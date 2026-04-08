"""Deployment plan endpoints — capital deployment timeline management."""

from datetime import date, datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func

from app.db.engine import async_session
from app.db.models.deployment_plans import DeploymentPlan, DeploymentTranche

logger = structlog.get_logger()

router = APIRouter()


# ── Pydantic Models ──


class TrancheCreate(BaseModel):
    quarterLabel: str
    plannedDate: date
    amountCents: int
    currency: str = "EUR"
    coreAllocationPct: int = 60
    convictionAllocationPct: int = 30
    cashBufferPct: int = 10
    candidateTickers: Optional[list] = None
    conditionalTriggers: Optional[list] = None


class PlanCreate(BaseModel):
    name: str
    startDate: date
    endDate: date
    totalAmountCents: int
    currency: str = "EUR"
    strategyNotes: Optional[str] = None
    macroRegimeAtCreation: Optional[str] = None
    nextReviewDate: Optional[date] = None
    tranches: list[TrancheCreate] = []


class PlanUpdate(BaseModel):
    name: Optional[str] = None
    strategyNotes: Optional[str] = None
    nextReviewDate: Optional[date] = None
    status: Optional[str] = None


class TrancheUpdate(BaseModel):
    candidateTickers: Optional[list] = None
    conditionalTriggers: Optional[list] = None
    coreAllocationPct: Optional[int] = None
    convictionAllocationPct: Optional[int] = None
    cashBufferPct: Optional[int] = None
    status: Optional[str] = None
    amountCents: Optional[int] = None
    plannedDate: Optional[date] = None
    executedAmountCents: Optional[int] = None
    executionNotes: Optional[str] = None


class TrancheComplete(BaseModel):
    executedAmountCents: int
    executionNotes: Optional[str] = None


# ── Helpers ──


def _plan_to_dict(plan: DeploymentPlan) -> dict:
    tranches = []
    deployed = 0
    for t in plan.tranches:
        if t.executed_amount_cents:
            deployed += t.executed_amount_cents
        tranches.append(_tranche_to_dict(t))

    return {
        "id": plan.id,
        "name": plan.name,
        "status": plan.status,
        "startDate": plan.start_date.isoformat(),
        "endDate": plan.end_date.isoformat(),
        "totalAmountCents": plan.total_amount_cents,
        "deployedAmountCents": deployed,
        "currency": plan.currency,
        "strategyNotes": plan.strategy_notes,
        "macroRegimeAtCreation": plan.macro_regime_at_creation,
        "nextReviewDate": plan.next_review_date.isoformat() if plan.next_review_date else None,
        "createdAt": plan.created_at.isoformat() if plan.created_at else None,
        "updatedAt": plan.updated_at.isoformat() if plan.updated_at else None,
        "tranches": tranches,
    }


def _tranche_to_dict(t: DeploymentTranche) -> dict:
    return {
        "id": t.id,
        "planId": t.plan_id,
        "quarterLabel": t.quarter_label,
        "plannedDate": t.planned_date.isoformat(),
        "amountCents": t.amount_cents,
        "currency": t.currency,
        "coreAllocationPct": t.core_allocation_pct,
        "convictionAllocationPct": t.conviction_allocation_pct,
        "cashBufferPct": t.cash_buffer_pct,
        "candidateTickers": t.candidate_tickers,
        "conditionalTriggers": t.conditional_triggers,
        "status": t.status,
        "executedDate": t.executed_date.isoformat() if t.executed_date else None,
        "executedAmountCents": t.executed_amount_cents,
        "executionNotes": t.execution_notes,
        "createdAt": t.created_at.isoformat() if t.created_at else None,
    }


# ── Endpoints ──


@router.get("/current")
async def get_current_plan():
    """Get the active deployment plan with all tranches."""
    async with async_session() as session:
        result = await session.execute(
            select(DeploymentPlan)
            .where(DeploymentPlan.status == "active")
            .order_by(DeploymentPlan.created_at.desc())
            .limit(1)
        )
        plan = result.scalar_one_or_none()

    if not plan:
        return {
            "data": None,
            "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
        }

    # Eagerly load tranches
    async with async_session() as session:
        result = await session.execute(
            select(DeploymentPlan)
            .where(DeploymentPlan.id == plan.id)
        )
        plan = result.scalar_one()
        await session.refresh(plan, ["tranches"])

    return {
        "data": _plan_to_dict(plan),
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("")
async def list_plans(
    status: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=50),
):
    """List deployment plans."""
    async with async_session() as session:
        query = select(DeploymentPlan).order_by(DeploymentPlan.created_at.desc())
        if status:
            query = query.where(DeploymentPlan.status == status)
        query = query.limit(limit)

        result = await session.execute(query)
        plans = result.scalars().all()

        data = []
        for plan in plans:
            await session.refresh(plan, ["tranches"])
            data.append(_plan_to_dict(plan))

    return {
        "data": data,
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.post("")
async def create_plan(body: PlanCreate):
    """Create a new deployment plan. Auto-supersedes any existing active plan."""
    async with async_session() as session:
        # Supersede existing active plans
        result = await session.execute(
            select(DeploymentPlan).where(DeploymentPlan.status == "active")
        )
        for old_plan in result.scalars().all():
            old_plan.status = "superseded"

        plan = DeploymentPlan(
            name=body.name,
            status="active",
            start_date=body.startDate,
            end_date=body.endDate,
            total_amount_cents=body.totalAmountCents,
            currency=body.currency,
            strategy_notes=body.strategyNotes,
            macro_regime_at_creation=body.macroRegimeAtCreation,
            next_review_date=body.nextReviewDate,
        )
        session.add(plan)
        await session.flush()

        for t in body.tranches:
            tranche = DeploymentTranche(
                plan_id=plan.id,
                quarter_label=t.quarterLabel,
                planned_date=t.plannedDate,
                amount_cents=t.amountCents,
                currency=t.currency,
                core_allocation_pct=t.coreAllocationPct,
                conviction_allocation_pct=t.convictionAllocationPct,
                cash_buffer_pct=t.cashBufferPct,
                candidate_tickers=t.candidateTickers,
                conditional_triggers=t.conditionalTriggers,
            )
            session.add(tranche)

        await session.commit()
        await session.refresh(plan, ["tranches"])

    return {
        "data": _plan_to_dict(plan),
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.put("/{plan_id}")
async def update_plan(plan_id: int, body: PlanUpdate):
    """Update plan metadata."""
    async with async_session() as session:
        plan = await session.get(DeploymentPlan, plan_id)
        if not plan:
            raise HTTPException(404, "Plan not found")

        if body.name is not None:
            plan.name = body.name
        if body.strategyNotes is not None:
            plan.strategy_notes = body.strategyNotes
        if body.nextReviewDate is not None:
            plan.next_review_date = body.nextReviewDate
        if body.status is not None:
            plan.status = body.status

        await session.commit()
        await session.refresh(plan, ["tranches"])

    return {
        "data": _plan_to_dict(plan),
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.put("/{plan_id}/tranches/{tranche_id}")
async def update_tranche(plan_id: int, tranche_id: int, body: TrancheUpdate):
    """Update a specific tranche."""
    async with async_session() as session:
        tranche = await session.get(DeploymentTranche, tranche_id)
        if not tranche or tranche.plan_id != plan_id:
            raise HTTPException(404, "Tranche not found")

        if body.candidateTickers is not None:
            tranche.candidate_tickers = body.candidateTickers
        if body.conditionalTriggers is not None:
            tranche.conditional_triggers = body.conditionalTriggers
        if body.coreAllocationPct is not None:
            tranche.core_allocation_pct = body.coreAllocationPct
        if body.convictionAllocationPct is not None:
            tranche.conviction_allocation_pct = body.convictionAllocationPct
        if body.cashBufferPct is not None:
            tranche.cash_buffer_pct = body.cashBufferPct
        if body.status is not None:
            tranche.status = body.status
        if body.amountCents is not None:
            tranche.amount_cents = body.amountCents
        if body.plannedDate is not None:
            tranche.planned_date = body.plannedDate
        if body.executedAmountCents is not None:
            tranche.executed_amount_cents = body.executedAmountCents
        if body.executionNotes is not None:
            tranche.execution_notes = body.executionNotes

        await session.commit()

    return {"data": _tranche_to_dict(tranche)}


@router.put("/{plan_id}/tranches/{tranche_id}/complete")
async def complete_tranche(plan_id: int, tranche_id: int, body: TrancheComplete):
    """Mark a tranche as completed."""
    async with async_session() as session:
        tranche = await session.get(DeploymentTranche, tranche_id)
        if not tranche or tranche.plan_id != plan_id:
            raise HTTPException(404, "Tranche not found")

        tranche.status = "completed"
        tranche.executed_date = date.today()
        tranche.executed_amount_cents = body.executedAmountCents
        tranche.execution_notes = body.executionNotes

        await session.commit()

    return {"data": _tranche_to_dict(tranche)}
