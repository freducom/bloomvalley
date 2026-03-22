"""Morningstar pipeline — fetches fund/ETF ratings and analysis data.

Uses two Morningstar public APIs:
1. SecuritySearch.ashx (morningstar.fi) — resolves ISIN to Morningstar ID, returns
   star rating and analyst rating from the search response.
2. Screener API (tools.morningstar.co.uk) — returns category, ongoing charge (expense
   ratio), and confirms star rating with richer data.

The old approach of scraping snapshot HTML pages no longer works because
morningstar.fi redirects to global.morningstar.com which blocks automated requests
(403 / 202 with empty body).
"""

import asyncio
import json
from datetime import date
from typing import Any

import httpx
import structlog
from sqlalchemy import select

from app.db.engine import async_session
from app.db.models.research_notes import ResearchNote
from app.db.models.securities import Security
from app.pipelines import register_pipeline
from app.pipelines.base import PipelineAdapter, RetryableError

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

# Search API — resolves ISIN/name to Morningstar ID + basic ratings
MS_SEARCH_URL = "https://www.morningstar.fi/fi/util/SecuritySearch.ashx"

# Screener API — returns structured data (category, ongoing charge, star rating)
# The path component 'klr5zyak8x' is a long-lived public site key used by
# Morningstar's own frontend widgets.
MS_SCREENER_URL = (
    "https://tools.morningstar.co.uk/api/rest.svc/klr5zyak8x/security/screener"
)

# Universe IDs covering major European exchanges + fund universes
MS_UNIVERSE_IDS = "|".join([
    "ETEXG$XAMS",   # Euronext Amsterdam
    "ETEXG$XETR",   # XETRA
    "ETEXG$XHEL",   # Helsinki
    "ETEXG$XLON",   # London
    "ETEXG$XMIL",   # Milan
    "ETEXG$XPAR",   # Paris
    "ETEXG$XNYS",   # NYSE
    "ETEXG$XNAS",   # NASDAQ
    "FOEUR$$ALL",    # All European funds
    "FOESP$$ALL",    # All Spanish-domiciled funds (catches many UCITS)
])

# Fields requested from the screener API
MS_SCREENER_FIELDS = "|".join([
    "SecId",
    "Name",
    "StarRatingM255",
    "AnalystRatingScale",
    "CategoryName",
    "OngoingCharge",
    "ReturnM255",
    "RiskM255",
])

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Analyst rating scale: the search API returns short codes; the screener may
# return numeric scale values.  Map both to human-readable medal names.
_ANALYST_RATING_MAP = {
    "gold": "Gold",
    "silver": "Silver",
    "bronze": "Bronze",
    "neutral": "Neutral",
    "negative": "Negative",
    # Numeric scale (AnalystRatingScale from screener)
    "5": "Gold",
    "4": "Silver",
    "3": "Bronze",
    "2": "Neutral",
    "1": "Negative",
}


def _parse_search_line(line: str) -> dict[str, Any] | None:
    """Parse one line of the SecuritySearch.ashx pipe-delimited response.

    Format: ``DisplayName|{JSON}|TypeLabel|Ticker|Exchange|TypeLabel2``

    The embedded JSON object contains:
        i   — Morningstar SecId
        sr  — star rating (str, "1"-"5" or "")
        ar  — analyst rating (str, "" if unavailable)
        n   — name
        s   — ticker symbol
        e   — exchange MIC
        t   — type code (22 = ETF, 2 = Fund, 3 = Stock)
    """
    if "|" not in line:
        return None
    parts = line.split("|", 2)
    if len(parts) < 2:
        return None

    json_str = parts[1]
    if not json_str.startswith("{"):
        return None

    try:
        data = json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        return None

    ms_id = data.get("i")
    if not ms_id:
        return None

    star_raw = data.get("sr", "")
    analyst_raw = data.get("ar", "")

    star_rating: int | None = None
    if star_raw and star_raw.isdigit():
        v = int(star_raw)
        if 1 <= v <= 5:
            star_rating = v

    analyst_rating = _ANALYST_RATING_MAP.get(analyst_raw.lower()) if analyst_raw else None

    return {
        "ms_id": ms_id,
        "name": data.get("n", ""),
        "ticker_ms": data.get("s", ""),
        "exchange": data.get("e", ""),
        "type_code": data.get("t"),
        "star_rating": star_rating,
        "analyst_rating": analyst_rating,
    }


