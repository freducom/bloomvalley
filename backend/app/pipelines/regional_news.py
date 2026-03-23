"""Regional News RSS pipeline — fetches financial news from 5 regional RSS feeds."""

import asyncio
import hashlib
import re
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree

import httpx
import structlog
from sqlalchemy import select

from app.db.engine import async_session
from app.db.models.news import NewsItem, NewsItemSecurity
from app.db.models.securities import Security
from app.pipelines import register_pipeline
from app.pipelines.base import PipelineAdapter

logger = structlog.get_logger()

# Regional RSS feed definitions
REGIONAL_FEEDS = [
    {
        "name": "CNBC World",
        "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100727362",
        "fallback_url": None,
        "is_global": True,
    },
    {
        "name": "ECB",
        "url": "https://www.ecb.europa.eu/rss/press.html",
        "fallback_url": None,
        "is_global": True,
    },
    {
        "name": "YLE Business",
        "url": "https://feeds.yle.fi/uutiset/v1/recent.rss?publisherIds=YLE_UUTISET&categories=18-220668",
        "fallback_url": None,
        "is_global": False,
    },
    {
        "name": "Dagens Industri",
        "url": "https://www.di.se/rss",
        "fallback_url": None,
        "is_global": False,
    },
    {
        "name": "FT Markets",
        "url": "https://www.ft.com/markets?format=rss",
        "fallback_url": None,
        "is_global": True,
    },
    {
        "name": "Yardeni QuickTakes",
        "url": "https://www.yardeniquicktakes.com/rss/",
        "fallback_url": None,
        "is_global": True,
    },
]


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


def _clean_html(text: str) -> str:
    """Strip HTML tags from summary text."""
    return re.sub(r"<[^>]+>", "", text).strip()


def _parse_published_at(pub_date_text: str | None) -> datetime:
    """Parse an RSS pubDate string into a timezone-aware datetime."""
    if not pub_date_text:
        return datetime.now(timezone.utc)
    try:
        dt = parsedate_to_datetime(pub_date_text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.now(timezone.utc)


def _match_securities(
    title: str, securities: dict[int, "Security"]
) -> list[int]:
    """Check if any held/watchlisted ticker appears in the title (case-insensitive)."""
    title_lower = title.lower()
    matched_ids: list[int] = []
    for sid, sec in securities.items():
        ticker = sec.ticker
        if not ticker:
            continue
        # Match ticker as a whole word (case-insensitive)
        # Strip exchange prefix if present (e.g., "HEL:NOKIA" -> "NOKIA")
        bare_ticker = ticker.split(":")[-1] if ":" in ticker else ticker
        if len(bare_ticker) < 2:
            continue
        pattern = r"\b" + re.escape(bare_ticker) + r"\b"
        if re.search(pattern, title_lower, re.IGNORECASE):
            matched_ids.append(sid)
    return matched_ids


async def _fetch_feed(
    feed: dict, client: httpx.AsyncClient
) -> list[dict]:
    """Fetch and parse a single RSS feed. Falls back to fallback_url on failure."""
    urls_to_try = [feed["url"]]
    if feed.get("fallback_url"):
        urls_to_try.append(feed["fallback_url"])

    resp = None
    for url in urls_to_try:
        try:
            resp = await client.get(url, timeout=15)
            resp.raise_for_status()
            break
        except Exception as e:
            logger.warning(
                "regional_news_fetch_error",
                feed=feed["name"],
                url=url,
                error=str(e),
            )
            resp = None

    if resp is None:
        logger.error("regional_news_feed_failed", feed=feed["name"])
        return []

    items: list[dict] = []
    try:
        root = ElementTree.fromstring(resp.text)
        # Standard RSS 2.0: items under <channel><item>
        # Also handle Atom feeds: <entry> elements
        rss_items = root.findall(".//item")
        if not rss_items:
            # Try Atom format
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            rss_items = root.findall(".//atom:entry", ns)

        for item in rss_items:
            # RSS 2.0 fields
            title_el = item.find("title")
            link_el = item.find("link")
            pub_date_el = item.find("pubDate")
            desc_el = item.find("description")

            # Atom fallbacks
            if title_el is None:
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                title_el = item.find("atom:title", ns)
            if link_el is None:
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                link_el = item.find("atom:link", ns)
            if pub_date_el is None:
                # Atom uses <updated> or <published>
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                pub_date_el = item.find("atom:published", ns) or item.find(
                    "atom:updated", ns
                )
            if desc_el is None:
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                desc_el = item.find("atom:summary", ns) or item.find(
                    "atom:content", ns
                )

            if title_el is None or link_el is None:
                continue

            title = title_el.text or ""
            if not title.strip():
                continue

            # For Atom <link>, the URL is in the href attribute
            url = ""
            if link_el.text:
                url = link_el.text.strip()
            elif link_el.get("href"):
                url = link_el.get("href", "").strip()
            if not url:
                continue

            published_at = _parse_published_at(
                pub_date_el.text if pub_date_el is not None else None
            )

            summary = ""
            if desc_el is not None and desc_el.text:
                summary = _clean_html(desc_el.text)[:500]

            items.append(
                {
                    "title": title.strip(),
                    "url": url,
                    "published_at": published_at,
                    "summary": summary,
                    "source_name": feed["name"],
                    "is_global": feed["is_global"],
                }
            )
    except ElementTree.ParseError as e:
        logger.warning(
            "regional_news_parse_error", feed=feed["name"], error=str(e)
        )

    logger.info(
        "regional_news_feed_parsed", feed=feed["name"], items=len(items)
    )
    return items


@register_pipeline
class RegionalNewsPipeline(PipelineAdapter):
    """Fetches financial news from 5 regional RSS feeds."""

    @property
    def source_name(self) -> str:
        return "regional_rss"

    @property
    def pipeline_name(self) -> str:
        return "regional_news"

    async def fetch(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        # Load active securities for ticker matching
        async with async_session() as session:
            result = await session.execute(
                select(Security).where(Security.is_active.is_(True))
            )
            securities = {s.id: s for s in result.scalars().all()}

        raw: list[dict[str, Any]] = []
        async with httpx.AsyncClient(
            headers={"User-Agent": "BloomvalleyTerminal/1.0"},
            follow_redirects=True,
        ) as client:
            for i, feed in enumerate(REGIONAL_FEEDS):
                items = await _fetch_feed(feed, client)
                for item in items:
                    # Try to link news to securities by checking ticker in title
                    item["security_ids"] = _match_securities(
                        item["title"], securities
                    )
                raw.extend(items)
                # 2s delay between feeds to be polite (skip after last)
                if i < len(REGIONAL_FEEDS) - 1:
                    await asyncio.sleep(2.0)

        logger.info("regional_news_fetched", total_items=len(raw))
        return raw

    async def validate(
        self, raw_records: list[dict]
    ) -> tuple[list[dict], list[str]]:
        valid: list[dict] = []
        errors: list[str] = []
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
                select(NewsItem.fingerprint).where(
                    NewsItem.fingerprint.in_(fps)
                )
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
                    source="regional_rss",
                    published_at=rec["published_at"],
                    summary=rec.get("summary"),
                    fingerprint=rec["fingerprint"],
                    is_global=rec.get("is_global", False),
                )
                session.add(news_item)
                await session.flush()

                # Link to matched securities
                for sid in rec.get("security_ids", []):
                    link = NewsItemSecurity(
                        news_item_id=news_item.id,
                        security_id=sid,
                    )
                    session.add(link)

                rows += 1

            await session.commit()

        logger.info("regional_news_loaded", rows=rows)
        return rows
