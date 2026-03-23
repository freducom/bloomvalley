"""Finnhub Earnings pipeline — fetches earnings calendar and estimates."""

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx
import structlog
from sqlalchemy import select

from app.config import settings
from app.db.engine import async_session
from app.db.models.fundamentals import EarningsReport
from app.db.models.securities import Security
from app.pipelines import register_pipeline
from app.pipelines.base import PipelineAdapter

logger = structlog.get_logger()

FINNHUB_BASE = "https://finnhub.io/api/v1"


def _to_finnhub_ticker(ticker: str) -> str:
    """Convert Yahoo-style ticker to Finnhub format."""
    if ticker.endswith("-USD"):
        return f"BINANCE:{ticker.replace('-USD', '')}USDT"
    return ticker


async def _fetch_earnings_for_ticker(
    client: httpx.AsyncClient, ticker: str
) -> list[dict]:
    """Fetch earnings history with estimates from Finnhub."""
    fh_ticker = _to_finnhub_ticker(ticker)
    try:
        resp = await client.get(
            f"{FINNHUB_BASE}/stock/earnings",
            params={"symbol": fh_ticker, "limit": 12, "token": settings.FINNHUB_API_KEY},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json() or []
    except Exception as e:
        logger.debug("finnhub_earnings_fetch_error", ticker=ticker, error=str(e))
        return []


async def _fetch_earnings_calendar(
    client: httpx.AsyncClient, from_date: str, to_date: str
) -> list[dict]:
    """Fetch upcoming earnings calendar from Finnhub."""
    try:
        resp = await client.get(
            f"{FINNHUB_BASE}/calendar/earnings",
            params={"from": from_date, "to": to_date, "token": settings.FINNHUB_API_KEY},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("earningsCalendar", [])
    except Exception as e:
        logger.warning("finnhub_calendar_error", error=str(e))
        return []


def _parse_quarter(period: str) -> tuple[int, int] | None:
    """Parse Finnhub period like '2026-03-31' into (year, quarter)."""
    try:
        dt = datetime.strptime(period, "%Y-%m-%d")
        quarter = (dt.month - 1) // 3 + 1
        return dt.year, quarter
    except (ValueError, TypeError):
        return None


@register_pipeline
class FinnhubEarningsPipeline(PipelineAdapter):
    """Fetches earnings estimates and calendar from Finnhub."""

    @property
    def source_name(self) -> str:
        return "finnhub"

    @property
    def pipeline_name(self) -> str:
        return "finnhub_earnings"

    async def fetch(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        if not settings.FINNHUB_API_KEY:
            logger.error("finnhub_api_key_missing")
            return []

        # Load active securities (stocks only, skip crypto/ETFs with no earnings)
        async with async_session() as session:
            result = await session.execute(
                select(Security)
                .where(Security.is_active.is_(True))
                .where(Security.ticker.isnot(None))
                .where(Security.asset_class.in_(["stock"]))
            )
            securities = {s.ticker: s for s in result.scalars().all()}

        raw: list[dict[str, Any]] = []

        async with httpx.AsyncClient(
            headers={"User-Agent": "BloomvalleyTerminal/1.0"},
        ) as client:
            # 1. Fetch upcoming earnings calendar (next 90 days)
            cal_from = date.today().isoformat()
            cal_to = (date.today() + timedelta(days=90)).isoformat()
            calendar = await _fetch_earnings_calendar(client, cal_from, cal_to)

            # Map calendar entries to our securities
            for entry in calendar:
                ticker = entry.get("symbol", "")
                if ticker in securities:
                    raw.append({
                        "type": "calendar",
                        "ticker": ticker,
                        "security_id": securities[ticker].id,
                        "report_date": entry.get("date"),
                        "eps_estimate": entry.get("epsEstimate"),
                        "revenue_estimate": entry.get("revenueEstimate"),
                        "quarter": entry.get("quarter"),
                        "year": entry.get("year"),
                    })

            # 2. Fetch historical earnings with surprise data per security
            for i, (ticker, sec) in enumerate(securities.items()):
                earnings = await _fetch_earnings_for_ticker(client, ticker)
                for e in earnings:
                    parsed = _parse_quarter(e.get("period", ""))
                    if not parsed:
                        continue
                    year, quarter = parsed
                    raw.append({
                        "type": "historical",
                        "ticker": ticker,
                        "security_id": sec.id,
                        "year": year,
                        "quarter": quarter,
                        "report_date": e.get("period"),
                        "eps_actual": e.get("actual"),
                        "eps_estimate": e.get("estimate"),
                        "surprise_pct": e.get("surprisePercent"),
                        "revenue_estimate": None,
                    })

                # Rate limit: ~10/sec for 60/min
                if (i + 1) % 8 == 0:
                    await asyncio.sleep(1.0)

        logger.info("finnhub_earnings_fetched", total=len(raw), securities=len(securities))
        return raw

    async def validate(
        self, raw_records: list[dict]
    ) -> tuple[list[dict], list[str]]:
        valid = []
        errors = []
        for rec in raw_records:
            if not rec.get("security_id"):
                errors.append(f"No security_id for {rec.get('ticker')}")
                continue
            if not rec.get("year") or not rec.get("quarter"):
                continue
            valid.append(rec)
        return valid, errors

    async def transform(self, valid_records: list[dict]) -> list[dict]:
        return valid_records

    async def load(self, transformed_records: list[dict]) -> int:
        if not transformed_records:
            return 0

        rows = 0
        async with async_session() as session:
            for rec in transformed_records:
                # Check if record exists
                existing = await session.execute(
                    select(EarningsReport).where(
                        EarningsReport.security_id == rec["security_id"],
                        EarningsReport.fiscal_year == rec["year"],
                        EarningsReport.quarter == rec["quarter"],
                    )
                )
                report = existing.scalar_one_or_none()

                eps_est = rec.get("eps_estimate")
                eps_act = rec.get("eps_actual")
                rev_est = rec.get("revenue_estimate")
                surprise = rec.get("surprise_pct")

                if report:
                    # Update estimate/surprise fields
                    changed = False
                    if eps_est is not None and report.eps_estimate_cents is None:
                        report.eps_estimate_cents = round(eps_est * 100)
                        changed = True
                    if eps_act is not None and report.eps_cents is None:
                        report.eps_cents = round(eps_act * 100)
                        changed = True
                    if surprise is not None and report.surprise_pct is None:
                        report.surprise_pct = Decimal(str(surprise))
                        changed = True
                    if rev_est is not None and report.revenue_estimate_cents is None:
                        report.revenue_estimate_cents = round(rev_est * 100)
                        changed = True
                    if rec.get("report_date") and not report.report_date:
                        try:
                            report.report_date = datetime.strptime(rec["report_date"], "%Y-%m-%d").date()
                        except (ValueError, TypeError):
                            pass
                        changed = True
                    if changed:
                        rows += 1
                else:
                    # Create new record
                    report_date = None
                    if rec.get("report_date"):
                        try:
                            report_date = datetime.strptime(rec["report_date"], "%Y-%m-%d").date()
                        except (ValueError, TypeError):
                            pass

                    new_report = EarningsReport(
                        security_id=rec["security_id"],
                        fiscal_quarter=f"Q{rec['quarter']} {rec['year']}",
                        fiscal_year=rec["year"],
                        quarter=rec["quarter"],
                        report_date=report_date,
                        eps_cents=round(eps_act * 100) if eps_act is not None else None,
                        eps_estimate_cents=round(eps_est * 100) if eps_est is not None else None,
                        revenue_estimate_cents=round(rev_est * 100) if rev_est is not None else None,
                        surprise_pct=Decimal(str(surprise)) if surprise is not None else None,
                        source="finnhub",
                    )
                    session.add(new_report)
                    rows += 1

            await session.commit()

        logger.info("finnhub_earnings_loaded", rows=rows)
        return rows