async def _search_by_isin(
    client: httpx.AsyncClient, isin: str
) -> dict[str, Any] | None:
    """Resolve an ISIN to a Morningstar ID via the search API."""
    resp = await client.get(
        MS_SEARCH_URL,
        params={"q": isin, "limit": "5", "source": "nav"},
    )

    if resp.status_code == 429:
        raise RetryableError("Morningstar search rate-limited (429)")
    if resp.status_code != 200:
        logger.warning("morningstar_search_http_error", status=resp.status_code, isin=isin)
        return None

    # Response is multi-line, pipe-delimited.  First line may be a header
    # like "Etf|||" with no JSON — skip those.
    for line in resp.text.strip().splitlines():
        parsed = _parse_search_line(line)
        if parsed:
            return parsed

    return None


async def _screener_lookup(
    client: httpx.AsyncClient, ms_id: str
) -> dict[str, Any] | None:
    """Fetch detailed data for a single SecId from the screener API."""
    resp = await client.get(
        MS_SCREENER_URL,
        params={
            "page": "1",
            "pageSize": "1",
            "sortOrder": "LegalName asc",
            "outputType": "json",
            "version": "1",
            "universeIds": MS_UNIVERSE_IDS,
            "securityDataPoints": MS_SCREENER_FIELDS,
            "term": ms_id,
        },
    )

    if resp.status_code == 429:
        raise RetryableError("Morningstar screener rate-limited (429)")
    if resp.status_code != 200:
        logger.warning(
            "morningstar_screener_http_error",
            status=resp.status_code,
            ms_id=ms_id,
        )
        return None

    try:
        # Response may have a UTF-8 BOM
        body = resp.content.decode("utf-8-sig")
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("morningstar_screener_parse_error", ms_id=ms_id, error=str(exc))
        return None

    rows = data.get("rows")
    if not rows:
        return None

    row = rows[0]
    result: dict[str, Any] = {}

    if "StarRatingM255" in row and row["StarRatingM255"] is not None:
        result["star_rating"] = int(row["StarRatingM255"])

    if "CategoryName" in row and row["CategoryName"]:
        result["category"] = row["CategoryName"]

    if "OngoingCharge" in row and row["OngoingCharge"] is not None:
        # API returns percentage as a float, e.g. 0.19 means 0.19%
        result["expense_ratio"] = round(float(row["OngoingCharge"]), 4)

    if "AnalystRatingScale" in row and row["AnalystRatingScale"] is not None:
        ar_val = str(row["AnalystRatingScale"])
        result["analyst_rating"] = _ANALYST_RATING_MAP.get(ar_val.lower(), ar_val)

    if "ReturnM255" in row and row["ReturnM255"] is not None:
        result["return_rating"] = row["ReturnM255"]

    if "RiskM255" in row and row["RiskM255"] is not None:
        result["risk_rating"] = row["RiskM255"]

    return result


