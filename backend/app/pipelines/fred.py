"""FRED macro indicators pipeline — interest rates, inflation, GDP, etc."""

import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import structlog
from sqlalchemy import text

from app.config import settings
from app.db.engine import async_session
from app.pipelines import register_pipeline
from app.pipelines.base import NonRetryableError, PipelineAdapter, RetryableError

logger = structlog.get_logger()

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Series definitions: (series_id, unit, category)
FRED_SERIES: list[tuple[str, str, str]] = [
    # --- US ---
    # Interest rates
    ("FEDFUNDS", "percent", "us_interest_rates"),
    ("DFF", "percent", "us_interest_rates"),
    # Treasury yields
    ("DGS2", "percent", "us_treasury_yields"),
    ("DGS5", "percent", "us_treasury_yields"),
    ("DGS10", "percent", "us_treasury_yields"),
    ("DGS30", "percent", "us_treasury_yields"),
    ("T10Y2Y", "percent", "us_treasury_yields"),
    ("T10Y3M", "percent", "us_treasury_yields"),
    # Inflation
    ("CPIAUCSL", "index", "us_inflation"),
    ("CPILFESL", "index", "us_inflation"),
    ("PCEPI", "index", "us_inflation"),
    ("T5YIE", "percent", "us_inflation"),
    ("T10YIE", "percent", "us_inflation"),
    # GDP
    ("GDP", "billions_usd", "us_gdp"),
    ("GDPC1", "billions_usd", "us_gdp"),
    # Labor
    ("UNRATE", "percent", "us_labor"),
    ("PAYEMS", "thousands", "us_labor"),
    ("ICSA", "number", "us_labor"),
    # Manufacturing
    ("MANEMP", "thousands", "us_manufacturing"),
    # Credit
    ("BAMLH0A0HYM2", "percent", "credit_spreads"),
    ("BAMLC0A0CM", "percent", "credit_spreads"),
    # --- Eurozone ---
    # ECB rates (FRED mirrors)
    ("ECBMRRFR", "percent", "ecb_rates"),
    ("ECBDFR", "percent", "ecb_rates"),
    # Eurozone inflation (HICP)
    ("CP0000EZ19M086NEST", "percent", "ez_inflation"),
    # Eurozone unemployment
    ("LRHUTTTTEZM156S", "percent", "ez_labor"),
    # Eurozone GDP (real, levels — quarterly)
    ("CLVMNACSCAB1GQEA19", "millions_eur", "ez_gdp"),
    # Germany 10Y bund yield (proxy for eurozone risk-free)
    ("IRLTLT01DEM156N", "percent", "ez_bond_yields"),
    # U Michigan Consumer Sentiment (PMI proxy — monthly, >80 expansion, <80 contraction)
    ("UMCSENT", "index", "us_sentiment"),
    # --- Finland ---
    # Finland unemployment
    ("LRHUTTTTFIM156S", "percent", "fi_labor"),
    # Finland real GDP (levels — quarterly)
    ("CLVMNACSCAB1GQFI", "millions_eur", "fi_gdp"),
    # Finland CPI inflation (annual %, World Bank)
    ("FPCPITOTLZGFIN", "percent", "fi_inflation"),
]


@register_pipeline
class FredMacroIndicators(PipelineAdapter):
    """Fetches macroeconomic indicators from FRED."""

    @property
    def source_name(self) -> str:
        return "fred"

    @property
    def pipeline_name(self) -> str:
        return "fred_macro_indicators"

    async def fetch(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        api_key = settings.FRED_API_KEY
        if not api_key:
            raise NonRetryableError("FRED_API_KEY not configured")

        if not from_date:
            from_date = date.today() - timedelta(days=365)
        if not to_date:
            to_date = date.today()

        logger.info(
            "fred_fetch_start",
            series_count=len(FRED_SERIES),
            from_date=from_date.isoformat(),
            to_date=to_date.isoformat(),
        )

        raw_records: list[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=30) as client:
            for series_id, unit, category in FRED_SERIES:
                try:
                    resp = await client.get(
                        FRED_BASE,
                        params={
                            "series_id": series_id,
                            "api_key": api_key,
                            "file_type": "json",
                            "observation_start": from_date.isoformat(),
                            "observation_end": to_date.isoformat(),
                        },
                    )

                    if resp.status_code == 429:
                        raise RetryableError("FRED rate limited (429)")
                    if resp.status_code == 400:
                        logger.warning("fred_series_not_found", series=series_id)
                        continue
                    resp.raise_for_status()

                    data = resp.json()
                    observations = data.get("observations", [])

                    for obs in observations:
                        value_str = obs.get("value", ".")
                        if value_str == "." or value_str == "":
                            continue  # Missing value marker

                        raw_records.append({
                            "indicator_code": series_id,
                            "date": obs["date"],
                            "value": value_str,
                            "unit": unit,
                            "category": category,
                        })

                except RetryableError:
                    raise
                except httpx.TimeoutException as e:
                    raise RetryableError(f"FRED timeout: {e}") from e
                except Exception as e:
                    logger.warning(
                        "fred_fetch_error", series=series_id, error=str(e)
                    )
                    continue

                # Rate limiting: ~500ms between requests (well under 120/min)
                await asyncio.sleep(0.5)

        logger.info("fred_fetch_complete", records=len(raw_records))
        return raw_records

    async def validate(
        self, raw_records: list[dict]
    ) -> tuple[list[dict], list[str]]:
        valid = []
        errors = []

        for rec in raw_records:
            code = rec["indicator_code"]
            rec_date_str = rec["date"]

            # Parse date
            try:
                rec_date = date.fromisoformat(rec_date_str)
            except (ValueError, TypeError):
                errors.append(f"{code}: invalid date {rec_date_str}")
                continue

            # Parse value
            try:
                value = Decimal(rec["value"])
            except Exception:
                errors.append(f"{code} {rec_date}: invalid value {rec['value']}")
                continue

            # Not in future
            if rec_date > date.today() + timedelta(days=1):
                errors.append(f"{code} {rec_date}: future date")
                continue

            rec["date"] = rec_date
            rec["value"] = value
            valid.append(rec)

        return valid, errors

    async def transform(self, valid_records: list[dict]) -> list[dict]:
        return [
            {
                "indicator_code": rec["indicator_code"],
                "date": rec["date"],
                "value": rec["value"],
                "unit": rec["unit"],
                "source": "fred",
            }
            for rec in valid_records
        ]

    async def load(self, transformed_records: list[dict]) -> int:
        if not transformed_records:
            return 0

        upsert_sql = text("""
            INSERT INTO macro_indicators (
                indicator_code, date, value, unit, source
            ) VALUES (
                :indicator_code, :date, :value, :unit, :source
            )
            ON CONFLICT (indicator_code, date) DO UPDATE SET
                value = EXCLUDED.value,
                unit = EXCLUDED.unit,
                source = EXCLUDED.source
        """)

        rows_affected = 0
        async with async_session() as session:
            for rec in transformed_records:
                await session.execute(upsert_sql, rec)
                rows_affected += 1
            await session.commit()

        logger.info("fred_macro_loaded", rows=rows_affected)
        return rows_affected
