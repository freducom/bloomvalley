"""Alert evaluation engine — checks all active alerts against current data."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import structlog
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.db.engine import async_session
from app.db.models.alerts import Alert, AlertHistory
from app.db.models.insider import InsiderTrade
from app.db.models.prices import Price
from app.db.models.recommendations import Recommendation

logger = structlog.get_logger()


async def evaluate_all() -> list[dict]:
    """Run all alert evaluations. Returns list of newly triggered alerts."""
    triggered = []
    triggered += await _evaluate_price_alerts()
    triggered += await _evaluate_insider_alerts()
    triggered += await _evaluate_recommendation_expiry()
    return triggered


async def _evaluate_price_alerts() -> list[dict]:
    """Check price_above and price_below alerts."""
    triggered = []
    async with async_session() as session:
        result = await session.execute(
            select(Alert).where(
                Alert.status == "active",
                Alert.type.in_(["price_above", "price_below"]),
                Alert.security_id.isnot(None),
            )
        )
        alerts = result.scalars().all()
        if not alerts:
            return []

        security_ids = list({a.security_id for a in alerts})
        # Get latest prices
        prices: dict[int, int] = {}
        for sid in security_ids:
            price_result = await session.execute(
                select(Price.close_cents)
                .where(Price.security_id == sid)
                .order_by(Price.date.desc())
                .limit(1)
            )
            p = price_result.scalar_one_or_none()
            if p is not None:
                prices[sid] = p

        now = datetime.now(timezone.utc)
        for alert in alerts:
            if alert.security_id not in prices or alert.threshold_value is None:
                continue
            current = prices[alert.security_id]
            threshold = int(alert.threshold_value)

            should_trigger = False
            if alert.type == "price_above" and current >= threshold:
                should_trigger = True
            elif alert.type == "price_below" and current <= threshold:
                should_trigger = True

            if should_trigger:
                alert.status = "triggered"
                alert.triggered_at = now
                history = AlertHistory(
                    alert_id=alert.id,
                    triggered_value=Decimal(str(current)),
                    triggered_value_currency=alert.threshold_currency,
                    message=f"Price {'above' if alert.type == 'price_above' else 'below'} threshold: {current} cents vs {threshold} cents",
                    triggered_at=now,
                )
                session.add(history)
                triggered.append({
                    "alertId": alert.id,
                    "type": alert.type,
                    "securityId": alert.security_id,
                    "message": history.message,
                })

        await session.commit()
    return triggered


async def _evaluate_insider_alerts() -> list[dict]:
    """Check for recent insider activity on watched securities."""
    triggered = []
    async with async_session() as session:
        result = await session.execute(
            select(Alert).where(
                Alert.status == "active",
                Alert.type == "insider_activity",
                Alert.security_id.isnot(None),
            )
        )
        alerts = result.scalars().all()
        if not alerts:
            return []

        cutoff = date.today() - timedelta(days=7)
        now = datetime.now(timezone.utc)

        for alert in alerts:
            trade_result = await session.execute(
                select(func.count()).where(
                    InsiderTrade.security_id == alert.security_id,
                    InsiderTrade.trade_date >= cutoff,
                )
            )
            count = trade_result.scalar_one()
            if count > 0:
                alert.status = "triggered"
                alert.triggered_at = now
                history = AlertHistory(
                    alert_id=alert.id,
                    triggered_value=Decimal(str(count)),
                    message=f"{count} insider trade(s) in last 7 days",
                    snapshot_data={"trade_count": count, "days_lookback": 7},
                    triggered_at=now,
                )
                session.add(history)
                triggered.append({
                    "alertId": alert.id,
                    "type": "insider_activity",
                    "securityId": alert.security_id,
                    "message": history.message,
                })

        await session.commit()
    return triggered


async def _evaluate_recommendation_expiry() -> list[dict]:
    """Check for recommendations approaching expiry."""
    triggered = []
    async with async_session() as session:
        result = await session.execute(
            select(Alert).where(
                Alert.status == "active",
                Alert.type == "recommendation_expiry",
            )
        )
        alerts = result.scalars().all()
        if not alerts:
            return []

        # Find active recommendations expiring within 7 days
        cutoff = date.today() + timedelta(days=7)
        rec_result = await session.execute(
            select(Recommendation).where(
                Recommendation.status == "active",
                Recommendation.expiry_date.isnot(None),
                Recommendation.expiry_date <= cutoff,
            )
        )
        expiring = rec_result.scalars().all()
        if not expiring:
            return []

        now = datetime.now(timezone.utc)
        expiring_ids = {r.security_id for r in expiring}
        expiring_map = {r.security_id: r for r in expiring}

        for alert in alerts:
            # If alert has security_id, check only that security; otherwise check all
            check_ids = [alert.security_id] if alert.security_id else list(expiring_ids)
            for sid in check_ids:
                if sid in expiring_ids:
                    rec = expiring_map[sid]
                    alert.status = "triggered"
                    alert.triggered_at = now
                    history = AlertHistory(
                        alert_id=alert.id,
                        message=f"Recommendation #{rec.id} ({rec.action} {rec.confidence}) expiring {rec.expiry_date.isoformat()}",
                        snapshot_data={"recommendation_id": rec.id, "expiry_date": rec.expiry_date.isoformat()},
                        triggered_at=now,
                    )
                    session.add(history)
                    triggered.append({
                        "alertId": alert.id,
                        "type": "recommendation_expiry",
                        "securityId": sid,
                        "message": history.message,
                    })
                    break  # One trigger per alert

        await session.commit()
    return triggered
