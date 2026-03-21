"""Kenneth French Data Library pipeline — Fama-French 5-factor daily data."""

import asyncio
import io
import zipfile
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pandas as pd
import structlog
from sqlalchemy import text

from app.db.engine import async_session
from app.pipelines import register_pipeline
from app.pipelines.base import NonRetryableError, PipelineAdapter, RetryableError

logger = structlog.get_logger()

FRENCH_BASE_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"

FACTOR_FILES = {
    "us_daily": "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip",
    "europe_daily": "Europe_5_Factors_Daily_CSV.zip",
}

FACTOR_COLUMNS = ["mkt", "smb", "hml", "rmw", "cma", "rf"]

# Indicator codes stored in macro_indicators table
# Pattern: ff5_{region}_{factor}  e.g. ff5_us_mkt_rf, ff5_eu_smb
REGION_PREFIX = {
    "us_daily": "ff5_us",
    "europe_daily": "ff5_eu",
}


def _parse_french_csv(raw: str, factor_set: str) -> pd.DataFrame:
    """Parse a Kenneth French Data Library CSV.

    The CSV has header rows and footer rows that need trimming.
    Data section starts after the line containing 'Mkt-RF'.
    Values are percentages — divide by 100 to get decimals.
    """
    lines = raw.split("\n")
    data_start = None
    data_end = None

    for i, line in enumerate(lines):
        if "Mkt-RF" in line and data_start is None:
            data_start = i
        if data_start is not None and i > data_start and line.strip() == "":
            data_end = i
            break

    if data_start is None:
        raise ValueError(f"Could not find data header in factor file: {factor_set}")

    if data_end is None:
        data_end = len(lines)

    csv_text = "\n".join(lines[data_start:data_end])
    df = pd.read_csv(io.StringIO(csv_text), skipinitialspace=True)

    # Clean column names
    df.columns = [c.strip() for c in df.columns]
    col_map = {
        "Mkt-RF": "mkt",
        "SMB": "smb",
        "HML": "hml",
        "RMW": "rmw",
        "CMA": "cma",
        "RF": "rf",
    }
    df = df.rename(columns=col_map)

    # Parse date column (first unnamed column)
    first_col = df.columns[0]
    df["date"] = pd.to_datetime(df[first_col].astype(str).str.strip(), format="%Y%m%d")

    # Convert from percentages to decimals
    for col in FACTOR_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce") / 100.0

    df = df.drop(columns=[first_col])
    df = df.dropna(subset=["date"])

    return df[["date"] + FACTOR_COLUMNS]


@register_pipeline
class FrenchFactors(PipelineAdapter):
    """Fetches Fama-French 5-factor daily data from Kenneth French Data Library."""

    @property
    def source_name(self) -> str:
        return "fred"

    @property
    def pipeline_name(self) -> str:
        return "french_factors"

    async def fetch(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        logger.info(
            "french_factors_fetch_start",
            factor_files=list(FACTOR_FILES.keys()),
        )

        raw_records: list[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=60) as client:
            for factor_set, filename in FACTOR_FILES.items():
                url = FRENCH_BASE_URL + filename
                try:
                    logger.info(
                        "french_factors_downloading",
                        factor_set=factor_set,
                        url=url,
                    )

                    resp = await client.get(url)

                    if resp.status_code == 429:
                        raise RetryableError(
                            f"French Data Library rate limited (429) for {factor_set}"
                        )
                    resp.raise_for_status()

                    # Extract CSV from ZIP
                    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                        csv_name = z.namelist()[0]
                        with z.open(csv_name) as f:
                            raw_text = f.read().decode("utf-8")

                    df = _parse_french_csv(raw_text, factor_set)

                    # Filter by date range if specified
                    if from_date:
                        df = df[df["date"] >= pd.Timestamp(from_date)]
                    if to_date:
                        df = df[df["date"] <= pd.Timestamp(to_date)]

                    prefix = REGION_PREFIX[factor_set]

                    for _, row in df.iterrows():
                        row_date = row["date"].date()
                        for factor in FACTOR_COLUMNS:
                            value = row[factor]
                            if pd.isna(value):
                                continue
                            # Build indicator code: ff5_us_mkt_rf, ff5_eu_smb, etc.
                            if factor == "mkt":
                                indicator_code = f"{prefix}_mkt_rf"
                            else:
                                indicator_code = f"{prefix}_{factor}"

                            raw_records.append({
                                "indicator_code": indicator_code,
                                "date": row_date.isoformat(),
                                "value": str(value),
                                "unit": "decimal",
                                "factor_set": factor_set,
                            })

                except RetryableError:
                    raise
                except httpx.TimeoutException as e:
                    raise RetryableError(
                        f"French Data Library timeout for {factor_set}: {e}"
                    ) from e
                except Exception as e:
                    logger.warning(
                        "french_factors_fetch_error",
                        factor_set=factor_set,
                        error=str(e),
                    )
                    continue

                # Rate limiting: 2-second delay between requests
                await asyncio.sleep(2.0)

        logger.info("french_factors_fetch_complete", records=len(raw_records))
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

        logger.info("french_factors_loaded", rows=rows_affected)
        return rows_affected