@register_pipeline
class MorningstarRatings(PipelineAdapter):
    """Fetches Morningstar ratings for funds and ETFs.

    Strategy:
    1. Use SecuritySearch.ashx to resolve ISIN -> Morningstar SecId and get
       star rating + analyst rating from the search response itself.
    2. Use the screener API to get category, expense ratio, and confirm star
       rating.
    3. Merge both sources — screener data takes precedence where available.
    """

    @property
    def source_name(self) -> str:
        return "morningstar"

    @property
    def pipeline_name(self) -> str:
        return "morningstar_ratings"

    async def fetch(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        # Get fund/ETF securities with an ISIN
        async with async_session() as session:
            result = await session.execute(
                select(Security).where(
                    Security.asset_class.in_(["etf", "fund"]),
                    Security.is_active.is_(True),
                    Security.isin.isnot(None),
                )
            )
            funds = result.scalars().all()

        if not funds:
            logger.info("morningstar_no_funds_found")
            return []

        logger.info("morningstar_fetch_start", funds=len(funds))

        raw_records: list[dict[str, Any]] = []

        async with httpx.AsyncClient(
            timeout=30,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            for fund in funds:
                try:
                    # Step 1: Resolve ISIN via search API
                    search_result = await _search_by_isin(client, fund.isin)

                    if not search_result:
                        logger.debug(
                            "morningstar_no_match",
                            ticker=fund.ticker,
                            isin=fund.isin,
                        )
                        await asyncio.sleep(3)
                        continue

                    ms_id = search_result["ms_id"]

                    # Step 2: Fetch detailed data from screener API
                    await asyncio.sleep(2)  # polite pause between requests
                    screener_data = await _screener_lookup(client, ms_id)

                    # Merge: search result is base, screener overwrites where present
                    merged: dict[str, Any] = {
                        "star_rating": search_result.get("star_rating"),
                        "analyst_rating": search_result.get("analyst_rating"),
                        "category": None,
                        "expense_ratio": None,
                        "risk_rating": None,
                        "return_rating": None,
                    }

                    if screener_data:
                        # Screener star rating is more authoritative
                        if "star_rating" in screener_data:
                            merged["star_rating"] = screener_data["star_rating"]
                        if "analyst_rating" in screener_data:
                            merged["analyst_rating"] = screener_data["analyst_rating"]
                        if "category" in screener_data:
                            merged["category"] = screener_data["category"]
                        if "expense_ratio" in screener_data:
                            merged["expense_ratio"] = screener_data["expense_ratio"]
                        if "risk_rating" in screener_data:
                            merged["risk_rating"] = screener_data["risk_rating"]
                        if "return_rating" in screener_data:
                            merged["return_rating"] = screener_data["return_rating"]

                    raw_records.append({
                        "security_id": fund.id,
                        "ticker": fund.ticker,
                        "isin": fund.isin,
                        "ms_id": ms_id,
                        "ratings": merged,
                    })

                    logger.info(
                        "morningstar_fetched",
                        ticker=fund.ticker,
                        ms_id=ms_id,
                        stars=merged.get("star_rating"),
                        category=merged.get("category"),
                    )

                except RetryableError:
                    raise
                except httpx.TimeoutException as e:
                    raise RetryableError(f"Morningstar timeout: {e}") from e
                except Exception as e:
                    logger.warning(
                        "morningstar_fetch_error",
                        ticker=fund.ticker,
                        error=str(e),
                    )
                    continue

                # Be polite: 5 seconds between fund iterations
                await asyncio.sleep(5)

        logger.info("morningstar_fetch_complete", records=len(raw_records))
        return raw_records

    async def validate(
        self, raw_records: list[dict]
    ) -> tuple[list[dict], list[str]]:
        valid = []
        errors = []

        for rec in raw_records:
            ticker = rec.get("ticker", "?")
            ratings = rec.get("ratings", {})

            # Count how many useful fields we got
            field_values = [
                ratings.get("star_rating"),
                ratings.get("category"),
                ratings.get("analyst_rating"),
                ratings.get("expense_ratio"),
                ratings.get("risk_rating"),
                ratings.get("return_rating"),
            ]
            parsed_count = sum(1 for v in field_values if v is not None)

            if parsed_count == 0:
                errors.append(f"{ticker}: no fields could be parsed from APIs")
                continue

            # Validate star rating range
            stars = ratings.get("star_rating")
            if stars is not None and not (1 <= stars <= 5):
                errors.append(f"{ticker}: invalid star rating {stars}")
                continue

            rec["parsed"] = {
                "star_rating": ratings.get("star_rating"),
                "category": ratings.get("category"),
                "analyst_rating": ratings.get("analyst_rating"),
                "expense_ratio": ratings.get("expense_ratio"),
                "risk_rating": ratings.get("risk_rating"),
                "return_rating": ratings.get("return_rating"),
                "ms_id": rec["ms_id"],
            }

            valid.append(rec)

            logger.info(
                "morningstar_validated",
                ticker=ticker,
                fields_found=parsed_count,
                stars=stars,
                category=ratings.get("category"),
                expense_ratio=ratings.get("expense_ratio"),
                analyst=ratings.get("analyst_rating"),
            )

        return valid, errors

    async def transform(self, valid_records: list[dict]) -> list[dict]:
        return [
            {
                "security_id": rec["security_id"],
                "ticker": rec["ticker"],
                "isin": rec["isin"],
                "ratings_data": rec["parsed"],
            }
            for rec in valid_records
        ]

    async def load(self, transformed_records: list[dict]) -> int:
        if not transformed_records:
            return 0

        rows_affected = 0

        async with async_session() as session:
            for rec in transformed_records:
                security_id = rec["security_id"]
                ticker = rec["ticker"]
                ratings_json = json.dumps(rec["ratings_data"], ensure_ascii=False)
                title = f"Morningstar Rating: {ticker}"

                # Check for existing note
                result = await session.execute(
                    select(ResearchNote).where(
                        ResearchNote.security_id == security_id,
                        ResearchNote.title == title,
                    )
                )
                existing = result.scalars().first()

                if existing:
                    existing.thesis = ratings_json
                    existing.tags = ["morningstar", "fund_rating"]
                    # Update moat_rating with star rating if available
                    stars = rec["ratings_data"].get("star_rating")
                    if stars:
                        existing.moat_rating = f"{stars}-star"
                    logger.info("morningstar_note_updated", ticker=ticker)
                else:
                    stars = rec["ratings_data"].get("star_rating")
                    note = ResearchNote(
                        security_id=security_id,
                        title=title,
                        thesis=ratings_json,
                        tags=["morningstar", "fund_rating"],
                        moat_rating=f"{stars}-star" if stars else None,
                    )
                    session.add(note)
                    logger.info("morningstar_note_created", ticker=ticker)

                rows_affected += 1

            await session.commit()

        logger.info("morningstar_ratings_loaded", rows=rows_affected)
        return rows_affected
