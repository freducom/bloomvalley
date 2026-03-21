"""SEC EDGAR pipeline — fetches Form 4 insider filings for US-listed securities."""

import asyncio
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
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

EDGAR_SEARCH_BASE = "https://efts.sec.gov/LATEST/search-index"
SEC_USER_AGENT = "Bloomvalley/1.0 (personal use)"

US_EXCHANGES = ("XNAS", "XNYS", "NYSE", "NASDAQ")


@register_pipeline
class SecEdgarFilings(PipelineAdapter):
    """Fetches SEC EDGAR Form 4 and 13F-HR filings for US-listed securities."""

    @property
    def source_name(self) -> str:
        return "sec_edgar"

    @property
    def pipeline_name(self) -> str:
        return "sec_edgar_filings"

    async def fetch(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        # Default date range: last 30 days
        if to_date is None:
            to_date = date.today()
        if from_date is None:
            from_date = to_date - timedelta(days=30)

        # Get US-listed active securities
        async with async_session() as session:
            result = await session.execute(
                select(Security).where(
                    Security.exchange.in_(US_EXCHANGES),
                    Security.is_active.is_(True),
                )
            )
            securities = result.scalars().all()

        if not securities:
            logger.info("sec_edgar_no_us_securities")
            return []

        logger.info("sec_edgar_fetch_start", securities=len(securities))

        raw_records: list[dict[str, Any]] = []

        async with httpx.AsyncClient(
            timeout=30,
            headers={"User-Agent": SEC_USER_AGENT},
        ) as client:
            for sec in securities:
                try:
                    # Search for Form 4 filings mentioning this ticker
                    params = {
                        "q": f'"{sec.ticker}"',
                        "forms": "4,13F-HR",
                        "dateRange": "custom",
                        "startdt": from_date.isoformat(),
                        "enddt": to_date.isoformat(),
                    }

                    resp = await client.get(EDGAR_SEARCH_BASE, params=params)

                    if resp.status_code == 429:
                        raise RetryableError("SEC EDGAR rate limited (429)")
                    if resp.status_code == 404:
                        logger.warning(
                            "sec_edgar_not_found", ticker=sec.ticker
                        )
                        await asyncio.sleep(0.5)
                        continue
                    resp.raise_for_status()

                    data = resp.json()
                    hits = data.get("hits", data.get("results", []))

                    # Handle both possible response structures
                    if isinstance(hits, dict):
                        hits = hits.get("hits", [])

                    for hit in hits:
                        # Extract filing metadata from the hit
                        source = hit.get("_source", hit)

                        form_type = (
                            source.get("form_type")
                            or source.get("forms")
                            or source.get("type")
                            or "Unknown"
                        )
                        filer_name = (
                            source.get("display_names", ["Unknown"])[0]
                            if isinstance(source.get("display_names"), list)
                            else source.get("entity_name")
                            or source.get("company_name")
                            or source.get("display_name")
                            or "Unknown"
                        )
                        filing_date = (
                            source.get("file_date")
                            or source.get("period_of_report")
                            or source.get("date_filed")
                            or to_date.isoformat()
                        )
                        accession_number = (
                            source.get("accession_no")
                            or source.get("accession_number")
                            or ""
                        )
                        # Build filing URL from accession number
                        if accession_number:
                            acc_clean = accession_number.replace("-", "")
                            filing_url = (
                                f"https://www.sec.gov/Archives/edgar/data/"
                                f"{source.get('entity_id', '')}/{acc_clean}/"
                                f"{accession_number}-index.htm"
                            )
                        else:
                            filing_url = source.get("file_url", "")

                        raw_records.append({
                            "security_id": sec.id,
                            "ticker": sec.ticker,
                            "form_type": str(form_type),
                            "filer_name": str(filer_name),
                            "filing_date": str(filing_date),
                            "accession_number": accession_number,
                            "filing_url": filing_url,
                            "raw_source": source,
                        })

                    logger.debug(
                        "sec_edgar_ticker_done",
                        ticker=sec.ticker,
                        filings=len(hits),
                    )

                except RetryableError:
                    raise
                except httpx.TimeoutException as e:
                    raise RetryableError(f"SEC EDGAR timeout: {e}") from e
                except Exception as e:
                    logger.warning(
                        "sec_edgar_fetch_error",
                        ticker=sec.ticker,
                        error=str(e),
                    )
                    continue

                # SEC rate limit: max 10 req/s, use 0.5s between requests
                await asyncio.sleep(0.5)

        logger.info("sec_edgar_fetch_complete", records=len(raw_records))
        return raw_records

    async def validate(
        self, raw_records: list[dict]
    ) -> tuple[list[dict], list[str]]:
        valid = []
        errors = []
        seen_keys: set[str] = set()

        for rec in raw_records:
            ticker = rec.get("ticker", "?")

            # Must have a form type
            if not rec.get("form_type") or rec["form_type"] == "Unknown":
                errors.append(f"{ticker}: missing form_type")
                continue

            # Must have a filer name
            if not rec.get("filer_name") or rec["filer_name"] == "Unknown":
                errors.append(f"{ticker}: missing filer_name")
                continue

            # Deduplicate by filing URL or accession number
            dedup_key = rec.get("filing_url") or rec.get("accession_number") or ""
            if not dedup_key:
                # Fall back to content-based dedup
                dedup_key = f"{rec['security_id']}:{rec['form_type']}:{rec['filer_name']}:{rec['filing_date']}"

            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            valid.append(rec)

        return valid, errors

    async def transform(self, valid_records: list[dict]) -> list[dict]:
        transformed = []

        for rec in valid_records:
            # Build a title for the research note
            title = f"SEC Filing: {rec['form_type']} - {rec['filer_name']}"
            if len(title) > 255:
                title = title[:252] + "..."

            # Build content JSON for the thesis field
            content = {
                "form_type": rec["form_type"],
                "filer_name": rec["filer_name"],
                "filing_date": rec["filing_date"],
                "accession_number": rec["accession_number"],
                "filing_url": rec["filing_url"],
                "ticker": rec["ticker"],
            }

            # Fingerprint for dedup in DB (based on filing URL or unique content)
            fp_source = rec.get("filing_url") or json.dumps(content, sort_keys=True)
            fingerprint = hashlib.sha256(fp_source.encode()).hexdigest()

            transformed.append({
                "security_id": rec["security_id"],
                "title": title,
                "thesis": json.dumps(content),
                "tags": ["sec_filing", "sec_edgar", rec["form_type"].lower()],
                "fingerprint": fingerprint,
            })

        return transformed

    async def load(self, transformed_records: list[dict]) -> int:
        if not transformed_records:
            return 0

        # Get existing fingerprints to avoid duplicates
        # We use tags to store the fingerprint for dedup
        fps = [r["fingerprint"] for r in transformed_records]

        # Check existing research notes by matching title + security_id
        # (since ResearchNote doesn't have a fingerprint column)
        existing_titles: set[tuple[int | None, str]] = set()
        async with async_session() as session:
            for rec in transformed_records:
                result = await session.execute(
                    select(ResearchNote.id).where(
                        ResearchNote.security_id == rec["security_id"],
                        ResearchNote.title == rec["title"],
                    )
                )
                if result.scalar_one_or_none() is not None:
                    existing_titles.add((rec["security_id"], rec["title"]))

        rows = 0
        async with async_session() as session:
            for rec in transformed_records:
                key = (rec["security_id"], rec["title"])
                if key in existing_titles:
                    continue

                note = ResearchNote(
                    security_id=rec["security_id"],
                    title=rec["title"],
                    thesis=rec["thesis"],
                    tags=rec["tags"],
                    is_active=True,
                )
                session.add(note)
                rows += 1

            await session.commit()

        logger.info("sec_edgar_filings_loaded", rows=rows)
        return rows
