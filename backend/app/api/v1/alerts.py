"""Alert management — CRUD, evaluation, history, and rebalancing suggestions."""

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.db.engine import async_session
from app.db.models.alerts import Alert, AlertHistory
from app.db.models.securities import Security
from app.services.alert_evaluator import evaluate_all
from app.services.rebalancer import compute_rebalancing

logger = structlog.get_logger()

router = APIRouter()


class AlertCreate(BaseModel):
    type: str  # price_above, price_below, insider_activity, etc.
    security_id: int | None = None
    account_id: int | None = None
    threshold_value: float | None = None  # in cents for price alerts
    threshold_currency: str | None = None
    message: str
    expires_at: str | None = None  # ISO datetime


class AlertUpdate(BaseModel):
    threshold_value: float | None = None
    threshold_currency: str | None = None
    message: str | None = None
    expires_at: str | None = None


def _alert_to_dict(a: Alert, sec: Security | None = None) -> dict:
    return {
        "id": a.id,
        "type": a.type,
        "status": a.status,
        "securityId": a.security_id,
        "ticker": sec.ticker if sec else None,
        "securityName": sec.name if sec else None,
        "accountId": a.account_id,
        "thresholdValue": float(a.threshold_value) if a.threshold_value is not None else None,
        "thresholdCurrency": a.threshold_currency,
        "message": a.message,
        "triggeredAt": a.triggered_at.isoformat() if a.triggered_at else None,
        "dismissedAt": a.dismissed_at.isoformat() if a.dismissed_at else None,
        "expiresAt": a.expires_at.isoformat() if a.expires_at else None,
        "createdAt": a.created_at.isoformat(),
    }


def _history_to_dict(h: AlertHistory) -> dict:
    return {
        "id": h.id,
        "alertId": h.alert_id,
        "triggeredValue": float(h.triggered_value) if h.triggered_value is not None else None,
        "triggeredValueCurrency": h.triggered_value_currency,
        "snapshotData": h.snapshot_data,
        "message": h.message,
        "triggeredAt": h.triggered_at.isoformat(),
    }


