"""Morningstar pipeline — fetches fund/ETF ratings and analysis data."""

import asyncio
import json
import re
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

# Morningstar API endpoints (public, no auth needed for basic data)
MS_SEARCH_URL = "https://www.morningstar.com/api/v2/search/securities"
MS_QUOTE_URL = "https://api-global.morningstar.com/sal-service/V1/stock/realTime/v3/{secId}"
MS_PERFORMANCE_URL = "https://api-global.morningstar.com/sal-service/V1/stock/performance/v3/{secId}"

# Alternative: use the public morningstar.fi / morningstar.se pages
MS_FUND_URL = "https://www.morningstar.fi/fi/funds/snapshot/snapshot.aspx?id={ms_id}"
MS_ETF_URL = "https://www.morningstar.fi/fi/etf/snapshot/snapshot.aspx?id={ms_id}"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _extract_star_rating(html: str) -> int | None:
    """Extract Morningstar star rating (1-5) from HTML."""
    # Look for star rating patterns
    patterns = [
        r'data-rating="(\d)"',
        r'ratingValue["\s:]+(\d)',
        r'starRating["\s:]+(\d)',
        r'class="[^"]*stars(\d)',
        r'rating_sprite\s+stars(\d)',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            rating = int(m.group(1))
            if 1 <= rating <= 5:
                return rating
    return None


def _extract_category(html: str) -> str | None:
    """Extract Morningstar category from HTML."""
    patterns = [
        r'(?:Morningstar\s+)?Category[^:]*:\s*</[^>]+>\s*<[^>]+>([^<]+)',
        r'"categoryName"\s*:\s*"([^"]+)"',
        r'Category["\s:]+([^"<]+)',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if val and len(val) < 100:
                return val
    return None


def _extract_analyst_rating(html: str) -> str | None:
    """Extract Morningstar analyst/medalist rating (Gold/Silver/Bronze/Neutral/Negative)."""
    patterns = [
        r'(?:Analyst|Medalist)\s+Rating[^:]*:\s*</[^>]+>\s*<[^>]+>([^<]+)',
        r'"analystRating"\s*:\s*"([^"]+)"',
        r'(?:Gold|Silver|Bronze|Neutral|Negative)(?=\s*</)',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            val = m.group(1) if m.lastindex else m.group(0)
            val = val.strip()
            for medal in ["Gold", "Silver", "Bronze", "Neutral", "Negative"]:
                if medal.lower() in val.lower():
                    return medal
    return None


def _extract_risk_rating(html: str) -> str | None:
    """Extract Morningstar risk rating."""
    patterns = [
        r'Risk\s+Rating[^:]*:\s*</[^>]+>\s*<[^>]+>([^<]+)',
        r'"riskRating"\s*:\s*"([^"]+)"',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if val and len(val) < 50:
                return val
    return None


def _extract_return_rating(html: str) -> str | None:
    """Extract Morningstar return rating."""
    patterns = [
        r'Return\s+Rating[^:]*:\s*</[^>]+>\s*<[^>]+>([^<]+)',
        r'"returnRating"\s*:\s*"([^"]+)"',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if val and len(val) < 50:
                return val
    return None


@register_pipeline
class MorningstarRatings(PipelineAdapter):
    """Fetches Morningstar ratings for funds and ETFs."""

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
                    # Try searching Morningstar.fi for the ISIN
                    search_url = (
                        f"https://www.morningstar.fi/fi/util/SecuritySearch.ashx"
                        f"?q={fund.isin}&limit=1"
                    )
                    resp = await client.get(search_url)

                    if resp.status_code == 429:
                        raise RetryableError("Morningstar rate limited (429)")

                    ms_id = None
                    if resp.status_code == 200:
                        # Response is typically JSON with search results
                        try:
                            results = resp.json()
                            if isinstance(results, list) and results:
                                ms_id = results[0].get("i") or results[0].get("id")
                        except Exception:
                            # May be plain text format: "id|name|type|..."
                            lines = resp.text.strip().split("\n")
                            if lines and "|" in lines[0]:
                                ms_id = lines[0].split("|")[0].strip()

                    if not ms_id:
                        logger.debug(
                            "morningstar_no_match",
                            ticker=fund.ticker,
                            isin=fund.isin,
                        )
                        await asyncio.sleep(3)
                        continue

                    # Fetch the fund/ETF page
                    page_url = MS_FUND_URL.format(ms_id=ms_id)
                    if fund.asset_class == "etf":
                        page_url = MS_ETF_URL.format(ms_id=ms_id)

                    page_resp = await client.get(page_url)

                    if page_resp.status_code == 429:
                        raise RetryableError("Morningstar rate limited (429)")
                    if page_resp.status_code == 404:
                        logger.warning(
                            "morningstar_page_not_found",
                            ticker=fund.ticker,
                            ms_id=ms_id,
                        )
                        await asyncio.sleep(3)
                        continue

                    page_resp.raise_for_status()

                    raw_records.append({
                        "security_id": fund.id,
                        "ticker": fund.ticker,
                        "isin": fund.isin,
                        "ms_id": ms_id,
                        "html": page_resp.text,
                    })

                    logger.info(
                        "morningstar_fetched",
                        ticker=fund.ticker,
                        ms_id=ms_id,
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

                # Be polite: 5 seconds between requests
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
            html = rec.get("html", "")

            if not html or len(html) < 500:
                errors.append(f"{ticker}: page too short ({len(html)} bytes)")
                continue

            # Parse ratings from HTML
            star_rating = _extract_star_rating(html)
            category = _extract_category(html)
            analyst_rating = _extract_analyst_rating(html)
            risk_rating = _extract_risk_rating(html)
            return_rating = _extract_return_rating(html)

            parsed_count = sum(
                1 for v in [star_rating, category, analyst_rating, risk_rating, return_rating] if v
            )

            if parsed_count == 0:
                errors.append(f"{ticker}: no fields could be parsed")
                continue

            rec["parsed"] = {
                "star_rating": star_rating,
                "category": category,
                "analyst_rating": analyst_rating,
                "risk_rating": risk_rating,
                "return_rating": return_rating,
                "ms_id": rec["ms_id"],
            }

            # Drop HTML to save memory
            del rec["html"]

            valid.append(rec)

            logger.info(
                "morningstar_parsed",
                ticker=ticker,
                fields_found=parsed_count,
                stars=star_rating,
                analyst=analyst_rating,
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
