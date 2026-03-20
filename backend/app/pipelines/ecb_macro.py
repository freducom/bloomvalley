"""ECB macro indicators pipeline — eurozone rates, yields, inflation, GDP."""

import asyncio
import csv
import io
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import httpx
import structlog
from sqlalchemy import text

from app.db.engine import async_session
from app.pipelines import register_pipeline
from app.pipelines.base import PipelineAdapter, RetryableError

logger = structlog.get_logger()

ECB_BASE = "https://data-api.ecb.europa.eu/service/data"

# (dataflow, series_key, indicator_code, unit, category)
ECB_SERIES: list[tuple[str, str, str, str, str]] = [
    # ECB key rates (daily)
    ("FM", "D.U2.EUR.4F.KR.MRR_FR.LEV", "ECB_MRR", "percent", "ecb_rates"),
    ("FM", "D.U2.EUR.4F.KR.DFR.LEV", "ECB_DFR", "percent", "ecb_rates"),
    # Euro area AAA yield curve spot rates (business daily)
    ("YC", "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y", "EZ_YC_2Y", "percent", "ez_bond_yields"),
    ("YC", "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_5Y", "EZ_YC_5Y", "percent", "ez_bond_yields"),
    ("YC", "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y", "EZ_YC_10Y", "percent", "ez_bond_yields"),
    ("YC", "B.U2.EUR.4F.G_N_A.SV_C_YM.SR_30Y", "EZ_YC_30Y", "percent", "ez_bond_yields"),
    # Eurozone HICP headline inflation (monthly, YoY %)
    ("HICP", "M.U2.N.000000.4D0.ANR", "EZ_HICP", "percent", "ez_inflation"),
    # Eurozone HICP core (ex energy, food, alcohol, tobacco)
    ("HICP", "M.U2.N.XEF000.4D0.ANR", "EZ_HICP_CORE", "percent", "ez_inflation"),
    # Finland HICP headline
    ("HICP", "M.FI.N.000000.4D0.ANR", "FI_HICP", "percent", "fi_inflation"),
    # Eurozone unemployment (monthly)
    ("LFSI", "M.I9.S.UNEHRT.TOTAL0.15_74.T", "EZ_UNEMP", "percent", "ez_labor"),
    # Finland unemployment (monthly)
    ("LFSI", "M.FI.S.UNEHRT.TOTAL0.15_74.T", "FI_UNEMP", "percent", "fi_labor"),
    # Eurozone GDP growth YoY (quarterly)
    ("MNA", "Q.Y.I9.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.GY", "EZ_GDP_YOY", "percent", "ez_gdp"),
    # Finland GDP growth YoY (quarterly)
    ("MNA", "Q.Y.FI.W2.S1.S1.B.B1GQ._Z._Z._Z.XDC.LR.GY", "FI_GDP_YOY", "percent", "fi_gdp"),
]


def _parse_ecb_csv(csv_text: str) -> list[dict[str, str]]:
    """Parse ECB CSV response into list of dicts with TIME_PERIOD and OBS_VALUE."""
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = []
    for row in reader:
        tp = row.get("TIME_PERIOD", "").strip()
        ov = row.get("OBS_VALUE", "").strip()
        if tp and ov:
            rows.append({"time": tp, "value": ov})
    return rows


def _period_to_date(period: str) -> date | None:
    """Convert ECB time period to date. Handles YYYY-MM-DD, YYYY-MM, YYYY-Qn."""
    try:
        if len(period) == 10:  # YYYY-MM-DD
            return date.fromisoformat(period)
        if len(period) == 7:  # YYYY-MM
            return date.fromisoformat(period + "-01")
        if "Q" in period.upper():  # YYYY-Q1
            year, q = period.split("-Q")
            month = (int(q) - 1) * 3 + 1
            return date(int(year), month, 1)
    except (ValueError, IndexError):
        pass
    return None


@register_pipeline
class EcbMacroIndicators(PipelineAdapter):
    """Fetches eurozone macro indicators directly from ECB Statistical Data Warehouse."""

    @property
    def source_name(self) -> str:
        return "ecb"

    @property
    def pipeline_name(self) -> str:
        return "ecb_macro_indicators"

    async def fetch(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        if not from_date:
            from_date = date.today() - timedelta(days=365)
        if not to_date:
            to_date = date.today()

        logger.info(
            "ecb_macro_fetch_start",
            series_count=len(ECB_SERIES),
            from_date=from_date.isoformat(),
            to_date=to_date.isoformat(),
        )

        raw_records: list[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=30) as client:
            for dataflow, series_key, code, unit, category in ECB_SERIES:
                url = f"{ECB_BASE}/{dataflow}/{series_key}"
                try:
                    resp = await client.get(
                        url,
                        params={
                            "format": "csvdata",
                            "startPeriod": from_date.isoformat(),
                            "endPeriod": to_date.isoformat(),
                            "detail": "dataonly",
                        },
                        headers={"Accept": "text/csv"},
                    )

                    if resp.status_code == 404:
                        logger.warning("ecb_series_not_found", code=code, url=url)
                        continue
                    if resp.status_code == 429:
                        raise RetryableError("ECB rate limited (429)")
                    resp.raise_for_status()

                    rows = _parse_ecb_csv(resp.text)
                    for row in rows:
                        raw_records.append({
                            "indicator_code": code,
                            "date": row["time"],
                            "value": row["value"],
                            "unit": unit,
                            "category": category,
                        })

                    logger.info("ecb_series_fetched", code=code, rows=len(rows))

                except RetryableError:
                    raise
                except httpx.TimeoutException as e:
                    raise RetryableError(f"ECB timeout on {code}: {e}") from e
                except Exception as e:
                    logger.warning("ecb_fetch_error", code=code, error=str(e))
                    continue

                await asyncio.sleep(0.3)

        logger.info("ecb_macro_fetch_complete", records=len(raw_records))
        return raw_records

    async def validate(
        self, raw_records: list[dict]
    ) -> tuple[list[dict], list[str]]:
        valid = []
        errors = []

        for rec in raw_records:
            code = rec["indicator_code"]
            rec_date = _period_to_date(rec["date"])
            if not rec_date:
                errors.append(f"{code}: invalid date {rec['date']}")
                continue

            try:
                value = Decimal(rec["value"])
            except Exception:
                errors.append(f"{code} {rec_date}: invalid value {rec['value']}")
                continue

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
                "source": "ecb",
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

        logger.info("ecb_macro_loaded", rows=rows_affected)
        return rows_affected
