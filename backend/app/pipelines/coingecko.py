"""CoinGecko data pipeline — cryptocurrency prices."""

import asyncio
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
import structlog
from sqlalchemy import select, text

from app.db.engine import async_session
from app.db.models.securities import Security
from app.pipelines import register_pipeline
from app.pipelines.base import NonRetryableError, PipelineAdapter, RetryableError

logger = structlog.get_logger()

CG_BASE = "https://api.coingecko.com/api/v3"


@register_pipeline
class CoinGeckoPrices(PipelineAdapter):
    """Fetches crypto prices from CoinGecko."""

    @property
    def source_name(self) -> str:
        return "coingecko"

    @property
    def pipeline_name(self) -> str:
        return "coingecko_prices"

    async def fetch(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        # Get crypto securities with coingecko_id
        async with async_session() as session:
            result = await session.execute(
                select(Security).where(
                    Security.asset_class == "crypto",
                    Security.is_active.is_(True),
                    Security.coingecko_id.isnot(None),
                )
            )
            cryptos = result.scalars().all()

        if not cryptos:
            return []

        id_map = {c.coingecko_id: c for c in cryptos}
        coin_ids = list(id_map.keys())

        logger.info("coingecko_fetch_start", coins=len(coin_ids))

        raw_records: list[dict[str, Any]] = []

        # Fetch OHLC data for each coin
        async with httpx.AsyncClient(timeout=30) as client:
            for coin_id in coin_ids:
                try:
                    raw_days = 30
                    if from_date:
                        raw_days = max(1, (date.today() - from_date).days)
                    # CoinGecko OHLC only accepts: 1, 7, 14, 30, 90, 180, 365
                    allowed = [1, 7, 14, 30, 90, 180, 365]
                    days = min((d for d in allowed if d >= raw_days), default=365)

                    resp = await client.get(
                        f"{CG_BASE}/coins/{coin_id}/ohlc",
                        params={"vs_currency": "usd", "days": days},
                    )

                    if resp.status_code == 429:
                        raise RetryableError("CoinGecko rate limited (429)")
                    if resp.status_code == 404:
                        logger.warning("coingecko_coin_not_found", coin=coin_id)
                        continue
                    resp.raise_for_status()

                    ohlc_data = resp.json()
                    sec = id_map[coin_id]

                    for candle in ohlc_data:
                        if len(candle) < 5:
                            continue
                        ts_ms, o, h, lo, c = candle[0], candle[1], candle[2], candle[3], candle[4]
                        candle_date = datetime.fromtimestamp(
                            ts_ms / 1000, tz=timezone.utc
                        ).date()

                        # Filter by date range
                        if from_date and candle_date < from_date:
                            continue
                        if to_date and candle_date > to_date:
                            continue

                        raw_records.append({
                            "security_id": sec.id,
                            "coin_id": coin_id,
                            "date": candle_date,
                            "open": o,
                            "high": h,
                            "low": lo,
                            "close": c,
                            "volume": None,  # OHLC endpoint doesn't include volume
                            "currency": sec.currency,
                        })

                except RetryableError:
                    raise
                except httpx.TimeoutException as e:
                    raise RetryableError(f"CoinGecko timeout: {e}") from e
                except Exception as e:
                    logger.warning("coingecko_fetch_error", coin=coin_id, error=str(e))
                    continue

                # Rate limiting: 6 seconds between requests (free tier safe)
                await asyncio.sleep(6)

        # Deduplicate: keep only the last candle per (security_id, date)
        seen: dict[tuple[int, date], dict] = {}
        for rec in raw_records:
            key = (rec["security_id"], rec["date"])
            seen[key] = rec  # later entry overwrites
        raw_records = list(seen.values())

        logger.info("coingecko_fetch_complete", records=len(raw_records))
        return raw_records

    async def validate(
        self, raw_records: list[dict]
    ) -> tuple[list[dict], list[str]]:
        valid = []
        errors = []
        today = date.today()

        for rec in raw_records:
            coin = rec.get("coin_id", "?")
            rec_date = rec["date"]

            # Close required and positive
            close = rec.get("close")
            if close is None or (isinstance(close, float) and math.isnan(close)):
                errors.append(f"{coin} {rec_date}: missing close")
                continue
            if close <= 0:
                errors.append(f"{coin} {rec_date}: close <= 0")
                continue

            # Not in future
            if rec_date > today + timedelta(days=1):
                errors.append(f"{coin} {rec_date}: future date")
                continue

            # Clean NaN
            def clean(v):
                if v is None:
                    return None
                if isinstance(v, float) and math.isnan(v):
                    return None
                return v

            rec["open"] = clean(rec.get("open"))
            rec["high"] = clean(rec.get("high"))
            rec["low"] = clean(rec.get("low"))

            valid.append(rec)

        return valid, errors

    async def transform(self, valid_records: list[dict]) -> list[dict]:
        transformed = []

        for rec in valid_records:
            def to_cents(v):
                if v is None:
                    return None
                c = round(float(v) * 100)
                return max(c, 1) if c >= 0 else c  # minimum 1 cent

            open_cents = to_cents(rec.get("open"))
            high_cents = to_cents(rec.get("high"))
            low_cents = to_cents(rec.get("low"))
            close_cents = to_cents(rec["close"])

            # Fix OHLC constraints
            all_vals = [v for v in [open_cents, high_cents, low_cents, close_cents] if v is not None]
            if all_vals:
                if high_cents is not None:
                    high_cents = max(all_vals)
                if low_cents is not None:
                    low_cents = min(all_vals)

            transformed.append({
                "security_id": rec["security_id"],
                "date": rec["date"],
                "open_cents": open_cents,
                "high_cents": high_cents,
                "low_cents": low_cents,
                "close_cents": close_cents,
                "adjusted_close_cents": close_cents,
                "volume": rec.get("volume"),
                "currency": rec["currency"],
                "source": "coingecko",
            })

        return transformed

    async def load(self, transformed_records: list[dict]) -> int:
        if not transformed_records:
            return 0

        upsert_sql = text("""
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

        rows_affected = 0
        async with async_session() as session:
            for rec in transformed_records:
                await session.execute(upsert_sql, rec)
                rows_affected += 1
            await session.commit()

        logger.info("coingecko_prices_loaded", rows=rows_affected)
        return rows_affected
