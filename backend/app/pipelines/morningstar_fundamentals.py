"""Morningstar fundamentals pipeline — fetches ROIC, leverage, and profitability
metrics from the Morningstar SAL API and overrides Yahoo-sourced values.

Morningstar standardises financials across IFRS/GAAP and cleanly separates
financial debt from lease liabilities, giving more accurate ROIC and leverage
figures than Yahoo Finance (which lumps IFRS 16 leases into totalDebt).

Flow:
1. Resolve each stock's Morningstar SecId (via ISIN or name search, cached
   in ``securities.morningstar_id``).
2. Fetch ``profitabilityAndEfficiency`` (ROIC, ROE, ROA, margins with 10yr
   history) and ``financialHealth`` (leverage, D/E, interest coverage).
3. Override ROIC and Net Debt/EBITDA in ``security_fundamentals`` where
   Morningstar data is available.
"""

import asyncio
import json
from datetime import date
from typing import Any

import httpx
import structlog
from sqlalchemy import select, text

from app.db.engine import async_session
from app.db.models.securities import Security
from app.pipelines import register_pipeline
from app.pipelines.base import PipelineAdapter, RetryableError

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Morningstar API configuration
# ---------------------------------------------------------------------------

# Screener API for ticker/ISIN -> SecId resolution (no auth needed)
MS_SCREENER_URL = (
    "https://lt.morningstar.com/api/rest.svc/klr5zyak8x/security/screener"
)

# SAL API for detailed fundamentals
MS_SAL_BASE = "https://api-global.morningstar.com/sal-service/v1/stock"
MS_API_KEY = "lstzFDEOhfFNMLikKa0am9mgEKLBl49T"
MS_SAL_PARAMS = {"clientId": "MDC", "version": "4.71.0"}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Map our exchange MICs to Morningstar exchange IDs
_EXCHANGE_MAP = {
    "XHEL": "XHEL",
    "XSTO": "XSTO",
    "XOSL": "XOSL",
    "XCSE": "XCSE",
    "XICE": "XICE",
    "XAMS": "XAMS",
    "XPAR": "XPAR",
    "XETR": "XETR",
    "XFRA": "XFRA",
    "XLON": "XLON",
    "XSWX": "XSWX",
    "XMIL": "XMIL",
    "XBRU": "XBRU",
    "XNYS": "XNYS",
    "XNAS": "XNAS",
}


# ---------------------------------------------------------------------------
# SecId resolution
# ---------------------------------------------------------------------------


async def _resolve_sec_id(
    client: httpx.AsyncClient,
    security: Security,
) -> str | None:
    """Resolve a security to its Morningstar SecId.

    Strategy:
    1. If ISIN is available, search by ISIN (most reliable).
    2. Otherwise, search by company name.
    3. Filter results to match our exchange.
    """
    exchange_suffix = _EXCHANGE_MAP.get(security.exchange or "", "")
    ms_exchange = f"EX$$$${exchange_suffix}" if exchange_suffix else None

    # Try ISIN first
    search_term = security.isin or security.name
    try:
        resp = await client.get(
            MS_SCREENER_URL,
            params={
                "outputType": "json",
                "version": "1",
                "languageId": "en",
                "securityDataPoints": "SecId,Name,ExchangeId,ISIN",
                "term": search_term,
                "universeIds": "E0WWE$$ALL",
            },
        )
        if resp.status_code == 429:
            raise RetryableError("Morningstar screener rate-limited")
        if resp.status_code != 200:
            return None

        body = resp.content.decode("utf-8-sig")
        data = json.loads(body)
        rows = data.get("rows", [])

        if not rows:
            # If ISIN search failed, try by name
            if security.isin and search_term == security.isin:
                return await _resolve_by_name(client, security, ms_exchange)
            return None

        # If we have an exchange to filter on, prefer that match
        if ms_exchange:
            for row in rows:
                if row.get("ExchangeId") == ms_exchange:
                    return row["SecId"]

        # Fallback: first result
        return rows[0]["SecId"]

    except (httpx.TimeoutException, httpx.ConnectError) as e:
        logger.warning("morningstar_resolve_error", ticker=security.ticker, error=str(e))
        return None


