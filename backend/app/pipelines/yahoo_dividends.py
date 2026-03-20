"""Yahoo Finance dividend pipeline — fetches dividend history for all active securities."""

import asyncio
import math
from datetime import date, timedelta
from typing import Any

import structlog
import yfinance as yf
from sqlalchemy import select, text

from app.db.engine import async_session
from app.db.models.securities import Security
from app.pipelines import register_pipeline
from app.pipelines.base import PipelineAdapter, RetryableError
from app.pipelines.yahoo_finance import _build_yahoo_ticker, MINOR_CURRENCY_MAP

logger = structlog.get_logger()


def _guess_frequency(dates: list[date]) -> str | None:
    """Guess dividend frequency from ex-dates (sorted ascending)."""
    if len(dates) < 2:
        return "annual"
    # Use recent dates only (last 5 years)
    recent = [d for d in dates if d.year >= dates[-1].year - 5]
    if len(recent) < 2:
        return "annual"
    gaps = []
    for i in range(1, len(recent)):
        gaps.append((recent[i] - recent[i - 1]).days)
    avg_gap = sum(gaps) / len(gaps)
    if avg_gap < 45:
        return "monthly"
    if avg_gap < 120:
        return "quarterly"
    if avg_gap < 240:
        return "semi_annual"
    return "annual"


@register_pipeline
class YahooDividends(PipelineAdapter):
    """Fetches dividend event history from Yahoo Finance for all active securities."""

    @property
    def source_name(self) -> str:
        return "yahoo_finance"

    @property
    def pipeline_name(self) -> str:
        return "yahoo_dividends"

    async def fetch(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        async with async_session() as session:
            result = await session.execute(
                select(Security).where(
                    Security.is_active.is_(True),
                    Security.asset_class.in_(["stock", "etf"]),
                )
            )
            securities = result.scalars().all()

        if not securities:
            return []

        raw_records: list[dict[str, Any]] = []

        for sec in securities:
            yahoo_ticker = _build_yahoo_ticker(sec.ticker, sec.exchange, sec.asset_class)
            try:
                ticker_obj = await asyncio.to_thread(lambda t=yahoo_ticker: yf.Ticker(t))
                divs = await asyncio.to_thread(lambda t=ticker_obj: t.dividends)

                if divs is None or divs.empty:
                    continue

                # Get currency from ticker info
                try:
                    info = await asyncio.to_thread(lambda t=ticker_obj: t.info)
                    yahoo_ccy = info.get("currency", sec.currency)
                except Exception:
                    yahoo_ccy = sec.currency

                minor = MINOR_CURRENCY_MAP.get(yahoo_ccy)
                divisor = minor[1] if minor else 1
                currency = minor[0] if minor else yahoo_ccy

                # Filter by date range
                ex_dates = []
                for idx, amount in divs.items():
                    ex_dt = idx.date() if hasattr(idx, "date") else idx
                    if from_date and ex_dt < from_date:
                        continue
                    if to_date and ex_dt > to_date:
                        continue

                    # Convert minor currency
                    adjusted_amount = float(amount) / divisor

                    if adjusted_amount <= 0 or math.isnan(adjusted_amount):
                        continue

                    ex_dates.append(ex_dt)
                    raw_records.append({
                        "security_id": sec.id,
                        "ticker": sec.ticker,
                        "ex_date": ex_dt,
                        "amount": adjusted_amount,
                        "currency": currency,
                    })

                # Determine frequency from date gaps and apply to all records for this security
                freq = _guess_frequency(sorted(ex_dates))
                for rec in raw_records:
                    if rec["security_id"] == sec.id:
                        rec["frequency"] = freq

            except Exception as e:
                logger.warning("yahoo_dividend_fetch_error", ticker=sec.ticker, error=str(e))
                continue

            await asyncio.sleep(0.2)

        logger.info("yahoo_dividends_fetched", records=len(raw_records))
        return raw_records

    async def validate(self, raw_records: list[dict]) -> tuple[list[dict], list[str]]:
        valid = []
        errors = []
        for rec in raw_records:
            if rec.get("amount", 0) <= 0:
                errors.append(f"{rec.get('ticker')} {rec.get('ex_date')}: invalid amount")
                continue
            valid.append(rec)
        return valid, errors

    async def transform(self, valid_records: list[dict]) -> list[dict]:
        transformed = []
        for rec in valid_records:
            amount_cents = round(rec["amount"] * 100)
            if amount_cents <= 0:
                continue  # Skip sub-cent dividends
            transformed.append({
                "security_id": rec["security_id"],
                "ex_date": rec["ex_date"],
                "amount_cents": amount_cents,
                "currency": rec["currency"],
                "frequency": rec.get("frequency"),
                "source": "yahoo_finance",
            })
        return transformed

    async def load(self, transformed_records: list[dict]) -> int:
        if not transformed_records:
            return 0

        upsert_sql = text("""
            INSERT INTO dividend_events (
                security_id, ex_date, amount_cents, currency, frequency, source
            ) VALUES (
                :security_id, :ex_date, :amount_cents, :currency, :frequency, :source
            )
            ON CONFLICT (security_id, ex_date) DO UPDATE SET
                amount_cents = EXCLUDED.amount_cents,
                currency = EXCLUDED.currency,
                frequency = EXCLUDED.frequency,
                updated_at = now()
        """)

        rows = 0
        async with async_session() as session:
            for rec in transformed_records:
                await session.execute(upsert_sql, rec)
                rows += 1
            await session.commit()

        logger.info("yahoo_dividends_loaded", rows=rows)
        return rows
