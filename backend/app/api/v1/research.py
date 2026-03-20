"""Research notes endpoints — CRUD for per-security investment analysis."""

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.db.engine import async_session
from app.db.models.research_notes import ResearchNote
from app.db.models.securities import Security
from app.api.v1.portfolio import _get_latest_prices

logger = structlog.get_logger()

router = APIRouter()


class NoteCreate(BaseModel):
    securityId: int
    title: str
    thesis: str | None = None
    bullCase: str | None = None
    bearCase: str | None = None
    baseCase: str | None = None
    intrinsicValueCents: int | None = None
    intrinsicValueCurrency: str | None = None
    marginOfSafetyPct: float | None = None
    moatRating: str | None = None  # none, narrow, wide
    tags: list[str] | None = None


class NoteUpdate(BaseModel):
    title: str | None = None
    thesis: str | None = None
    bullCase: str | None = None
    bearCase: str | None = None
    baseCase: str | None = None
    intrinsicValueCents: int | None = None
    intrinsicValueCurrency: str | None = None
    marginOfSafetyPct: float | None = None
    moatRating: str | None = None
    tags: list[str] | None = None
    isActive: bool | None = None


def _note_to_dict(note: ResearchNote, sec: Security, price_cents: int | None = None):
    mos = None
    if note.intrinsic_value_cents and price_cents and price_cents > 0:
        mos = round(((note.intrinsic_value_cents - price_cents) / note.intrinsic_value_cents) * 100, 2)

    return {
        "id": note.id,
        "securityId": note.security_id,
        "ticker": sec.ticker,
        "securityName": sec.name,
        "sector": sec.sector,
        "assetClass": sec.asset_class,
        "title": note.title,
        "thesis": note.thesis,
        "bullCase": note.bull_case,
        "bearCase": note.bear_case,
        "baseCase": note.base_case,
        "intrinsicValueCents": note.intrinsic_value_cents,
        "intrinsicValueCurrency": note.intrinsic_value_currency,
        "marginOfSafetyPct": float(note.margin_of_safety_pct) if note.margin_of_safety_pct is not None else mos,
        "currentPriceCents": price_cents,
        "moatRating": note.moat_rating,
        "tags": note.tags or [],
        "isActive": note.is_active,
        "createdAt": note.created_at.isoformat(),
        "updatedAt": note.updated_at.isoformat(),
    }