@router.get("")
async def list_alerts(
    status: str | None = Query(None),
    type: str | None = Query(None, alias="type"),
    security_id: int | None = Query(None, alias="securityId"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List alert rules with filters."""
    async with async_session() as session:
        query = (
            select(Alert, Security)
            .outerjoin(Security, Alert.security_id == Security.id)
            .order_by(Alert.created_at.desc())
        )
        if status:
            query = query.where(Alert.status == status)
        if type:
            query = query.where(Alert.type == type)
        if security_id:
            query = query.where(Alert.security_id == security_id)

        count_q = select(func.count()).select_from(query.subquery())
        total = (await session.execute(count_q)).scalar_one()

        result = await session.execute(query.offset(offset).limit(limit))
        rows = result.all()

    return {
        "data": [_alert_to_dict(a, sec) for a, sec in rows],
        "pagination": {"total": total, "limit": limit, "offset": offset},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/active-count")
async def active_count():
    """Count of active and triggered alerts for sidebar badge."""
    async with async_session() as session:
        active = (await session.execute(
            select(func.count()).where(Alert.status == "active")
        )).scalar_one()
        triggered = (await session.execute(
            select(func.count()).where(Alert.status == "triggered")
        )).scalar_one()

    return {
        "data": {"active": active, "triggered": triggered, "total": active + triggered},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/history")
async def alert_history(
    alert_id: int | None = Query(None, alias="alertId"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Paginated history of triggered alerts."""
    async with async_session() as session:
        query = select(AlertHistory).order_by(AlertHistory.triggered_at.desc())
        if alert_id:
            query = query.where(AlertHistory.alert_id == alert_id)

        count_q = select(func.count()).select_from(query.subquery())
        total = (await session.execute(count_q)).scalar_one()

        result = await session.execute(query.offset(offset).limit(limit))
        rows = result.scalars().all()

    return {
        "data": [_history_to_dict(h) for h in rows],
        "pagination": {"total": total, "limit": limit, "offset": offset},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/rebalancing")
async def rebalancing_suggestions(
    mode: str = Query("minimize_tax", regex="^(minimize_tax|exact_target)$"),
):
    """Compute tax-aware rebalancing suggestions.

    Modes:
    - minimize_tax (default): prioritise tax-efficient sells (OST first,
      then losses, then smallest gains, then >10yr deemed cost).
    - exact_target: FIFO lot selection, hits exact target regardless of tax.
    """
    async with async_session() as session:
        result = await compute_rebalancing(session, mode=mode)

    def _money(cents: int, currency: str = "EUR") -> dict:
        return {"amount": cents, "currency": currency}

    def _trade_to_dict(t) -> dict:
        d: dict = {
            "action": t.action,
            "securityId": t.security_id,
            "securityName": t.security_name,
            "ticker": t.ticker,
            "accountId": t.account_id,
            "accountName": t.account_name,
            "quantity": float(t.quantity),
            "estimatedProceeds": _money(t.estimated_proceeds_cents, t.estimated_proceeds_currency),
            "estimatedProceedsEur": _money(t.estimated_proceeds_eur_cents, "EUR"),
        }
        if t.tax_impact is not None:
            d["taxImpact"] = {
                "realizedGain": _money(t.tax_impact.realized_gain_cents, "EUR"),
                "estimatedTax": _money(t.tax_impact.estimated_tax_cents, "EUR"),
                "taxRate": t.tax_impact.tax_rate,
                "usedDeemedCost": t.tax_impact.used_deemed_cost,
                "isOsakesaastotili": t.tax_impact.is_osakesaastotili,
            }
        else:
            d["taxImpact"] = None
        return d

    def _allocation_to_dict(alloc) -> dict:
        return {
            key: {"actual": entry.actual, "target": entry.target, "drift": entry.drift}
            for key, entry in alloc.items()
        }

    data: dict = {
        "currentAllocation": _allocation_to_dict(result.current_allocation),
        "suggestedTrades": [_trade_to_dict(t) for t in result.suggested_trades],
        "summary": {
            "totalSells": _money(result.summary.total_sells_eur_cents),
            "totalBuys": _money(result.summary.total_buys_eur_cents),
            "netCashFlow": _money(result.summary.net_cash_flow_eur_cents),
            "totalEstimatedTax": _money(result.summary.total_estimated_tax_eur_cents),
        },
        "mode": result.mode,
    }
    if result.message:
        data["message"] = result.message

    return {
        "data": data,
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/{alert_id}")
async def get_alert(alert_id: int):
    """Get a single alert with its history."""
    async with async_session() as session:
        alert = await session.get(Alert, alert_id)
        if not alert:
            raise HTTPException(404, "Alert not found")

        sec = await session.get(Security, alert.security_id) if alert.security_id else None

        hist_result = await session.execute(
            select(AlertHistory)
            .where(AlertHistory.alert_id == alert_id)
            .order_by(AlertHistory.triggered_at.desc())
            .limit(20)
        )
        history = hist_result.scalars().all()

    data = _alert_to_dict(alert, sec)
    data["history"] = [_history_to_dict(h) for h in history]

    return {
        "data": data,
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.post("")
async def create_alert(body: AlertCreate):
    """Create a new alert rule."""
    async with async_session() as session:
        alert = Alert(
            type=body.type,
            security_id=body.security_id,
            account_id=body.account_id,
            threshold_value=body.threshold_value,
            threshold_currency=body.threshold_currency,
            message=body.message,
            expires_at=datetime.fromisoformat(body.expires_at) if body.expires_at else None,
        )
        session.add(alert)
        await session.commit()
        await session.refresh(alert)

        sec = await session.get(Security, alert.security_id) if alert.security_id else None

    return {
        "data": _alert_to_dict(alert, sec),
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.put("/{alert_id}")
async def update_alert(alert_id: int, body: AlertUpdate):
    """Update an alert rule."""
    async with async_session() as session:
        alert = await session.get(Alert, alert_id)
        if not alert:
            raise HTTPException(404, "Alert not found")

        if body.threshold_value is not None:
            alert.threshold_value = body.threshold_value
        if body.threshold_currency is not None:
            alert.threshold_currency = body.threshold_currency
        if body.message is not None:
            alert.message = body.message
        if body.expires_at is not None:
            alert.expires_at = datetime.fromisoformat(body.expires_at)

        await session.commit()
        await session.refresh(alert)
        sec = await session.get(Security, alert.security_id) if alert.security_id else None

    return {
        "data": _alert_to_dict(alert, sec),
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.delete("/{alert_id}")
async def delete_alert(alert_id: int):
    """Delete an alert rule."""
    async with async_session() as session:
        alert = await session.get(Alert, alert_id)
        if not alert:
            raise HTTPException(404, "Alert not found")
        await session.delete(alert)
        await session.commit()

    return {
        "data": {"deleted": True, "id": alert_id},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.post("/{alert_id}/dismiss")
async def dismiss_alert(alert_id: int):
    """Dismiss a triggered alert."""
    async with async_session() as session:
        alert = await session.get(Alert, alert_id)
        if not alert:
            raise HTTPException(404, "Alert not found")

        alert.status = "dismissed"
        alert.dismissed_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(alert)
        sec = await session.get(Security, alert.security_id) if alert.security_id else None

    return {
        "data": _alert_to_dict(alert, sec),
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.post("/{alert_id}/reactivate")
async def reactivate_alert(alert_id: int):
    """Reactivate a dismissed or triggered alert."""
    async with async_session() as session:
        alert = await session.get(Alert, alert_id)
        if not alert:
            raise HTTPException(404, "Alert not found")

        alert.status = "active"
        alert.triggered_at = None
        alert.dismissed_at = None
        await session.commit()
        await session.refresh(alert)
        sec = await session.get(Security, alert.security_id) if alert.security_id else None

    return {
        "data": _alert_to_dict(alert, sec),
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.post("/evaluate")
async def evaluate_alerts():
    """Manually trigger evaluation of all active alerts."""
    triggered = await evaluate_all()
    return {
        "data": {
            "evaluated": True,
            "triggered": triggered,
            "triggeredCount": len(triggered),
        },
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }
