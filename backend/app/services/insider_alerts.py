"""Insider alert detection — checks for cluster buying and trades on held securities.

Called after insider/congress pipelines run. Sends Telegram notifications
for actionable signals.
"""

from __future__ import annotations

from datetime import date, timedelta

import structlog
from sqlalchemy import case, func, select

from app.db.engine import async_session
from app.db.models.fundamentals import SecurityFundamentals
from app.db.models.insider import CongressTrade, InsiderTrade
from app.db.models.securities import Security
from app.db.models.transactions import Transaction
from app.services import telegram

logger = structlog.get_logger()

CLUSTER_WINDOW_DAYS = 30
CLUSTER_MIN_INSIDERS = 3

# Only alert on trades disclosed in the last N days (avoid re-alerting old data)
LOOKBACK_DAYS = 3


async def _get_held_security_ids() -> set[int]:
    """Get security IDs for all currently held positions."""
    async with async_session() as session:
        result = await session.execute(
            select(
                Transaction.security_id,
                func.sum(
                    case(
                        (Transaction.type.in_(["buy", "transfer_in"]), Transaction.quantity),
                        else_=-Transaction.quantity,
                    )
                ).label("net_qty"),
            )
            .where(Transaction.type.in_(["buy", "sell", "transfer_in", "transfer_out"]))
            .group_by(Transaction.security_id)
            .having(
                func.sum(
                    case(
                        (Transaction.type.in_(["buy", "transfer_in"]), Transaction.quantity),
                        else_=-Transaction.quantity,
                    )
                )
                > 0
            )
        )
        return {row.security_id for row in result.all()}


async def check_and_notify():
    """Main entry point: check for insider signals and send Telegram alerts.

    1. Cluster buying: 3+ distinct insiders buying same security within 30 days
    2. Insider trades on held securities (new trades disclosed recently)
    3. Congress trades on held securities (new trades disclosed recently)
    """
    logger.info("insider_alerts.check_start")

    held_ids = await _get_held_security_ids()
    if not held_ids:
        logger.info("insider_alerts.no_holdings")
        return

    today = date.today()
    lookback = today - timedelta(days=LOOKBACK_DAYS)

    await _check_cluster_buying(today, held_ids)
    await _check_held_insider_trades(today, lookback, held_ids)
    await _check_held_congress_trades(today, lookback, held_ids)

    logger.info("insider_alerts.check_complete")


async def _check_cluster_buying(today: date, held_ids: set[int]):
    """Detect cluster buying across ALL securities (not just held)."""
    window_start = today - timedelta(days=CLUSTER_WINDOW_DAYS)

    async with async_session() as session:
        # Find securities with 3+ distinct insider buyers in the window
        # Also sum total value of those buys
        result = await session.execute(
            select(
                InsiderTrade.security_id,
                func.count(func.distinct(InsiderTrade.insider_name)).label("insider_count"),
                func.coalesce(func.sum(InsiderTrade.value_cents), 0).label("total_value_cents"),
            )
            .where(
                InsiderTrade.trade_type == "buy",
                InsiderTrade.trade_date >= window_start,
            )
            .group_by(InsiderTrade.security_id)
            .having(
                func.count(func.distinct(InsiderTrade.insider_name)) >= CLUSTER_MIN_INSIDERS
            )
        )
        clusters = result.all()

        if not clusters:
            return

        # Fetch security details, market cap, and FX info
        sec_ids = [c.security_id for c in clusters]
        sec_result = await session.execute(
            select(Security).where(Security.id.in_(sec_ids))
        )
        sec_map = {s.id: s for s in sec_result.scalars().all()}

        # Fetch market caps from fundamentals
        fund_result = await session.execute(
            select(
                SecurityFundamentals.security_id,
                SecurityFundamentals.market_cap_cents,
            ).where(SecurityFundamentals.security_id.in_(sec_ids))
        )
        mcap_map = {row.security_id: row.market_cap_cents for row in fund_result.all()}

        # Get the actual insiders for each cluster
        cluster_data = []
        for c in clusters:
            sec = sec_map.get(c.security_id)
            if not sec:
                continue

            insider_result = await session.execute(
                select(
                    InsiderTrade.insider_name,
                    InsiderTrade.role,
                    InsiderTrade.value_cents,
                    InsiderTrade.currency,
                )
                .where(
                    InsiderTrade.security_id == c.security_id,
                    InsiderTrade.trade_type == "buy",
                    InsiderTrade.trade_date >= window_start,
                )
                .order_by(InsiderTrade.value_cents.desc().nullslast())
                .limit(10)
            )
            insiders = []
            seen_names = set()
            for row in insider_result.all():
                if row.insider_name not in seen_names:
                    seen_names.add(row.insider_name)
                    insiders.append({
                        "name": row.insider_name,
                        "role": row.role,
                        "valueCents": row.value_cents,
                        "currency": row.currency,
                    })

            jr = await session.execute(
                select(InsiderTrade.jurisdiction)
                .where(
                    InsiderTrade.security_id == c.security_id,
                    InsiderTrade.trade_type == "buy",
                    InsiderTrade.trade_date >= window_start,
                )
                .limit(1)
            )
            jr_row = jr.scalar_one_or_none()

            # Flag if it's a held security
            is_held = c.security_id in held_ids
            ticker_display = sec.ticker
            if is_held:
                ticker_display = f"{sec.ticker} (HELD)"

            # Compute % of market cap
            market_cap = mcap_map.get(c.security_id)
            total_value = c.total_value_cents
            pct_of_market_cap = None
            if market_cap and market_cap > 0 and total_value:
                pct_of_market_cap = round((total_value / market_cap) * 100, 4)

            cluster_data.append({
                "ticker": ticker_display,
                "securityName": sec.name,
                "insiderCount": c.insider_count,
                "insiders": insiders,
                "jurisdiction": jr_row or "",
                "totalValueCents": total_value,
                "currency": sec.currency,
                "pctOfMarketCap": pct_of_market_cap,
            })

    if cluster_data:
        logger.info("insider_alerts.cluster_buying", count=len(cluster_data))
        await telegram.notify_insider_cluster_buying(cluster_data)


async def _check_held_insider_trades(
    today: date, lookback: date, held_ids: set[int]
):
    """Find new insider trades on held securities disclosed recently."""
    async with async_session() as session:
        result = await session.execute(
            select(InsiderTrade, Security)
            .join(Security, InsiderTrade.security_id == Security.id)
            .where(
                InsiderTrade.security_id.in_(held_ids),
                InsiderTrade.disclosure_date >= lookback,
                InsiderTrade.trade_type.in_(["buy", "sell"]),
            )
            .order_by(InsiderTrade.trade_date.desc())
            .limit(20)
        )
        rows = result.all()

    if not rows:
        return

    trades = []
    for t, sec in rows:
        trades.append({
            "ticker": sec.ticker,
            "securityName": sec.name,
            "insiderName": t.insider_name,
            "role": t.role,
            "tradeType": t.trade_type,
            "shares": str(t.shares),
            "valueCents": t.value_cents,
            "currency": t.currency,
            "source": "insider",
        })

    logger.info("insider_alerts.held_insider_trades", count=len(trades))
    await telegram.notify_insider_held_trades(trades)


async def _check_held_congress_trades(
    today: date, lookback: date, held_ids: set[int]
):
    """Find new congress trades on held securities disclosed recently."""
    async with async_session() as session:
        result = await session.execute(
            select(CongressTrade, Security)
            .join(Security, CongressTrade.security_id == Security.id)
            .where(
                CongressTrade.security_id.in_(held_ids),
                CongressTrade.disclosure_date >= lookback,
            )
            .order_by(CongressTrade.trade_date.desc())
            .limit(20)
        )
        rows = result.all()

    if not rows:
        return

    trades = []
    for t, sec in rows:
        trades.append({
            "ticker": sec.ticker,
            "securityName": sec.name,
            "memberName": t.member_name,
            "role": f"{t.chamber} ({t.party})",
            "tradeType": t.trade_type,
            "shares": "",
            "valueCents": t.amount_range_high_cents,
            "currency": t.currency,
            "source": "congress",
        })

    logger.info("insider_alerts.held_congress_trades", count=len(trades))
    await telegram.notify_insider_held_trades(trades)
