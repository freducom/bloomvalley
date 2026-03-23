"""News feed endpoints — unified news, per-security news, bookmarks, impact tagging, sentiment."""

from datetime import datetime, date, timedelta, timezone

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, and_

from app.db.engine import async_session
from app.db.models.news import NewsItem, NewsItemSecurity
from app.db.models.securities import Security
from app.services.news_cleanup import cleanup_old_news

logger = structlog.get_logger()

router = APIRouter()


class ImpactUpdate(BaseModel):
    securityId: int
    impactDirection: str | None = None  # positive, negative, neutral
    impactSeverity: str | None = None  # high, medium, low
    impactReasoning: str | None = None


class BookmarkUpdate(BaseModel):
    isBookmarked: bool


class ManualNewsCreate(BaseModel):
    title: str
    url: str | None = None
    summary: str | None = None
    securityIds: list[int] | None = None
    isGlobal: bool = False


def _news_to_dict(item: NewsItem, linked: list[dict] | None = None) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "url": item.url,
        "source": item.source,
        "publishedAt": item.published_at.isoformat(),
        "summary": item.summary,
        "imageUrl": item.image_url,
        "isGlobal": item.is_global,
        "isBookmarked": item.is_bookmarked,
        "securities": linked or [],
        "createdAt": item.created_at.isoformat(),
    }


def _link_to_dict(link: NewsItemSecurity, sec: Security | None = None) -> dict:
    return {
        "securityId": link.security_id,
        "ticker": sec.ticker if sec else None,
        "name": sec.name if sec else None,
        "impactDirection": link.impact_direction,
        "impactSeverity": link.impact_severity,
        "impactReasoning": link.impact_reasoning,
    }


