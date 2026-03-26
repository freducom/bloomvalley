"""Research notes endpoints — CRUD for per-security investment analysis."""

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, text

from app.db.engine import async_session
from app.db.models.holdings_snapshot import HoldingsSnapshot
from app.db.models.recommendations import Recommendation
from app.db.models.research_notes import ResearchNote
from app.db.models.securities import Security
from app.db.models.watchlists import WatchlistItem
from app.api.v1.portfolio import _get_latest_prices

logger = structlog.get_logger()

router = APIRouter()


class NoteCreate(BaseModel):
    securityId: int | None = None
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
        "ticker": sec.ticker if sec else None,
        "securityName": sec.name if sec else None,
        "sector": sec.sector if sec else None,
        "assetClass": sec.asset_class if sec else None,
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
            .outerjoin(Security, ResearchNote.security_id == Security.id)
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
        pc = prices.get(sec.id, {}).get("close_cents") if sec and sec.id in prices else None
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
        sec = None
        if body.securityId is not None:
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
            intrinsic_value_currency=body.intrinsicValueCurrency or (sec.currency if sec else None),
            margin_of_safety_pct=body.marginOfSafetyPct,
            moat_rating=body.moatRating,
            tags=body.tags,
        )
        session.add(note)
        await session.commit()
        await session.refresh(note)

    prices = await _get_latest_prices()
    pc = prices.get(sec.id, {}).get("close_cents") if sec else None
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


@router.post("/cleanup")
async def cleanup_research():
    """Run research notes retention cleanup: delete old auto-generated notes."""
    from app.services.research_cleanup import cleanup_old_research
    result = await cleanup_old_research()
    return {"data": result, "meta": {"timestamp": datetime.now(timezone.utc).isoformat()}}


KNOWN_AGENTS = [
    "research-analyst",
    "technical-analyst",
    "risk-manager",
    "quant-analyst",
    "macro-strategist",
    "fixed-income-analyst",
    "tax-strategist",
    "compliance-officer",
    "portfolio-manager",
]


@router.get("/coverage")
async def research_coverage():
    """Return coverage status for all securities in holdings + watchlists."""
    now = datetime.now(timezone.utc)

    async with async_session() as session:
        # 1. Get security IDs from latest holdings snapshot
        latest_date_q = select(func.max(HoldingsSnapshot.snapshot_date))
        latest_date = (await session.execute(latest_date_q)).scalar_one_or_none()

        portfolio_ids: set[int] = set()
        if latest_date is not None:
            port_q = select(HoldingsSnapshot.security_id.distinct()).where(
                HoldingsSnapshot.snapshot_date == latest_date
            )
            portfolio_ids = {r[0] for r in (await session.execute(port_q)).all()}

        # 2. Get security IDs from watchlists
        wl_q = select(WatchlistItem.security_id.distinct())
        watchlist_ids = {r[0] for r in (await session.execute(wl_q)).all()}

        all_ids = portfolio_ids | watchlist_ids
        if not all_ids:
            return {
                "data": [],
                "summary": {"total": 0, "fresh": 0, "stale": 0, "veryStale": 0, "missing": 0},
                "meta": {"timestamp": now.isoformat()},
            }

        # 3. Get securities info
        sec_q = select(Security).where(Security.id.in_(all_ids))
        securities = {s.id: s for s in (await session.execute(sec_q)).scalars().all()}

        # 4. Get research note stats per security
        notes_q = (
            select(
                ResearchNote.security_id,
                func.max(ResearchNote.updated_at).label("last_updated"),
                func.count(ResearchNote.id).label("note_count"),
            )
            .where(ResearchNote.is_active.is_(True))
            .where(ResearchNote.security_id.in_(all_ids))
            .group_by(ResearchNote.security_id)
        )
        note_stats: dict[int, dict] = {}
        for row in (await session.execute(notes_q)).all():
            note_stats[row.security_id] = {
                "last_updated": row.last_updated,
                "note_count": row.note_count,
            }

        # 5. Check for analyst and technical notes per security
        analyst_q = (
            select(ResearchNote.security_id.distinct())
            .where(ResearchNote.is_active.is_(True))
            .where(ResearchNote.security_id.in_(all_ids))
            .where(ResearchNote.tags.any("research-analyst"))
        )
        analyst_ids = {r[0] for r in (await session.execute(analyst_q)).all()}

        technical_q = (
            select(ResearchNote.security_id.distinct())
            .where(ResearchNote.is_active.is_(True))
            .where(ResearchNote.security_id.in_(all_ids))
            .where(ResearchNote.tags.any("technical"))
        )
        technical_ids = {r[0] for r in (await session.execute(technical_q)).all()}

    # 6. Build response
    staleness_order = {"missing": 0, "very_stale": 1, "stale": 2, "fresh": 3}
    summary = {"total": 0, "fresh": 0, "stale": 0, "veryStale": 0, "missing": 0}
    data = []

    for sid in all_ids:
        sec = securities.get(sid)
        if not sec:
            continue

        stats = note_stats.get(sid)
        last_date = stats["last_updated"] if stats else None
        note_count = stats["note_count"] if stats else 0

        if last_date is None:
            staleness = "missing"
        else:
            # Ensure timezone-aware comparison
            if last_date.tzinfo is None:
                age = now.replace(tzinfo=None) - last_date
            else:
                age = now - last_date
            days = age.total_seconds() / 86400
            if days < 3:
                staleness = "fresh"
            elif days < 7:
                staleness = "stale"
            else:
                staleness = "very_stale"

        summary["total"] += 1
        if staleness == "fresh":
            summary["fresh"] += 1
        elif staleness == "stale":
            summary["stale"] += 1
        elif staleness == "very_stale":
            summary["veryStale"] += 1
        else:
            summary["missing"] += 1

        data.append({
            "securityId": sid,
            "ticker": sec.ticker,
            "name": sec.name,
            "assetClass": sec.asset_class,
            "isInPortfolio": sid in portfolio_ids,
            "isOnWatchlist": sid in watchlist_ids,
            "lastResearchDate": last_date.isoformat() if last_date else None,
            "noteCount": note_count,
            "hasAnalystNote": sid in analyst_ids,
            "hasTechnicalNote": sid in technical_ids,
            "staleness": staleness,
            "_stalenessOrder": staleness_order[staleness],
        })

    data.sort(key=lambda x: (x["_stalenessOrder"], x["ticker"] or ""))
    for item in data:
        del item["_stalenessOrder"]

    return {
        "data": data,
        "summary": summary,
        "meta": {"timestamp": now.isoformat()},
    }


