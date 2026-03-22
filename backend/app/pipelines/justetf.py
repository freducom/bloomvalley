"""justETF data pipeline — ETF profile data from justETF.com."""

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

JUSTETF_BASE = "https://www.justetf.com/en/etf-profile.html"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"


def _extract_by_testid(html: str, testid: str, closing_tag: str = "") -> str | None:
    """Extract text content from an element identified by data-testid attribute.

    justETF uses data-testid attributes on value elements, e.g.:
        data-testid="tl_etf-basics_value_ter">0.20% p.a.</div>
    This is more robust than label-based matching which broke when the
    page layout changed (discovered 2026-03-22).

    Args:
        html: The full page HTML.
        testid: The data-testid attribute value to locate the element.
        closing_tag: If set, capture up to this specific closing tag (e.g. "div")
                     to include child elements. Otherwise stops at the first
                     closing tag encountered.
    """
    if closing_tag:
        end_pattern = rf"</{re.escape(closing_tag)}\b"
    else:
        end_pattern = r"</"
    pattern = re.compile(
        rf'data-testid="{re.escape(testid)}"[^>]*>'
        rf"([\s\S]*?){end_pattern}",
        re.IGNORECASE,
    )
    match = pattern.search(html)
    if match:
        # Strip nested HTML tags from the captured content
        raw = re.sub(r"<[^>]+>", " ", match.group(1))
        cleaned = re.sub(r"\s+", " ", raw).strip()
        if cleaned:
            return cleaned
    return None


def _parse_ter(html: str) -> str | None:
    """Extract TER percentage, e.g. '0.20%'.

    Primary: data-testid="tl_etf-basics_value_ter" (table row)
    Fallback: data-testid="etf-profile-header_ter-value" (header)
    """
    for testid in ["tl_etf-basics_value_ter", "etf-profile-header_ter-value"]:
        raw = _extract_by_testid(html, testid)
        if raw:
            m = re.search(r"(\d+[.,]\d+\s*%)", raw)
            if m:
                return m.group(1).replace(",", ".")
    return None