@router.post("/cleanup")
async def cleanup_news():
    """Run news retention cleanup: strip old summaries, delete expired items."""
    result = await cleanup_old_news()
    return {
        "data": result,
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("")
async def list_news(
    security_id: int | None = Query(None, alias="securityId"),
    is_global: bool | None = Query(None, alias="isGlobal"),
    impact_direction: str | None = Query(None, alias="impactDirection"),
    impact_severity: str | None = Query(None, alias="impactSeverity"),
    is_bookmarked: bool | None = Query(None, alias="isBookmarked"),
    from_date: str | None = Query(None, alias="fromDate"),
    to_date: str | None = Query(None, alias="toDate"),
    q: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Unified news feed with filters."""
    async with async_session() as session:
        query = select(NewsItem).order_by(NewsItem.published_at.desc())

        if security_id:
            query = query.join(
                NewsItemSecurity,
                NewsItemSecurity.news_item_id == NewsItem.id,
            ).where(NewsItemSecurity.security_id == security_id)

            if impact_direction:
                query = query.where(NewsItemSecurity.impact_direction == impact_direction)
            if impact_severity:
                query = query.where(NewsItemSecurity.impact_severity == impact_severity)

        if is_global is not None:
            query = query.where(NewsItem.is_global == is_global)
        if is_bookmarked is not None:
            query = query.where(NewsItem.is_bookmarked == is_bookmarked)
        if from_date:
            query = query.where(NewsItem.published_at >= datetime.fromisoformat(from_date))
        if to_date:
            query = query.where(NewsItem.published_at <= datetime.fromisoformat(to_date))
        if q:
            pattern = f"%{q}%"
            query = query.where(NewsItem.title.ilike(pattern) | NewsItem.summary.ilike(pattern))

        # Count
        count_q = select(func.count()).select_from(query.subquery())
        total = (await session.execute(count_q)).scalar_one()

        result = await session.execute(query.offset(offset).limit(limit))
        items = result.scalars().all()

        # Load linked securities for each news item
        item_ids = [i.id for i in items]
        if item_ids:
            links_result = await session.execute(
                select(NewsItemSecurity, Security)
                .join(Security, NewsItemSecurity.security_id == Security.id)
                .where(NewsItemSecurity.news_item_id.in_(item_ids))
            )
            links_by_item: dict[int, list[dict]] = {}
            for link, sec in links_result.all():
                links_by_item.setdefault(link.news_item_id, []).append(
                    _link_to_dict(link, sec)
                )
        else:
            links_by_item = {}

    data = [_news_to_dict(item, links_by_item.get(item.id, [])) for item in items]

    return {
        "data": data,
        "pagination": {"total": total, "limit": limit, "offset": offset},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/sentiment-summary")
async def sentiment_summary():
    """Aggregated sentiment for held securities over last 7 days."""
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)

    async with async_session() as session:
        result = await session.execute(
            select(
                NewsItemSecurity.security_id,
                NewsItemSecurity.impact_direction,
                func.count(NewsItemSecurity.id).label("cnt"),
            )
            .join(NewsItem, NewsItemSecurity.news_item_id == NewsItem.id)
            .where(
                NewsItem.published_at >= seven_days_ago,
                NewsItemSecurity.impact_direction.isnot(None),
            )
            .group_by(NewsItemSecurity.security_id, NewsItemSecurity.impact_direction)
        )
        rows = result.all()

        # Get security details
        sec_ids = list({r.security_id for r in rows})
        if sec_ids:
            sec_result = await session.execute(
                select(Security).where(Security.id.in_(sec_ids))
            )
            secs = {s.id: s for s in sec_result.scalars().all()}
        else:
            secs = {}

    # Aggregate
    by_security: dict[int, dict] = {}
    for r in rows:
        if r.security_id not in by_security:
            sec = secs.get(r.security_id)
            by_security[r.security_id] = {
                "securityId": r.security_id,
                "ticker": sec.ticker if sec else None,
                "name": sec.name if sec else None,
                "positive": 0,
                "negative": 0,
                "neutral": 0,
                "totalArticles": 0,
            }
        by_security[r.security_id][r.impact_direction] = r.cnt
        by_security[r.security_id]["totalArticles"] += r.cnt

    # Determine overall sentiment
    data = []
    for sid, entry in by_security.items():
        if entry["positive"] > entry["negative"]:
            sentiment = "positive"
        elif entry["negative"] > entry["positive"]:
            sentiment = "negative"
        else:
            sentiment = "neutral"
        entry["sentiment"] = sentiment
        data.append(entry)

    data.sort(key=lambda x: x["totalArticles"], reverse=True)

    return {
        "data": data,
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/security/{security_id}")
async def news_for_security(
    security_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """News for a specific security."""
    async with async_session() as session:
        query = (
            select(NewsItem)
            .join(NewsItemSecurity, NewsItemSecurity.news_item_id == NewsItem.id)
            .where(NewsItemSecurity.security_id == security_id)
            .order_by(NewsItem.published_at.desc())
        )

        count_q = select(func.count()).select_from(query.subquery())
        total = (await session.execute(count_q)).scalar_one()

        result = await session.execute(query.offset(offset).limit(limit))
        items = result.scalars().all()

        # Load links
        item_ids = [i.id for i in items]
        links_by_item: dict[int, list[dict]] = {}
        if item_ids:
            links_result = await session.execute(
                select(NewsItemSecurity, Security)
                .join(Security, NewsItemSecurity.security_id == Security.id)
                .where(NewsItemSecurity.news_item_id.in_(item_ids))
            )
            for link, sec in links_result.all():
                links_by_item.setdefault(link.news_item_id, []).append(
                    _link_to_dict(link, sec)
                )

    # Summary stats
    thirty_days = datetime.now(timezone.utc) - timedelta(days=30)
    recent_count = sum(
        1 for i in items
        if i.published_at and i.published_at >= thirty_days
    )

    data = [_news_to_dict(item, links_by_item.get(item.id, [])) for item in items]

    return {
        "data": data,
        "summary": {
            "totalArticles": total,
            "last30Days": recent_count,
        },
        "pagination": {"total": total, "limit": limit, "offset": offset},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/{news_id}")
async def get_news_item(news_id: int):
    """Get a single news item with linked securities."""
    async with async_session() as session:
        item = await session.get(NewsItem, news_id)
        if not item:
            raise HTTPException(404, "News item not found")

        links_result = await session.execute(
            select(NewsItemSecurity, Security)
            .join(Security, NewsItemSecurity.security_id == Security.id)
            .where(NewsItemSecurity.news_item_id == news_id)
        )
        linked = [_link_to_dict(link, sec) for link, sec in links_result.all()]

    return {
        "data": _news_to_dict(item, linked),
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.put("/{news_id}/impact")
async def update_impact(news_id: int, body: ImpactUpdate):
    """Tag or update impact for a news item on a specific security."""
    async with async_session() as session:
        item = await session.get(NewsItem, news_id)
        if not item:
            raise HTTPException(404, "News item not found")

        # Find or create link
        result = await session.execute(
            select(NewsItemSecurity).where(
                NewsItemSecurity.news_item_id == news_id,
                NewsItemSecurity.security_id == body.securityId,
            )
        )
        link = result.scalar_one_or_none()

        if not link:
            link = NewsItemSecurity(
                news_item_id=news_id,
                security_id=body.securityId,
            )
            session.add(link)

        if body.impactDirection is not None:
            link.impact_direction = body.impactDirection
        if body.impactSeverity is not None:
            link.impact_severity = body.impactSeverity
        if body.impactReasoning is not None:
            link.impact_reasoning = body.impactReasoning

        await session.commit()

    return {"data": {"id": news_id, "updated": True}, "meta": {"timestamp": datetime.now(timezone.utc).isoformat()}}


@router.put("/{news_id}/bookmark")
async def toggle_bookmark(news_id: int, body: BookmarkUpdate):
    """Toggle bookmark status."""
    async with async_session() as session:
        item = await session.get(NewsItem, news_id)
        if not item:
            raise HTTPException(404, "News item not found")
        item.is_bookmarked = body.isBookmarked
        await session.commit()

    return {
        "data": {"id": news_id, "isBookmarked": body.isBookmarked},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.post("")
async def create_manual_news(body: ManualNewsCreate):
    """Create a manual news entry."""
    import hashlib

    fp = hashlib.sha256(body.title.lower().strip().encode()).hexdigest()

    async with async_session() as session:
        # Check duplicate
        existing = await session.execute(
            select(NewsItem).where(NewsItem.fingerprint == fp)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(409, "Duplicate news item")

        item = NewsItem(
            title=body.title[:500],
            url=body.url or "",
            source="manual",
            published_at=datetime.now(timezone.utc),
            summary=body.summary,
            fingerprint=fp,
            is_global=body.isGlobal,
        )
        session.add(item)
        await session.flush()

        if body.securityIds:
            for sid in body.securityIds:
                link = NewsItemSecurity(
                    news_item_id=item.id,
                    security_id=sid,
                )
                session.add(link)

        await session.commit()
        await session.refresh(item)

    return {
        "data": _news_to_dict(item, []),
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }
