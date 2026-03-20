"""Google News RSS pipeline — fetches news for held and watchlist securities."""

import asyncio
import hashlib
import re
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree

import httpx
import structlog
from sqlalchemy import select, text

from app.db.engine import async_session
from app.db.models.news import NewsItem, NewsItemSecurity
from app.db.models.securities import Security
from app.pipelines import register_pipeline
from app.pipelines.base import PipelineAdapter

logger = structlog.get_logger()

# Global market queries for macro news
GLOBAL_QUERIES = [
    "stock market today",
    "ECB interest rate",
    "Federal Reserve",
    "inflation data",
    "bond yields",
]


def _normalize_title(title: str) -> str:
    """Normalize title for fingerprinting: lowercase, strip prefixes, remove punctuation."""
    t = title.lower().strip()
    # Remove common prefixes
    for prefix in ["breaking:", "update:", "exclusive:", "just in:"]:
        if t.startswith(prefix):
            t = t[len(prefix):].strip()
    # Remove punctuation and extra whitespace
    t = re.sub(r"[^\w\s]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _fingerprint(title: str) -> str:
    """SHA-256 fingerprint of normalized title."""
    return hashlib.sha256(_normalize_title(title).encode()).hexdigest()


def _clean_html(text: str) -> str:
    """Strip HTML tags from summary text."""
    return re.sub(r"<[^>]+>", "", text).strip()


async def _fetch_rss(query: str, client: httpx.AsyncClient) -> list[dict]:
    """Fetch and parse a Google News RSS feed for a query."""
    encoded_query = query.replace(" ", "+")
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en&gl=US&ceid=US:en"
    try:
        resp = await client.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("google_news_fetch_error", query=query, error=str(e))
        return []

    items = []
    try:
        root = ElementTree.fromstring(resp.text)
        for item in root.findall(".//item"):
            title_el = item.find("title")
            link_el = item.find("link")
            pub_date_el = item.find("pubDate")
            desc_el = item.find("description")
            source_el = item.find("source")

            if title_el is None or link_el is None:
                continue

            title = title_el.text or ""
            if not title.strip():
                continue

            published_at = None
            if pub_date_el is not None and pub_date_el.text:
                try:
                    published_at = parsedate_to_datetime(pub_date_el.text)
                    if published_at.tzinfo is None:
                        published_at = published_at.replace(tzinfo=timezone.utc)
                except Exception:
                    published_at = datetime.now(timezone.utc)

            summary = ""
            if desc_el is not None and desc_el.text:
                summary = _clean_html(desc_el.text)[:500]

            source_name = "Google News"
            if source_el is not None and source_el.text:
                source_name = source_el.text

            items.append({
                "title": title.strip(),
                "url": (link_el.text or "").strip(),
                "published_at": published_at or datetime.now(timezone.utc),
                "summary": summary,
                "source_name": source_name,
            })
    except ElementTree.ParseError as e:
        logger.warning("google_news_parse_error", query=query, error=str(e))

    return items


@register_pipeline
class GoogleNewsPipeline(PipelineAdapter):
    """Fetches news from Google News RSS for held securities and global topics."""

    @property
    def source_name(self) -> str:
        return "google_news"

    @property
    def pipeline_name(self) -> str:
        return "google_news"

    async def fetch(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        # Get held securities + watchlist securities
        async with async_session() as session:
            result = await session.execute(
                select(Security).where(Security.is_active.is_(True))
            )
            securities = {s.id: s for s in result.scalars().all()}

        raw: list[dict[str, Any]] = []
        async with httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0 (compatible; WarrenCashett/1.0)"},
            follow_redirects=True,
        ) as client:
            # Per-security news
            for sid, sec in securities.items():
                query = f"{sec.ticker} {sec.name} stock"
                items = await _fetch_rss(query, client)
                for item in items:
                    item["security_ids"] = [sid]
                    item["is_global"] = False
                raw.extend(items)
                await asyncio.sleep(0.5)  # Rate limiting

            # Global news
            for query in GLOBAL_QUERIES:
                items = await _fetch_rss(query, client)
                for item in items:
                    item["security_ids"] = []
                    item["is_global"] = True
                raw.extend(items)
                await asyncio.sleep(0.5)

        logger.info("google_news_fetched", items=len(raw))
        return raw

    async def validate(self, raw_records: list[dict]) -> tuple[list[dict], list[str]]:
        valid = []
        errors = []
        seen_fps = set()

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
                    source="google_news",
                    published_at=rec["published_at"],
                    summary=rec.get("summary"),
                    fingerprint=rec["fingerprint"],
                    is_global=rec.get("is_global", False),
                )
                session.add(news_item)
                await session.flush()

                # Link to securities
                for sid in rec.get("security_ids", []):
                    link = NewsItemSecurity(
                        news_item_id=news_item.id,
                        security_id=sid,
                    )
                    session.add(link)

                rows += 1

            await session.commit()

        logger.info("google_news_loaded", rows=rows)
        return rows