def _parse_fund_size(html: str) -> str | None:
    """Extract fund size / AUM, e.g. 'EUR 109,651 m'.

    Primary: data-testid="etf-profile-header_fund-size-value-wrapper" (header)
    The wrapper contains: <span> EUR 109,651 </span> m
    Fallback: search the etf-basics table row for fund size.
    """
    # Try the header wrapper first — it contains currency, amount and unit.
    # Use closing_tag="div" because the wrapper is a <div> containing nested
    # <span> children: <span>EUR 109,651</span> m <span class="indicator...">
    raw = _extract_by_testid(html, "etf-profile-header_fund-size-value-wrapper", closing_tag="div")
    if raw:
        m = re.search(r"([A-Z]{3}\s+[\d.,]+)\s*(m|bn)", raw, re.IGNORECASE)
        if m:
            return f"{m.group(1).strip()} {m.group(2)}"
    # Fallback: basics table row
    raw = _extract_by_testid(html, "tl_etf-basics_value_fund-size")
    if raw:
        m = re.search(r"([A-Z]{3}\s+[\d.,]+\s*(?:m|bn))", raw, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def _parse_replication(html: str) -> str | None:
    """Extract replication method: Physical, Synthetic, Swap, etc.

    Primary: data-testid="tl_etf-basics_value_replication" (table)
    Fallback: data-testid="etf-profile-header_replication-value" (header)
    """
    for testid in ["tl_etf-basics_value_replication",
                    "etf-profile-header_replication-value"]:
        raw = _extract_by_testid(html, testid)
        if raw:
            for method in ["Physical", "Synthetic", "Swap", "Full replication",
                           "Optimized sampling", "Unfunded swap", "Funded swap"]:
                if method.lower() in raw.lower():
                    return method
    return None


def _parse_distribution(html: str) -> str | None:
    """Extract distribution policy: Accumulating or Distributing.

    Primary: data-testid="tl_etf-basics_value_distribution-policy" (table)
    Fallback: data-testid="etf-profile-header_distribution-policy-value" (header)
    """
    for testid in ["tl_etf-basics_value_distribution-policy",
                    "etf-profile-header_distribution-policy-value"]:
        raw = _extract_by_testid(html, testid)
        if raw:
            if "accumulating" in raw.lower():
                return "Accumulating"
            if "distributing" in raw.lower():
                return "Distributing"
    return None


def _parse_domicile(html: str) -> str | None:
    """Extract fund domicile country.

    Primary: data-testid="tl_etf-basics_value_domicile-country" (table)
    """
    raw = _extract_by_testid(html, "tl_etf-basics_value_domicile-country")
    if raw and len(raw) < 50:
        return raw
    return None


@register_pipeline
class JustETFProfiles(PipelineAdapter):
    """Scrapes ETF profile data from justETF.com."""

    @property
    def source_name(self) -> str:
        return "justetf"

    @property
    def pipeline_name(self) -> str:
        return "justetf_profiles"

    async def fetch(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        # Get ETF securities with an ISIN
        async with async_session() as session:
            result = await session.execute(
                select(Security).where(
                    Security.asset_class == "etf",
                    Security.is_active.is_(True),
                    Security.isin.isnot(None),
                )
            )
            etfs = result.scalars().all()

        if not etfs:
            logger.info("justetf_no_etfs_found")
            return []

        logger.info("justetf_fetch_start", etfs=len(etfs))

        raw_records: list[dict[str, Any]] = []

        async with httpx.AsyncClient(
            timeout=30,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            for etf in etfs:
                try:
                    url = f"{JUSTETF_BASE}?isin={etf.isin}"
                    resp = await client.get(url)

                    if resp.status_code == 429:
                        raise RetryableError("justETF rate limited (429)")
                    if resp.status_code == 404:
                        logger.warning("justetf_etf_not_found", isin=etf.isin, ticker=etf.ticker)
                        continue
                    resp.raise_for_status()

                    html = resp.text

                    raw_records.append({
                        "security_id": etf.id,
                        "ticker": etf.ticker,
                        "isin": etf.isin,
                        "html": html,
                    })

                    logger.info("justetf_fetched", ticker=etf.ticker, isin=etf.isin)

                except RetryableError:
                    raise
                except httpx.TimeoutException as e:
                    raise RetryableError(f"justETF timeout: {e}") from e
                except Exception as e:
                    logger.warning("justetf_fetch_error", isin=etf.isin, ticker=etf.ticker, error=str(e))
                    continue

                # Be polite: 5 seconds between requests
                await asyncio.sleep(5)

        logger.info("justetf_fetch_complete", records=len(raw_records))
        return raw_records

    async def validate(
        self, raw_records: list[dict]
    ) -> tuple[list[dict], list[str]]:
        valid = []
        errors = []

        for rec in raw_records:
            ticker = rec.get("ticker", "?")
            html = rec.get("html", "")

            if not html or len(html) < 1000:
                errors.append(f"{ticker}: page too short or empty ({len(html)} bytes)")
                continue

            # Parse all fields from HTML
            ter = _parse_ter(html)
            fund_size = _parse_fund_size(html)
            replication = _parse_replication(html)
            distribution = _parse_distribution(html)
            domicile = _parse_domicile(html)

            parsed_count = sum(1 for v in [ter, fund_size, replication, distribution, domicile] if v)

            if parsed_count == 0:
                errors.append(f"{ticker}: no fields could be parsed from page")
                continue

            rec["parsed"] = {
                "ter": ter,
                "fund_size": fund_size,
                "replication": replication,
                "distribution_policy": distribution,
                "fund_domicile": domicile,
            }

            # Drop HTML to save memory
            del rec["html"]

            valid.append(rec)

            logger.info(
                "justetf_parsed",
                ticker=ticker,
                fields_found=parsed_count,
                ter=ter,
                replication=replication,
                distribution=distribution,
            )

        return valid, errors

    async def transform(self, valid_records: list[dict]) -> list[dict]:
        transformed = []

        for rec in valid_records:
            transformed.append({
                "security_id": rec["security_id"],
                "ticker": rec["ticker"],
                "isin": rec["isin"],
                "profile_data": rec["parsed"],
            })

        return transformed

    async def load(self, transformed_records: list[dict]) -> int:
        if not transformed_records:
            return 0

        rows_affected = 0

        async with async_session() as session:
            for rec in transformed_records:
                security_id = rec["security_id"]
                ticker = rec["ticker"]
                profile_json = json.dumps(rec["profile_data"], ensure_ascii=False)
                title = f"justETF Profile: {ticker}"

                # Check for existing note with same security_id and title pattern
                result = await session.execute(
                    select(ResearchNote).where(
                        ResearchNote.security_id == security_id,
                        ResearchNote.title == title,
                    )
                )
                existing = result.scalars().first()

                if existing:
                    existing.thesis = profile_json
                    existing.tags = ["etf_profile", "justetf"]
                    logger.info("justetf_note_updated", ticker=ticker)
                else:
                    note = ResearchNote(
                        security_id=security_id,
                        title=title,
                        thesis=profile_json,
                        tags=["etf_profile", "justetf"],
                    )
                    session.add(note)
                    logger.info("justetf_note_created", ticker=ticker)

                rows_affected += 1

            await session.commit()

        logger.info("justetf_profiles_loaded", rows=rows_affected)
        return rows_affected
