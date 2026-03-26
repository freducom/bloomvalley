"""Recommendation tracker — buy/sell/hold calls with retrospective accuracy."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.db.engine import async_session
from app.db.models.recommendation_checkpoints import RecommendationCheckpoint
from app.db.models.recommendations import Recommendation
from app.db.models.securities import Security
from app.db.models.prices import Price

logger = structlog.get_logger()

router = APIRouter()


class RecommendationCreate(BaseModel):
    security_id: int
    action: str  # buy, sell, hold
    confidence: str  # high, medium, low
    target_price_cents: int | None = None
    entry_price_cents: int | None = None
    currency: str = "EUR"
    rationale: str
    bull_case: str | None = None
    bear_case: str | None = None
    source: str | None = None
    time_horizon: str | None = None  # short, medium, long
    recommended_date: str | None = None
    expiry_date: str | None = None


class RecommendationClose(BaseModel):
    exit_price_cents: int | None = None
    outcome_notes: str | None = None


def _rec_to_dict(r: Recommendation, sec: Security | None = None) -> dict:
    return {
        "id": r.id,
        "securityId": r.security_id,
        "ticker": sec.ticker if sec else None,
        "securityName": sec.name if sec else None,
        "action": r.action,
        "confidence": r.confidence,
        "targetPriceCents": r.target_price_cents,
        "entryPriceCents": r.entry_price_cents,
        "currency": r.currency,
        "rationale": r.rationale,
        "bullCase": r.bull_case,
        "bearCase": r.bear_case,
        "source": r.source,
        "timeHorizon": r.time_horizon,
        "status": r.status,
        "recommendedDate": r.recommended_date.isoformat(),
        "closedDate": r.closed_date.isoformat() if r.closed_date else None,
        "expiryDate": r.expiry_date.isoformat() if r.expiry_date else None,
        "exitPriceCents": r.exit_price_cents,
        "returnPct": float(r.return_pct) if r.return_pct is not None else None,
        "outcomeNotes": r.outcome_notes,
    }


@router.get("")
async def list_recommendations(
    status: str | None = Query(None),
    action: str | None = Query(None),
    security_id: int | None = Query(None, alias="securityId"),
    source: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List recommendations with filters."""
    async with async_session() as session:
        query = (
            select(Recommendation, Security)
            .join(Security, Recommendation.security_id == Security.id)
            .order_by(Recommendation.recommended_date.desc())
        )

        if status:
            query = query.where(Recommendation.status == status)
        if action:
            query = query.where(Recommendation.action == action)
        if security_id:
            query = query.where(Recommendation.security_id == security_id)
        if source:
            query = query.where(Recommendation.source == source)

        count_q = select(func.count()).select_from(query.subquery())
        total = (await session.execute(count_q)).scalar_one()

        result = await session.execute(query.offset(offset).limit(limit))
        rows = result.all()

    data = [_rec_to_dict(r, sec) for r, sec in rows]

    return {
        "data": data,
        "pagination": {"total": total, "limit": limit, "offset": offset},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.post("")
async def create_recommendation(body: RecommendationCreate):
    """Create a new recommendation."""
    async with async_session() as session:
        sec = await session.get(Security, body.security_id)
        if not sec:
            raise HTTPException(404, "Security not found")

        rec_date = date.fromisoformat(body.recommended_date) if body.recommended_date else date.today()

        # Auto-close any existing active recommendation for the same security+action
        existing = await session.execute(
            select(Recommendation)
            .where(
                Recommendation.security_id == body.security_id,
                Recommendation.action == body.action,
                Recommendation.status == "active",
            )
        )
        for old_rec in existing.scalars().all():
            old_rec.status = "closed"
            old_rec.closed_date = date.today()
            old_rec.outcome_notes = "Superseded by new recommendation"

        # Auto-fill entry price from latest price if not provided
        entry_price = body.entry_price_cents
        if not entry_price:
            price_result = await session.execute(
                select(Price.close_cents)
                .where(Price.security_id == body.security_id)
                .order_by(Price.date.desc())
                .limit(1)
            )
            latest = price_result.scalar_one_or_none()
            if latest:
                entry_price = latest

        rec = Recommendation(
            security_id=body.security_id,
            action=body.action,
            confidence=body.confidence,
            target_price_cents=body.target_price_cents,
            entry_price_cents=entry_price,
            currency=body.currency,
            rationale=body.rationale,
            bull_case=body.bull_case,
            bear_case=body.bear_case,
            source=body.source,
            time_horizon=body.time_horizon,
            recommended_date=rec_date,
            expiry_date=date.fromisoformat(body.expiry_date) if body.expiry_date else None,
        )
        session.add(rec)
        await session.commit()
        await session.refresh(rec)

    return {
        "data": _rec_to_dict(rec, sec),
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.put("/{rec_id}/close")
async def close_recommendation(rec_id: int, body: RecommendationClose):
    """Close a recommendation and record outcome."""
    async with async_session() as session:
        rec = await session.get(Recommendation, rec_id)
        if not rec:
            raise HTTPException(404, "Recommendation not found")
        if rec.status == "closed":
            raise HTTPException(409, "Already closed")

        # Get exit price from body or latest price
        exit_price = body.exit_price_cents
        if not exit_price:
            price_result = await session.execute(
                select(Price.close_cents)
                .where(Price.security_id == rec.security_id)
                .order_by(Price.date.desc())
                .limit(1)
            )
            exit_price = price_result.scalar_one_or_none()

        # Calculate return
        return_pct = None
        if exit_price and rec.entry_price_cents and rec.entry_price_cents != 0:
            if rec.action == "buy":
                return_pct = Decimal(
                    str(round((exit_price - rec.entry_price_cents) / rec.entry_price_cents * 100, 4))
                )
            elif rec.action == "sell":
                # Sell recommendation: profit if price went down
                return_pct = Decimal(
                    str(round((rec.entry_price_cents - exit_price) / rec.entry_price_cents * 100, 4))
                )

        rec.status = "closed"
        rec.closed_date = date.today()
        rec.exit_price_cents = exit_price
        rec.return_pct = return_pct
        rec.outcome_notes = body.outcome_notes

        await session.commit()
        await session.refresh(rec)

        sec = await session.get(Security, rec.security_id)

    return {
        "data": _rec_to_dict(rec, sec),
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/retrospective")
async def get_retrospective():
    """Retrospective analysis of all closed recommendations."""
    async with async_session() as session:
        result = await session.execute(
            select(Recommendation).where(Recommendation.status == "closed")
        )
        closed = result.scalars().all()

        active_result = await session.execute(
            select(func.count()).where(Recommendation.status == "active")
        )
        active_count = active_result.scalar_one()

    if not closed:
        return {
            "data": {
                "totalClosed": 0,
                "activeCount": active_count,
                "hitRate": None,
                "avgReturnPct": None,
                "byAction": {},
                "byConfidence": {},
                "bySource": {},
                "bestCalls": [],
                "worstCalls": [],
            },
            "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
        }

    # Calculate metrics
    total = len(closed)
    wins = [r for r in closed if r.return_pct is not None and r.return_pct > 0]
    losses = [r for r in closed if r.return_pct is not None and r.return_pct <= 0]
    with_returns = [r for r in closed if r.return_pct is not None]

    hit_rate = round(len(wins) / len(with_returns) * 100, 1) if with_returns else None
    avg_return = round(float(sum(r.return_pct for r in with_returns)) / len(with_returns), 2) if with_returns else None

    # By action
    by_action = {}
    for action in ["buy", "sell", "hold"]:
        action_recs = [r for r in with_returns if r.action == action]
        if action_recs:
            action_wins = [r for r in action_recs if r.return_pct > 0]
            by_action[action] = {
                "count": len(action_recs),
                "hitRate": round(len(action_wins) / len(action_recs) * 100, 1),
                "avgReturnPct": round(float(sum(r.return_pct for r in action_recs)) / len(action_recs), 2),
            }

    # By confidence
    by_confidence = {}
    for conf in ["high", "medium", "low"]:
        conf_recs = [r for r in with_returns if r.confidence == conf]
        if conf_recs:
            conf_wins = [r for r in conf_recs if r.return_pct > 0]
            by_confidence[conf] = {
                "count": len(conf_recs),
                "hitRate": round(len(conf_wins) / len(conf_recs) * 100, 1),
                "avgReturnPct": round(float(sum(r.return_pct for r in conf_recs)) / len(conf_recs), 2),
            }

    # By source
    by_source = {}
    for source in set(r.source or "manual" for r in with_returns):
        src_recs = [r for r in with_returns if (r.source or "manual") == source]
        if src_recs:
            src_wins = [r for r in src_recs if r.return_pct > 0]
            by_source[source] = {
                "count": len(src_recs),
                "hitRate": round(len(src_wins) / len(src_recs) * 100, 1),
                "avgReturnPct": round(float(sum(r.return_pct for r in src_recs)) / len(src_recs), 2),
            }

    # Best/worst
    sorted_by_return = sorted(with_returns, key=lambda r: float(r.return_pct), reverse=True)
    best = sorted_by_return[:5]
    worst = sorted_by_return[-5:]

    return {
        "data": {
            "totalClosed": total,
            "activeCount": active_count,
            "hitRate": hit_rate,
            "avgReturnPct": avg_return,
            "totalWins": len(wins),
            "totalLosses": len(losses),
            "byAction": by_action,
            "byConfidence": by_confidence,
            "bySource": by_source,
            "bestCalls": [
                {"id": r.id, "securityId": r.security_id, "action": r.action, "returnPct": float(r.return_pct)}
                for r in best
            ],
            "worstCalls": [
                {"id": r.id, "securityId": r.security_id, "action": r.action, "returnPct": float(r.return_pct)}
                for r in worst
            ],
        },
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


async def _compute_checkpoints(session) -> int:
    """Compute missing checkpoints for all eligible recommendations.

    Returns count of newly created checkpoints.
    """
    today = date.today()
    checkpoint_days = [30, 90, 180]

    # Get all recommendations with entry price and recommended date
    result = await session.execute(
        select(Recommendation).where(
            Recommendation.entry_price_cents.isnot(None),
            Recommendation.recommended_date.isnot(None),
        )
    )
    recs = result.scalars().all()

    # Load existing checkpoints in bulk
    existing_result = await session.execute(
        select(
            RecommendationCheckpoint.recommendation_id,
            RecommendationCheckpoint.days_elapsed,
        )
    )
    existing_set = set(existing_result.all())

    new_count = 0
    for rec in recs:
        for days in checkpoint_days:
            if (rec.id, days) in existing_set:
                continue

            check_date = rec.recommended_date + timedelta(days=days)
            if today < check_date:
                continue

            # Find closest price on or before check_date
            price_result = await session.execute(
                select(Price.close_cents)
                .where(
                    Price.security_id == rec.security_id,
                    Price.date <= check_date,
                )
                .order_by(Price.date.desc())
                .limit(1)
            )
            check_price = price_result.scalar_one_or_none()

            return_pct = None
            was_correct = None
            if check_price and rec.entry_price_cents and rec.entry_price_cents != 0:
                if rec.action == "buy":
                    return_pct = Decimal(
                        str(round((check_price - rec.entry_price_cents) / rec.entry_price_cents * 100, 4))
                    )
                elif rec.action == "sell":
                    return_pct = Decimal(
                        str(round((rec.entry_price_cents - check_price) / rec.entry_price_cents * 100, 4))
                    )
                if return_pct is not None:
                    was_correct = return_pct > 0

            checkpoint = RecommendationCheckpoint(
                recommendation_id=rec.id,
                days_elapsed=days,
                check_date=check_date,
                price_at_check_cents=check_price,
                return_pct=return_pct,
                was_correct=was_correct,
            )
            session.add(checkpoint)
            new_count += 1

    if new_count > 0:
        await session.commit()

    return new_count


def _build_period_stats(checkpoints: list[RecommendationCheckpoint]) -> dict:
    """Build win/loss stats for a list of checkpoints."""
    with_returns = [c for c in checkpoints if c.return_pct is not None]
    if not with_returns:
        return {"total": 0, "wins": 0, "winRate": None, "avgReturn": None}
    wins = [c for c in with_returns if c.was_correct]
    avg_ret = round(float(sum(c.return_pct for c in with_returns)) / len(with_returns), 2)
    return {
        "total": len(with_returns),
        "wins": len(wins),
        "winRate": round(len(wins) / len(with_returns) * 100, 1),
        "avgReturn": avg_ret,
    }


@router.get("/accuracy")
async def get_accuracy():
    """Mark-to-market accuracy for all recommendations at 30/90/180 day checkpoints."""
    async with async_session() as session:
        # Compute any missing checkpoints first
        await _compute_checkpoints(session)

        # Fetch all checkpoints with their recommendations
        result = await session.execute(
            select(RecommendationCheckpoint, Recommendation, Security)
            .join(Recommendation, RecommendationCheckpoint.recommendation_id == Recommendation.id)
            .join(Security, Recommendation.security_id == Security.id)
        )
        rows = result.all()

    # Group by period
    by_period: dict[str, list] = {"30d": [], "90d": [], "180d": []}
    by_action_period: dict[str, dict[str, list]] = {}
    all_checkpoints_flat = []

    for cp, rec, sec in rows:
        period_key = f"{cp.days_elapsed}d"
        if period_key in by_period:
            by_period[period_key].append(cp)

        action = rec.action
        if action not in by_action_period:
            by_action_period[action] = {"30d": [], "90d": [], "180d": []}
        if period_key in by_action_period[action]:
            by_action_period[action][period_key].append(cp)

        if cp.return_pct is not None:
            all_checkpoints_flat.append({
                "checkpoint": cp,
                "ticker": sec.ticker,
                "action": rec.action,
            })

    # Build aggregate stats
    checkpoints_stats = {k: _build_period_stats(v) for k, v in by_period.items()}

    by_action_stats = {}
    for action, periods in by_action_period.items():
        by_action_stats[action] = {k: _build_period_stats(v) for k, v in periods.items()}

    # Best/worst calls
    sorted_calls = sorted(all_checkpoints_flat, key=lambda x: float(x["checkpoint"].return_pct), reverse=True)
    best = sorted_calls[:5]
    worst = sorted_calls[-5:] if len(sorted_calls) >= 5 else sorted_calls

    def _call_to_dict(item):
        cp = item["checkpoint"]
        return {
            "ticker": item["ticker"],
            "action": item["action"],
            "days": cp.days_elapsed,
            "returnPct": float(cp.return_pct),
        }

    return {
        "data": {
            "checkpoints": checkpoints_stats,
            "byAction": by_action_stats,
            "bestCalls": [_call_to_dict(c) for c in best],
            "worstCalls": [_call_to_dict(c) for c in worst],
        },
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.post("/compute-checkpoints")
async def compute_checkpoints():
    """Trigger batch computation of recommendation checkpoints."""
    async with async_session() as session:
        new_count = await _compute_checkpoints(session)

    return {
        "data": {"newCheckpoints": new_count},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/{rec_id}")
async def get_recommendation(rec_id: int):
    """Get a single recommendation with current price context."""
    async with async_session() as session:
        rec = await session.get(Recommendation, rec_id)
        if not rec:
            raise HTTPException(404, "Recommendation not found")

        sec = await session.get(Security, rec.security_id)

        # Get current price for unrealized return calculation
        current_price = None
        if rec.status == "active" and rec.entry_price_cents:
            price_result = await session.execute(
                select(Price.close_cents)
                .where(Price.security_id == rec.security_id)
                .order_by(Price.date.desc())
                .limit(1)
            )
            current_price = price_result.scalar_one_or_none()

    data = _rec_to_dict(rec, sec)
    if current_price and rec.entry_price_cents:
        if rec.action == "buy":
            data["unrealizedReturnPct"] = round(
                (current_price - rec.entry_price_cents) / rec.entry_price_cents * 100, 2
            )
        elif rec.action == "sell":
            data["unrealizedReturnPct"] = round(
                (rec.entry_price_cents - current_price) / rec.entry_price_cents * 100, 2
            )
        data["currentPriceCents"] = current_price

    return {
        "data": data,
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }
