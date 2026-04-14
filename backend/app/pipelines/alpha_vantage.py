"""Alpha Vantage data pipeline — backup price source and forex rates."""

import asyncio
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
import structlog
from sqlalchemy import select, text

from app.config import settings
from app.db.engine import async_session
from app.db.models.securities import Security
from app.pipelines import register_pipeline
from app.pipelines.base import (
    NonRetryableError, PipelineAdapter, RetryableError,
    get_last_known_prices, check_price_spike,
)

logger = structlog.get_logger()

AV_BASE = "https://www.alphavantage.co/query"

# Forex pairs to fetch (all EUR-based)
FX_PAIRS = [
    ("EUR", "USD"),
    ("EUR", "GBP"),
    ("EUR", "SEK"),
    ("EUR", "NOK"),
    ("EUR", "DKK"),
    ("EUR", "CHF"),
]


@register_pipeline
class AlphaVantagePrices(PipelineAdapter):
    """Fetches backup daily prices and forex rates from Alpha Vantage."""

    @property
    def source_name(self) -> str:
        return "alpha_vantage"

    @property
    def pipeline_name(self) -> str:
        return "alpha_vantage_prices"

    async def fetch(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        api_key = settings.ALPHA_VANTAGE_API_KEY
        if not api_key:
            logger.warning("alpha_vantage_no_api_key", msg="No API key configured, skipping")
            return []

        raw_records: list[dict[str, Any]] = []

        # --- 1. Daily prices for securities missing recent Yahoo data ---
        stale_cutoff = date.today() - timedelta(days=3)

        async with async_session() as session:
            # Find active non-crypto securities with no yahoo price in last 3 days
            result = await session.execute(
                text("""
                    SELECT s.id, s.ticker, s.currency
                    FROM securities s
                    WHERE s.is_active = true
                      AND s.asset_class != 'crypto'
                      AND NOT EXISTS (
                          SELECT 1 FROM prices p
                          WHERE p.security_id = s.id
                            AND p.source = 'yahoo_finance'
                            AND p.date >= :cutoff
                      )
                """),
                {"cutoff": stale_cutoff},
            )
            stale_securities = result.fetchall()

        logger.info(
            "alpha_vantage_fetch_start",
            stale_securities=len(stale_securities),
            fx_pairs=len(FX_PAIRS),
        )

        async with httpx.AsyncClient(timeout=30) as client:
            # Fetch daily prices for stale securities
            for row in stale_securities:
                sec_id, ticker, currency = row[0], row[1], row[2]
                try:
                    resp = await client.get(
                        AV_BASE,
                        params={
                            "function": "TIME_SERIES_DAILY",
                            "symbol": ticker,
                            "outputsize": "compact",
                            "apikey": api_key,
                        },
                    )

                    if resp.status_code == 429:
                        raise RetryableError("Alpha Vantage rate limited (429)")
                    resp.raise_for_status()

                    data = resp.json()

                    # Alpha Vantage returns error messages in JSON
                    if "Error Message" in data:
                        logger.warning(
                            "alpha_vantage_ticker_error",
                            ticker=ticker,
                            error=data["Error Message"],
                        )
                        await asyncio.sleep(3)
                        continue

                    if "Note" in data:
                        # API call frequency limit reached
                        raise RetryableError(f"Alpha Vantage limit: {data['Note']}")

                    time_series = data.get("Time Series (Daily)", {})

                    for date_str, values in time_series.items():
                        rec_date = datetime.strptime(date_str, "%Y-%m-%d").date()

                        if from_date and rec_date < from_date:
                            continue
                        if to_date and rec_date > to_date:
                            continue

                        raw_records.append({
                            "type": "price",
                            "security_id": sec_id,
                            "ticker": ticker,
                            "date": rec_date,
                            "open": float(values["1. open"]),
                            "high": float(values["2. high"]),
                            "low": float(values["3. low"]),
                            "close": float(values["4. close"]),
                            "volume": int(values["5. volume"]),
                            "currency": currency,
                        })

                except RetryableError:
                    raise
                except httpx.TimeoutException as e:
                    raise RetryableError(f"Alpha Vantage timeout: {e}") from e
                except Exception as e:
                    logger.warning(
                        "alpha_vantage_price_fetch_error",
                        ticker=ticker,
                        error=str(e),
                    )
                    continue

                # Free tier: 25 calls/day — sleep 3 seconds between requests
                await asyncio.sleep(3)

            # --- 2. Forex rates ---
            for base_cur, quote_cur in FX_PAIRS:
                try:
                    resp = await client.get(
                        AV_BASE,
                        params={
                            "function": "FX_DAILY",
                            "from_symbol": base_cur,
                            "to_symbol": quote_cur,
                            "outputsize": "compact",
                            "apikey": api_key,
                        },
                    )

                    if resp.status_code == 429:
                        raise RetryableError("Alpha Vantage rate limited (429)")
                    resp.raise_for_status()

                    data = resp.json()

                    if "Error Message" in data:
                        logger.warning(
                            "alpha_vantage_fx_error",
                            pair=f"{base_cur}/{quote_cur}",
                            error=data["Error Message"],
                        )
                        await asyncio.sleep(3)
                        continue

                    if "Note" in data:
                        raise RetryableError(f"Alpha Vantage limit: {data['Note']}")

                    time_series = data.get("Time Series FX (Daily)", {})

                    for date_str, values in time_series.items():
                        rec_date = datetime.strptime(date_str, "%Y-%m-%d").date()

                        if from_date and rec_date < from_date:
                            continue
                        if to_date and rec_date > to_date:
                            continue

                        raw_records.append({
                            "type": "fx",
                            "base_currency": base_cur,
                            "quote_currency": quote_cur,
                            "date": rec_date,
                            "rate": float(values["4. close"]),
                        })

                except RetryableError:
                    raise
                except httpx.TimeoutException as e:
                    raise RetryableError(f"Alpha Vantage timeout: {e}") from e
                except Exception as e:
                    logger.warning(
                        "alpha_vantage_fx_fetch_error",
                        pair=f"{base_cur}/{quote_cur}",
                        error=str(e),
                    )
                    continue

                await asyncio.sleep(3)

        logger.info("alpha_vantage_fetch_complete", records=len(raw_records))
        return raw_records

    async def validate(
        self, raw_records: list[dict]
    ) -> tuple[list[dict], list[str]]:
        valid = []
        errors = []
        today = date.today()

        # Fetch last known prices for spike detection
        price_sec_ids = {r["security_id"] for r in raw_records
                         if r.get("type") == "price" and r.get("security_id")}
        last_prices = await get_last_known_prices(price_sec_ids)

        for rec in raw_records:
            rec_date = rec["date"]
            label = rec.get("ticker") or f"{rec.get('base_currency')}/{rec.get('quote_currency')}"

            # Not in future
            if rec_date > today + timedelta(days=1):
                errors.append(f"{label} {rec_date}: future date")
                continue

            if rec["type"] == "price":
                close = rec.get("close")
                if close is None or (isinstance(close, float) and math.isnan(close)):
                    errors.append(f"{label} {rec_date}: missing close")
                    continue
                if close <= 0:
                    errors.append(f"{label} {rec_date}: close <= 0")
                    continue

                # Spike detection (auto-corrects GBp/GBX, rejects >10x moves)
                sec_id = rec.get("security_id")
                last_close = last_prices.get(sec_id)
                if last_close and not check_price_spike(rec, last_close, errors):
                    continue

                # Clean NaN values
                def clean(v: Any) -> Any:
                    if v is None:
                        return None
                    if isinstance(v, float) and math.isnan(v):
                        return None
                    return v

                rec["open"] = clean(rec.get("open"))
                rec["high"] = clean(rec.get("high"))
                rec["low"] = clean(rec.get("low"))

            elif rec["type"] == "fx":
                rate = rec.get("rate")
                if rate is None or (isinstance(rate, float) and math.isnan(rate)):
                    errors.append(f"{label} {rec_date}: missing rate")
                    continue
                if rate <= 0:
                    errors.append(f"{label} {rec_date}: rate <= 0")
                    continue

            valid.append(rec)

        return valid, errors

    async def transform(self, valid_records: list[dict]) -> list[dict]:
        transformed = []

        for rec in valid_records:
            if rec["type"] == "price":
                def to_cents(v: Any) -> int | None:
                    if v is None:
                        return None
                    c = round(float(v) * 100)
                    return max(c, 1) if c >= 0 else c  # minimum 1 cent

                open_cents = to_cents(rec.get("open"))
                high_cents = to_cents(rec.get("high"))
                low_cents = to_cents(rec.get("low"))
                close_cents = to_cents(rec["close"])

                # Fix OHLC constraints
                all_vals = [
                    v for v in [open_cents, high_cents, low_cents, close_cents]
                    if v is not None
                ]
                if all_vals:
                    if high_cents is not None:
                        high_cents = max(all_vals)
                    if low_cents is not None:
                        low_cents = min(all_vals)

                transformed.append({
                    "type": "price",
                    "security_id": rec["security_id"],
                    "date": rec["date"],
                    "open_cents": open_cents,
                    "high_cents": high_cents,
                    "low_cents": low_cents,
                    "close_cents": close_cents,
                    "adjusted_close_cents": close_cents,
                    "volume": rec.get("volume"),
                    "currency": rec["currency"],
                    "source": "alpha_vantage",
                })

            elif rec["type"] == "fx":
                transformed.append({
                    "type": "fx",
                    "base_currency": rec["base_currency"],
                    "quote_currency": rec["quote_currency"],
                    "date": rec["date"],
                    "rate": rec["rate"],
                    "source": "alpha_vantage",
                })

        return transformed

    async def load(self, transformed_records: list[dict]) -> int:
        if not transformed_records:
            return 0

        price_upsert_sql = text("""
            INSERT INTO prices (
                security_id, date, open_cents, high_cents, low_cents,
                close_cents, adjusted_close_cents, volume, currency, source
            ) VALUES (
                :security_id, :date, :open_cents, :high_cents, :low_cents,
                :close_cents, :adjusted_close_cents, :volume, :currency, :source
            )
            ON CONFLICT (security_id, date) DO UPDATE SET
                open_cents = EXCLUDED.open_cents,
                high_cents = EXCLUDED.high_cents,
                low_cents = EXCLUDED.low_cents,
                close_cents = EXCLUDED.close_cents,
                adjusted_close_cents = EXCLUDED.adjusted_close_cents,
                volume = EXCLUDED.volume,
                source = EXCLUDED.source
        """)

        fx_upsert_sql = text("""
            INSERT INTO fx_rates (base_currency, quote_currency, date, rate, source)
            VALUES (:base, :quote, :date, :rate, :source)
            ON CONFLICT (base_currency, quote_currency, date) DO UPDATE SET
                rate = EXCLUDED.rate,
                source = EXCLUDED.source
        """)

        rows_affected = 0
        async with async_session() as session:
            for rec in transformed_records:
                if rec["type"] == "price":
                    params = {k: v for k, v in rec.items() if k != "type"}
                    await session.execute(price_upsert_sql, params)
                elif rec["type"] == "fx":
                    await session.execute(fx_upsert_sql, {
                        "base": rec["base_currency"],
                        "quote": rec["quote_currency"],
                        "date": rec["date"],
                        "rate": rec["rate"],
                        "source": rec["source"],
                    })
                rows_affected += 1
            await session.commit()

        logger.info("alpha_vantage_loaded", rows=rows_affected)
        return rows_affected