async def _resolve_by_name(
    client: httpx.AsyncClient,
    security: Security,
    ms_exchange: str | None,
) -> str | None:
    """Fallback: search by company name when ISIN is not available."""
    # Clean name: remove suffixes like "Oyj", "AB", "ASA", "Inc."
    name = security.name
    for suffix in ["Oyj", "AB", "ASA", "Inc.", "Inc", "Corp.", "Corp", "PLC", "SE", "SA", "N.V.", "AG"]:
        name = name.replace(f" {suffix}", "")
    name = name.strip()

    try:
        resp = await client.get(
            MS_SCREENER_URL,
            params={
                "outputType": "json",
                "version": "1",
                "languageId": "en",
                "securityDataPoints": "SecId,Name,ExchangeId,ISIN",
                "term": name,
                "universeIds": "E0WWE$$ALL",
            },
        )
        if resp.status_code != 200:
            return None

        body = resp.content.decode("utf-8-sig")
        data = json.loads(body)
        rows = data.get("rows", [])

        if ms_exchange:
            for row in rows:
                if row.get("ExchangeId") == ms_exchange:
                    return row["SecId"]

        return rows[0]["SecId"] if rows else None

    except (httpx.TimeoutException, httpx.ConnectError):
        return None


# ---------------------------------------------------------------------------
# SAL API fetchers
# ---------------------------------------------------------------------------


async def _fetch_profitability(
    client: httpx.AsyncClient, sec_id: str
) -> dict[str, Any] | None:
    """Fetch ROIC, ROE, ROA and efficiency metrics."""
    try:
        resp = await client.get(
            f"{MS_SAL_BASE}/keyMetrics/profitabilityAndEfficiency/{sec_id}",
            params=MS_SAL_PARAMS,
            headers={"apikey": MS_API_KEY},
        )
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception as e:
        logger.warning("morningstar_profitability_error", sec_id=sec_id, error=str(e))
        return None


async def _fetch_financial_health(
    client: httpx.AsyncClient, sec_id: str
) -> dict[str, Any] | None:
    """Fetch leverage and liquidity ratios."""
    try:
        resp = await client.get(
            f"{MS_SAL_BASE}/keyMetrics/financialHealth/{sec_id}",
            params=MS_SAL_PARAMS,
            headers={"apikey": MS_API_KEY},
        )
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception as e:
        logger.warning("morningstar_health_error", sec_id=sec_id, error=str(e))
        return None


# ---------------------------------------------------------------------------
# Data extraction helpers
# ---------------------------------------------------------------------------


def _get_latest(data_list: list[dict], field: str) -> float | None:
    """Get the most recent non-null value for a field from Morningstar dataList."""
    if not data_list:
        return None
    # dataList is chronological; iterate from newest to oldest
    for item in reversed(data_list):
        # Skip "Latest Qtr" label entries — they duplicate the last annual
        if item.get("fiscalPeriodYear") == "Latest Qtr" or item.get("fiscalPeriodYearMonth") == "Latest Qtr":
            continue
        val = item.get(field)
        if val is not None:
            return float(val)
    return None


def _get_latest_health(data_list: list[dict], field: str) -> float | None:
    """Get most recent value from financial health dataList."""
    if not data_list:
        return None
    for item in reversed(data_list):
        if item.get("fiscalPeriodYearMonth") == "Latest Qtr":
            continue
        val = item.get(field)
        if val is not None:
            return float(val)
    return None


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


