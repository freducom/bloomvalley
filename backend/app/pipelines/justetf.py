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


def _extract(html: str, label: str) -> str | None:
    """Extract a value following a label in justETF HTML."""
    # justETF uses patterns like:
    #   <span>Total expense ratio</span> ... <span>0.20% p.a.</span>
    #   or similar table/div structures with the label followed by the value
    pattern = re.compile(
        rf"{re.escape(label)}"
        r"[\s\S]{0,500}?"           # allow up to 500 chars between label and value
        r"(?:<[^>]*>[\s]*)*"        # skip any intervening HTML tags
        r"([^<]+)",                 # capture first text node after tags
        re.IGNORECASE,
    )
    match = pattern.search(html)
    if match:
        return match.group(1).strip()
    return None


def _parse_ter(html: str) -> str | None:
    """Extract TER percentage, e.g. '0.20% p.a.'."""
    raw = _extract(html, "Total expense ratio")
    if raw:
        m = re.search(r"(\d+[.,]\d+\s*%)", raw)
        if m:
            return m.group(1).replace(",", ".")
    return None


def _parse_fund_size(html: str) -> str | None:
    """Extract fund size / AUM, e.g. 'EUR 1,234 m' or 'EUR 56 bn'."""
    raw = _extract(html, "Fund size")
    if raw:
        # Match currency + amount patterns like "EUR 1,234 m" or "1.234 m"
        m = re.search(r"([A-Z]{3}\s+[\d.,]+\s*(?:m|bn|mil|billion)?)", raw, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        # Fallback: just grab a number with possible unit
        m = re.search(r"([\d.,]+\s*(?:m|bn|mil|billion)?)", raw, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def _parse_replication(html: str) -> str | None:
    """Extract replication method: Physical, Synthetic, Swap, etc."""
    raw = _extract(html, "Replication")
    if raw:
        for method in ["Physical", "Synthetic", "Swap", "Full replication",
                       "Optimized sampling", "Unfunded swap", "Funded swap"]:
            if method.lower() in raw.lower():
                return method
    return None


def _parse_distribution(html: str) -> str | None:
    """Extract distribution policy: Accumulating or Distributing."""
    raw = _extract(html, "Distribution policy")
    if raw:
        if "accumulating" in raw.lower():
            return "Accumulating"
        if "distributing" in raw.lower():
            return "Distributing"
    return None


def _parse_domicile(html: str) -> str | None:
    """Extract fund domicile country."""
    raw = _extract(html, "Fund domicile")
    if raw:
        # Clean up: take the first meaningful word(s), skip HTML artifacts
        cleaned = re.sub(r"\s+", " ", raw).strip()
        if cleaned and len(cleaned) < 50:
            return cleaned
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
