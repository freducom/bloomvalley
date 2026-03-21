"""GDELT DOC API pipeline — fetches global macro events from the GDELT Project."""

import asyncio
import hashlib
import re
from datetime import date, datetime, timezone
from typing import Any

import httpx
import structlog
from sqlalchemy import select

from app.db.engine import async_session
from app.db.models.news import NewsItem
from app.pipelines import register_pipeline
from app.pipelines.base import PipelineAdapter

logger = structlog.get_logger()

# Macro-relevant queries for global event monitoring
GDELT_QUERIES = [
    "economic crisis",
    "central bank policy",
    "trade war",
    "sanctions",
    "commodity prices",
    "inflation",
    "recession risk",
    "financial regulation",
    "currency crisis",
    "sovereign debt",
]

GDELT_DOC_API = (
    "https://api.gdeltproject.org/api/v2/doc/doc"
    "?query={query}&mode=artlist&maxrecords=50&format=json"
)

# Rate limit: 1 request per 5 seconds
RATE_LIMIT_DELAY = 5.0


def _normalize_title(title: str) -> str:
    """Normalize title for fingerprinting: lowercase, strip prefixes, remove punctuation."""
    t = title.lower().strip()
    for prefix in ["breaking:", "update:", "exclusive:", "just in:"]:
        if t.startswith(prefix):
            t = t[len(prefix) :].strip()
    t = re.sub(r"[^\w\s]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _fingerprint(title: str) -> str:
    """SHA-256 fingerprint of normalized title."""
    return hashlib.sha256(_normalize_title(title).encode()).hexdigest()


def _parse_seendate(seendate: str) -> datetime:
    """Parse GDELT seendate format YYYYMMDDTHHMMSSZ into a timezone-aware datetime."""
    try:
        return datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


async def _fetch_query(query: str, client: httpx.AsyncClient) -> list[dict]:
    """Fetch articles from the GDELT DOC API for a single query."""
    url = GDELT_DOC_API.format(query=query.replace(" ", "%20"))
    try:
        resp = await client.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("gdelt_fetch_error", query=query, error=str(e))
        return []

    items = []
    try:
        data = resp.json()
        articles = data.get("articles", [])
        for article in articles:
            title = (article.get("title") or "").strip()
            article_url = (article.get("url") or "").strip()
            if not title or not article_url:
                continue

            items.append(
                {
                    "title": title,
                    "url": article_url,
                    "published_at": _parse_seendate(article.get("seendate", "")),
                    "domain": article.get("domain"),
                    "language": article.get("language"),
                    "image_url": article.get("socialimage"),
                    "tone": article.get("tone"),
                }
            )
    except Exception as e:
        logger.warning("gdelt_parse_error", query=query, error=str(e))

    return items


@register_pipeline
class GdeltEventsPipeline(PipelineAdapter):
    """Fetches global macro event news from the GDELT Project DOC API."""

    @property
    def source_name(self) -> str:
        return "gdelt"

    @property
    def pipeline_name(self) -> str:
        return "gdelt_events"

    async def fetch(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        raw: list[dict[str, Any]] = []
        async with httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0 (compatible; Bloomvalley/1.0)"},
            follow_redirects=True,
        ) as client:
            for query in GDELT_QUERIES:
                items = await _fetch_query(query, client)
                logger.info("gdelt_query_fetched", query=query, items=len(items))
                for item in items:
                    item["is_global"] = True
                raw.extend(items)
                await asyncio.sleep(RATE_LIMIT_DELAY)

        logger.info("gdelt_fetched_total", items=len(raw))
        return raw

    async def validate(self, raw_records: list[dict]) -> tuple[list[dict], list[str]]:
        valid = []
        errors = []
        seen_fps: set[str] = set()

        for rec in raw_records:
            if not rec.get("title") or not rec.get("url"):
                errors.append("Missing title or URL")
                continue
            fp = _fingerprint(rec["title"])
            if fp in seen_fps:
                continue  # Deduplicate within batch
            seen_fps.add(fp)
            rec["fingerprint"] = fp
            valid.append(rec)

        return valid, errors

    async def transform(self, valid_records: list[dict]) -> list[dict]:
        return valid_records

    async def load(self, transformed_records: list[dict]) -> int:
        if not transformed_records:
            return 0

        # Get existing fingerprints to skip duplicates
        fps = [r["fingerprint"] for r in transformed_records]
        async with async_session() as session:
            result = await session.execute(
                select(NewsItem.fingerprint).where(NewsItem.fingerprint.in_(fps))
            )
            existing_fps = {r[0] for r in result.all()}

        rows = 0
        async with async_session() as session:
            for rec in transformed_records:
                if rec["fingerprint"] in existing_fps:
                    continue

                news_item = NewsItem(
                    title=rec["title"][:500],
                    url=rec["url"],
                    source="gdelt",
                    published_at=rec["published_at"],
                    summary=None,
                    image_url=rec.get("image_url"),
                    fingerprint=rec["fingerprint"],
                    is_global=rec.get("is_global", True),
                )
                session.add(news_item)
                rows += 1

            await session.commit()

        logger.info("gdelt_loaded", rows=rows)
        return rows
