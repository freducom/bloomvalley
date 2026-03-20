"""ECB data pipeline — EUR exchange rates via SDMX API."""

import asyncio
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import httpx
import structlog

from app.db.engine import async_session
from app.pipelines import register_pipeline
from app.pipelines.base import NonRetryableError, PipelineAdapter, RetryableError
from sqlalchemy import text

logger = structlog.get_logger()

ECB_BASE = "https://data-api.ecb.europa.eu/service"
FX_CURRENCIES = ["USD", "GBP", "SEK", "NOK", "DKK", "CHF", "JPY"]

# Plausible FX rate ranges for validation
FX_RANGES: dict[str, tuple[float, float]] = {
    "USD": (0.70, 1.60),
    "GBP": (0.60, 1.20),
    "SEK": (8.00, 14.00),
    "NOK": (8.00, 14.00),
    "DKK": (7.40, 7.50),
    "CHF": (0.80, 1.30),
    "JPY": (100.0, 200.0),
}


@register_pipeline
class EcbFxRates(PipelineAdapter):
    """Fetches EUR exchange rates from the ECB SDMX API."""

    @property
    def source_name(self) -> str:
        return "ecb"

    @property
    def pipeline_name(self) -> str:
        return "ecb_fx_rates"

    async def fetch(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        if from_date is None:
            from_date = date.today() - timedelta(days=30)

        currencies = "+".join(FX_CURRENCIES)
        url = f"{ECB_BASE}/data/EXR/D.{currencies}.EUR.SP00.A"
        params = {
            "startPeriod": from_date.isoformat(),
            "format": "jsondata",
        }
        if to_date:
            params["endPeriod"] = to_date.isoformat()

        logger.info("ecb_fetch_start", currencies=len(FX_CURRENCIES), from_date=from_date.isoformat())

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url, params=params)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise RetryableError(f"ECB API returned {resp.status_code}")
                if resp.status_code == 404:
                    raise NonRetryableError(f"ECB series not found: {resp.status_code}")
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException as e:
            raise RetryableError(f"ECB timeout: {e}") from e
        except httpx.HTTPError as e:
            raise RetryableError(f"ECB HTTP error: {e}") from e

        return self._parse_sdmx(data)

    def _parse_sdmx(self, data: dict) -> list[dict[str, Any]]:
        """Parse ECB SDMX JSON response into flat rows."""
        rows = []
        structure = data.get("structure", {})
        datasets = data.get("dataSets", [])

        if not datasets or not structure:
            return rows

        # Extract currency dimension values
        series_dims = structure.get("dimensions", {}).get("series", [])
        currency_dim = next((d for d in series_dims if d["id"] == "CURRENCY"), None)
        if not currency_dim:
            return rows
        currencies = [v["id"] for v in currency_dim["values"]]

        # Extract time periods
        obs_dims = structure.get("dimensions", {}).get("observation", [])
        time_dim = next((d for d in obs_dims if d["id"] == "TIME_PERIOD"), None)
        if not time_dim:
            return rows
        dates = [v["id"] for v in time_dim["values"]]

        # Parse observations
        dataset = datasets[0]
        for series_key, series_data in dataset.get("series", {}).items():
            parts = series_key.split(":")
            # Currency is at index 1 in the series key
            currency_idx = int(parts[1]) if len(parts) > 1 else 0
            currency = currencies[currency_idx] if currency_idx < len(currencies) else None
            if not currency:
                continue

            for obs_key, obs_values in series_data.get("observations", {}).items():
                date_idx = int(obs_key)
                if date_idx >= len(dates):
                    continue
                rate = obs_values[0] if obs_values else None
                if rate is None:
                    continue

                rows.append({
                    "base_currency": "EUR",
                    "quote_currency": currency,
                    "date": dates[date_idx],
                    "rate": rate,
                    "source": "ecb",
                })

        logger.info("ecb_fetch_complete", records=len(rows))
        return rows

    async def validate(
        self, raw_records: list[dict]
    ) -> tuple[list[dict], list[str]]:
        valid = []
        errors = []
        today = date.today()

        for rec in raw_records:
            currency = rec["quote_currency"]
            rate = rec["rate"]
            rec_date = rec["date"]

            # Parse date string
            if isinstance(rec_date, str):
                try:
                    rec["date"] = date.fromisoformat(rec_date)
                except ValueError:
                    errors.append(f"ECB {currency} {rec_date}: invalid date")
                    continue

            # Skip weekends
            if rec["date"].weekday() >= 5:
                continue

            # Not in the future
            if rec["date"] > today + timedelta(days=1):
                errors.append(f"ECB {currency} {rec_date}: future date")
                continue

            # Rate positive
            if rate <= 0:
                errors.append(f"ECB {currency} {rec_date}: rate <= 0 ({rate})")
                continue

            # Plausible range check
            lo, hi = FX_RANGES.get(currency, (0.001, 100000))
            if rate < lo or rate > hi:
                errors.append(
                    f"ECB {currency} {rec_date}: rate {rate} outside range [{lo}, {hi}]"
                )
                continue

            rec["rate"] = Decimal(str(rate))
            valid.append(rec)

        return valid, errors

    async def transform(self, valid_records: list[dict]) -> list[dict]:
        # Already in the right format
        return valid_records

    async def load(self, transformed_records: list[dict]) -> int:
        if not transformed_records:
            return 0

        upsert_sql = text("""
            INSERT INTO fx_rates (base_currency, quote_currency, date, rate, source)
            VALUES (:base_currency, :quote_currency, :date, :rate, :source)
            ON CONFLICT (base_currency, quote_currency, date) DO UPDATE SET
                rate = EXCLUDED.rate,
                source = EXCLUDED.source
        """)

        rows_affected = 0
        async with async_session() as session:
            for rec in transformed_records:
                await session.execute(upsert_sql, rec)
                rows_affected += 1
            await session.commit()

        logger.info("ecb_fx_loaded", rows=rows_affected)
        return rows_affected