@register_pipeline
class MorningstarFundamentals(PipelineAdapter):
    """Fetches quality metrics from Morningstar's SAL API for all active stocks.

    Overrides Yahoo-sourced ROIC and leverage with Morningstar's standardised
    (IFRS 16-adjusted) calculations.
    """

    @property
    def source_name(self) -> str:
        return "morningstar"

    @property
    def pipeline_name(self) -> str:
        return "morningstar_fundamentals"

    async def fetch(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Resolve SecIds and fetch profitability + financial health data."""
        async with async_session() as session:
            result = await session.execute(
                select(Security).where(
                    Security.is_active.is_(True),
                    Security.asset_class == "stock",
                )
            )
            securities = result.scalars().all()

        if not securities:
            logger.info("morningstar_fundamentals_skip", reason="no active stocks")
            return []

        logger.info("morningstar_fundamentals_fetch_start", securities=len(securities))

        raw_records: list[dict[str, Any]] = []
        resolved = 0
        cached = 0

        async with httpx.AsyncClient(
            timeout=30,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            for sec in securities:
                sec_id = sec.morningstar_id

                # Resolve SecId if not cached
                if not sec_id:
                    sec_id = await _resolve_sec_id(client, sec)
                    if sec_id:
                        # Cache it in the DB
                        async with async_session() as s:
                            await s.execute(
                                text("UPDATE securities SET morningstar_id = :ms_id WHERE id = :sid"),
                                {"ms_id": sec_id, "sid": sec.id},
                            )
                            await s.commit()
                        resolved += 1
                        logger.info(
                            "morningstar_resolved",
                            ticker=sec.ticker,
                            sec_id=sec_id,
                        )
                    else:
                        logger.debug(
                            "morningstar_resolve_failed",
                            ticker=sec.ticker,
                        )
                        await asyncio.sleep(1)
                        continue
                    await asyncio.sleep(1.5)  # Rate limit after resolution
                else:
                    cached += 1

                # Fetch profitability and financial health in parallel
                prof_task = _fetch_profitability(client, sec_id)
                health_task = _fetch_financial_health(client, sec_id)
                prof_data, health_data = await asyncio.gather(prof_task, health_task)

                if prof_data or health_data:
                    raw_records.append({
                        "security_id": sec.id,
                        "ticker": sec.ticker,
                        "sec_id": sec_id,
                        "profitability": prof_data,
                        "financial_health": health_data,
                    })

                # Rate limit: 1s between tickers
                await asyncio.sleep(1)

        logger.info(
            "morningstar_fundamentals_fetch_complete",
            records=len(raw_records),
            resolved=resolved,
            cached=cached,
        )
        return raw_records

    async def validate(
        self, raw_records: list[dict]
    ) -> tuple[list[dict], list[str]]:
        """Validate that we got at least ROIC or leverage data."""
        valid = []
        errors = []

        for rec in raw_records:
            ticker = rec["ticker"]
            prof = rec.get("profitability") or {}
            health = rec.get("financial_health") or {}

            prof_list = prof.get("dataList", [])
            health_list = health.get("dataList", [])

            roic = _get_latest(prof_list, "roic")
            roe = _get_latest(prof_list, "roe")
            roa = _get_latest(prof_list, "roa")
            de_ratio = _get_latest_health(health_list, "debtEquityRatio")
            interest_coverage = _get_latest_health(health_list, "interestCoverage")
            financial_leverage = _get_latest_health(health_list, "financialLeverage")

            if roic is None and roe is None and de_ratio is None:
                errors.append(f"{ticker}: no usable data from Morningstar")
                continue

            rec["parsed"] = {
                "roic": roic / 100 if roic is not None else None,  # MS returns percentage
                "roe": roe / 100 if roe is not None else None,
                "roa": roa / 100 if roa is not None else None,
                "debt_equity_ratio": de_ratio,
                "interest_coverage": interest_coverage,
                "financial_leverage": financial_leverage,
            }
            valid.append(rec)

            logger.info(
                "morningstar_fundamentals_validated",
                ticker=ticker,
                roic=f"{roic:.1f}%" if roic is not None else None,
                roe=f"{roe:.1f}%" if roe is not None else None,
                de_ratio=de_ratio,
            )

        return valid, errors

    async def transform(self, valid_records: list[dict]) -> list[dict]:
        """Transform to DB update format."""
        return [
            {
                "security_id": rec["security_id"],
                "ticker": rec["ticker"],
                **rec["parsed"],
            }
            for rec in valid_records
        ]

    async def load(self, transformed_records: list[dict]) -> int:
        """Override ROIC (and ROE if available) in security_fundamentals."""
        if not transformed_records:
            return 0

        update_sql = text("""
            UPDATE security_fundamentals
            SET roic = COALESCE(:roic, roic),
                roe = COALESCE(:roe, roe),
                updated_at = now()
            WHERE security_id = :security_id
        """)

        rows_affected = 0
        async with async_session() as session:
            for rec in transformed_records:
                roic = rec.get("roic")
                roe = rec.get("roe")

                if roic is None and roe is None:
                    continue

                result = await session.execute(
                    update_sql,
                    {
                        "security_id": rec["security_id"],
                        "roic": roic,
                        "roe": roe,
                    },
                )
                if result.rowcount > 0:
                    rows_affected += 1
                    logger.debug(
                        "morningstar_fundamentals_updated",
                        ticker=rec["ticker"],
                        roic=f"{roic*100:.1f}%" if roic else None,
                    )

            await session.commit()

        logger.info("morningstar_fundamentals_loaded", rows=rows_affected)
        return rows_affected