@router.get("/notes")
async def list_notes(
    security_id: int | None = Query(None, alias="securityId"),
    moat_rating: str | None = Query(None, alias="moatRating"),
    is_active: bool | None = Query(None, alias="isActive"),
    tag: str | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List research notes with filters."""
    async with async_session() as session:
        query = (
            select(ResearchNote, Security)
            .join(Security, ResearchNote.security_id == Security.id)
            .order_by(ResearchNote.updated_at.desc())
        )

        if security_id:
            query = query.where(ResearchNote.security_id == security_id)
        if moat_rating:
            query = query.where(ResearchNote.moat_rating == moat_rating)
        if is_active is not None:
            query = query.where(ResearchNote.is_active == is_active)
        if tag:
            query = query.where(ResearchNote.tags.any(tag))
        if q:
            pattern = f"%{q}%"
            query = query.where(
                ResearchNote.title.ilike(pattern)
                | ResearchNote.thesis.ilike(pattern)
                | Security.ticker.ilike(pattern)
                | Security.name.ilike(pattern)
            )

        # Count
        count_q = select(func.count()).select_from(query.subquery())
        total = (await session.execute(count_q)).scalar_one()

        result = await session.execute(query.offset(offset).limit(limit))
        rows = result.all()

    prices = await _get_latest_prices()
    data = []
    for note, sec in rows:
        pc = prices.get(sec.id, {}).get("close_cents") if sec.id in prices else None
        data.append(_note_to_dict(note, sec, pc))

    return {
        "data": data,
        "pagination": {"total": total, "limit": limit, "offset": offset},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/notes/{note_id}")
async def get_note(note_id: int):
    """Get a single research note."""
    async with async_session() as session:
        result = await session.execute(
            select(ResearchNote, Security)
            .join(Security, ResearchNote.security_id == Security.id)
            .where(ResearchNote.id == note_id)
        )
        row = result.one_or_none()
        if not row:
            raise HTTPException(404, "Research note not found")
        note, sec = row

    prices = await _get_latest_prices()
    pc = prices.get(sec.id, {}).get("close_cents")
    return {"data": _note_to_dict(note, sec, pc), "meta": {"timestamp": datetime.now(timezone.utc).isoformat()}}


@router.post("/notes")
async def create_note(body: NoteCreate):
    """Create a new research note."""
    async with async_session() as session:
        sec = await session.get(Security, body.securityId)
        if not sec:
            raise HTTPException(404, "Security not found")

        note = ResearchNote(
            security_id=body.securityId,
            title=body.title,
            thesis=body.thesis,
            bull_case=body.bullCase,
            bear_case=body.bearCase,
            base_case=body.baseCase,
            intrinsic_value_cents=body.intrinsicValueCents,
            intrinsic_value_currency=body.intrinsicValueCurrency or sec.currency,
            margin_of_safety_pct=body.marginOfSafetyPct,
            moat_rating=body.moatRating,
            tags=body.tags,
        )
        session.add(note)
        await session.commit()
        await session.refresh(note)

    prices = await _get_latest_prices()
    pc = prices.get(sec.id, {}).get("close_cents")
    return {"data": _note_to_dict(note, sec, pc), "meta": {"timestamp": datetime.now(timezone.utc).isoformat()}}


@router.put("/notes/{note_id}")
async def update_note(note_id: int, body: NoteUpdate):
    """Update a research note."""
    async with async_session() as session:
        note = await session.get(ResearchNote, note_id)
        if not note:
            raise HTTPException(404, "Research note not found")

        if body.title is not None:
            note.title = body.title
        if body.thesis is not None:
            note.thesis = body.thesis
        if body.bullCase is not None:
            note.bull_case = body.bullCase
        if body.bearCase is not None:
            note.bear_case = body.bearCase
        if body.baseCase is not None:
            note.base_case = body.baseCase
        if body.intrinsicValueCents is not None:
            note.intrinsic_value_cents = body.intrinsicValueCents
        if body.intrinsicValueCurrency is not None:
            note.intrinsic_value_currency = body.intrinsicValueCurrency
        if body.marginOfSafetyPct is not None:
            note.margin_of_safety_pct = body.marginOfSafetyPct
        if body.moatRating is not None:
            note.moat_rating = body.moatRating
        if body.tags is not None:
            note.tags = body.tags
        if body.isActive is not None:
            note.is_active = body.isActive

        await session.commit()
        await session.refresh(note)

        sec = await session.get(Security, note.security_id)

    prices = await _get_latest_prices()
    pc = prices.get(sec.id, {}).get("close_cents")
    return {"data": _note_to_dict(note, sec, pc), "meta": {"timestamp": datetime.now(timezone.utc).isoformat()}}


@router.delete("/notes/{note_id}")
async def delete_note(note_id: int):
    """Soft-delete a research note."""
    async with async_session() as session:
        note = await session.get(ResearchNote, note_id)
        if not note:
            raise HTTPException(404, "Research note not found")
        note.is_active = False
        await session.commit()

    return {"data": {"id": note_id, "deleted": True}, "meta": {"timestamp": datetime.now(timezone.utc).isoformat()}}


@router.get("/tags")
async def list_tags():
    """Get all unique tags used across research notes."""
    async with async_session() as session:
        result = await session.execute(
            select(func.unnest(ResearchNote.tags).label("tag"))
            .where(ResearchNote.is_active.is_(True))
            .distinct()
        )
        tags = sorted([r.tag for r in result.all()])
    return {"data": tags, "meta": {"timestamp": datetime.now(timezone.utc).isoformat()}}