@router.get("/consensus")
async def research_consensus():
    """Return analyst consensus for all tracked securities."""
    now = datetime.now(timezone.utc)

    async with async_session() as session:
        # 1. Get tracked security IDs (same as coverage)
        latest_date_q = select(func.max(HoldingsSnapshot.snapshot_date))
        latest_date = (await session.execute(latest_date_q)).scalar_one_or_none()

        portfolio_ids: set[int] = set()
        if latest_date is not None:
            port_q = select(HoldingsSnapshot.security_id.distinct()).where(
                HoldingsSnapshot.snapshot_date == latest_date
            )
            portfolio_ids = {r[0] for r in (await session.execute(port_q)).all()}

        wl_q = select(WatchlistItem.security_id.distinct())
        watchlist_ids = {r[0] for r in (await session.execute(wl_q)).all()}

        all_ids = portfolio_ids | watchlist_ids
        if not all_ids:
            return {"data": [], "meta": {"timestamp": now.isoformat()}}

        # 2. Get securities info
        sec_q = select(Security).where(Security.id.in_(all_ids))
        securities = {s.id: s for s in (await session.execute(sec_q)).scalars().all()}

        # 3. Get all active research notes for these securities
        notes_q = (
            select(ResearchNote)
            .where(ResearchNote.is_active.is_(True))
            .where(ResearchNote.security_id.in_(all_ids))
            .order_by(ResearchNote.updated_at.desc())
        )
        all_notes = (await session.execute(notes_q)).scalars().all()

        # 4. Get latest active recommendation per security
        rec_subq = (
            select(
                Recommendation.security_id,
                func.max(Recommendation.id).label("max_id"),
            )
            .where(Recommendation.status == "active")
            .where(Recommendation.security_id.in_(all_ids))
            .group_by(Recommendation.security_id)
            .subquery()
        )
        rec_q = (
            select(Recommendation)
            .join(rec_subq, Recommendation.id == rec_subq.c.max_id)
        )
        recs_by_sec: dict[int, Recommendation] = {}
        for rec in (await session.execute(rec_q)).scalars().all():
            recs_by_sec[rec.security_id] = rec

    # 5. Organize notes by security and agent
    notes_by_sec: dict[int, dict[str, list]] = {}
    for note in all_notes:
        sid = note.security_id
        if sid not in notes_by_sec:
            notes_by_sec[sid] = {}
        tags = note.tags or []
        for agent in KNOWN_AGENTS:
            if agent in tags:
                if agent not in notes_by_sec[sid]:
                    notes_by_sec[sid][agent] = []
                notes_by_sec[sid][agent].append(note)

    # 6. Build response
    data = []
    for sid in all_ids:
        sec = securities.get(sid)
        if not sec:
            continue

        rec = recs_by_sec.get(sid)
        pm_action = rec.action if rec else None
        pm_confidence = rec.confidence if rec else None

        agent_notes = notes_by_sec.get(sid, {})
        agent_coverage = len(agent_notes)

        # Extract research-analyst verdict from thesis
        research_verdict = None
        moat_rating = None
        ra_notes = agent_notes.get("research-analyst", [])
        if ra_notes:
            latest_ra = ra_notes[0]  # already sorted by updated_at desc
            thesis = latest_ra.thesis or ""
            for verdict_str in ["BUY", "AVOID", "WAIT", "HOLD"]:
                if f"**{verdict_str}**" in thesis:
                    research_verdict = verdict_str
                    break
            if latest_ra.moat_rating:
                moat_rating = latest_ra.moat_rating

        # Detect conflicts
        has_conflict = False
        conflict_details = None
        if pm_action and research_verdict:
            pm_norm = pm_action.lower()
            rv_norm = research_verdict.lower()
            if (pm_norm == "buy" and rv_norm == "avoid") or (
                pm_norm == "sell" and rv_norm == "buy"
            ):
                has_conflict = True
                conflict_details = (
                    f"PM recommends {pm_action.upper()} but research-analyst says {research_verdict}"
                )

        # Build agents dict
        agents_dict = {}
        for agent in KNOWN_AGENTS:
            a_notes = agent_notes.get(agent, [])
            if a_notes:
                latest = a_notes[0]
                a_verdict = None
                if agent == "research-analyst" and research_verdict:
                    a_verdict = research_verdict
                agents_dict[agent] = {
                    "hasNote": True,
                    "verdict": a_verdict,
                    "updatedAt": latest.updated_at.isoformat(),
                }

        data.append({
            "securityId": sid,
            "ticker": sec.ticker,
            "name": sec.name,
            "pmAction": pm_action,
            "pmConfidence": pm_confidence,
            "researchVerdict": research_verdict,
            "moatRating": moat_rating,
            "agentCoverage": agent_coverage,
            "totalAgents": len(KNOWN_AGENTS),
            "hasConflict": has_conflict,
            "conflictDetails": conflict_details,
            "agents": agents_dict,
            "_sortConflict": 0 if has_conflict else 1,
        })

    data.sort(key=lambda x: (x["_sortConflict"], x["agentCoverage"], x.get("ticker") or ""))
    for item in data:
        del item["_sortConflict"]

    return {
        "data": data,
        "meta": {"timestamp": now.isoformat()},
    }
