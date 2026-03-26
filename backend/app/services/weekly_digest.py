"""Weekly digest — composes and sends a Monday morning Telegram summary.

Privacy-safe: no absolute portfolio values, only % changes, counts, and tickers.
"""

from __future__ import annotations

from datetime import date, timedelta

import structlog
from sqlalchemy import func, select

from app.db.engine import async_session
from app.db.models.dividends import DividendEvent
from app.db.models.insider import InsiderTrade
from app.db.models.recommendations import Recommendation
from app.db.models.securities import Security
from app.services import telegram

logger = structlog.get_logger()


async def compose_and_send_digest():
    """Build and send the weekly digest message."""
    logger.info("weekly_digest.start")

    today = date.today()
    week_ago = today - timedelta(days=7)
    week_ahead = today + timedelta(days=7)

    sections = []
    sections.append("<b>Weekly Digest</b>")
    sections.append("")

    # 1. Recommendations summary
    rec_section = await _recommendations_summary()
    if rec_section:
        sections.append(rec_section)

    # 2. Upcoming dividends (next 7 days)
    div_section = await _upcoming_dividends(today, week_ahead)
    if div_section:
        sections.append(div_section)

    # 3. Insider activity (last 7 days)
    insider_section = await _insider_summary(week_ago, today)
    if insider_section:
        sections.append(insider_section)

    # 4. Macro regime (latest)
    macro_section = await _macro_regime()
    if macro_section:
        sections.append(macro_section)

    if len(sections) <= 2:
        sections.append("<i>No notable activity this week.</i>")

    text = "\n".join(sections)
    ok = await telegram.send(text, force=True)
    logger.info("weekly_digest.complete", sent=ok)
    return ok


async def _recommendations_summary() -> str | None:
    """Count active recommendations by action."""
    async with async_session() as session:
        result = await session.execute(
            select(
                Recommendation.action,
                func.count().label("cnt"),
            )
            .where(Recommendation.status == "active")
            .group_by(Recommendation.action)
        )
        rows = result.all()

    if not rows:
        return None

    counts = {row.action: row.cnt for row in rows}
    parts = []
    for action in ["buy", "sell", "hold", "wait"]:
        cnt = counts.get(action, 0)
        if cnt > 0:
            parts.append(f"{cnt} {action.upper()}")

    total = sum(counts.values())
    lines = [
        "<b>Recommendations</b>",
        f"  {' | '.join(parts)} ({total} active)",
    ]
    return "\n".join(lines)


async def _upcoming_dividends(today: date, week_ahead: date) -> str | None:
    """List dividend ex-dates in the next 7 days for held securities."""
    async with async_session() as session:
        result = await session.execute(
            select(DividendEvent, Security)
            .join(Security, DividendEvent.security_id == Security.id)
            .where(
                DividendEvent.ex_date >= today,
                DividendEvent.ex_date <= week_ahead,
            )
            .order_by(DividendEvent.ex_date)
        )
        rows = result.all()

    if not rows:
        return None

    lines = ["<b>Dividends This Week</b>"]
    for ev, sec in rows[:8]:
        day_name = ev.ex_date.strftime("%a")
        lines.append(f"  {telegram._escape(sec.ticker)} (ex {day_name} {ev.ex_date.strftime('%d %b')})")

    if len(rows) > 8:
        lines.append(f"  ... and {len(rows) - 8} more")

    return "\n".join(lines)


async def _insider_summary(week_ago: date, today: date) -> str | None:
    """Summarize insider activity in the last 7 days."""
    async with async_session() as session:
        # Count significant trades
        sig_count = (await session.execute(
            select(func.count())
            .where(
                InsiderTrade.disclosure_date >= week_ago,
                InsiderTrade.is_significant.is_(True),
            )
        )).scalar_one()

        # Count cluster buying signals (3+ distinct buyers per security in last 30 days)
        cluster_result = await session.execute(
            select(func.count())
            .select_from(
                select(InsiderTrade.security_id)
                .where(
                    InsiderTrade.trade_type == "buy",
                    InsiderTrade.trade_date >= today - timedelta(days=30),
                )
                .group_by(InsiderTrade.security_id)
                .having(func.count(func.distinct(InsiderTrade.insider_name)) >= 3)
                .subquery()
            )
        )
        cluster_count = cluster_result.scalar_one()

    if sig_count == 0 and cluster_count == 0:
        return None

    parts = []
    if sig_count > 0:
        parts.append(f"{sig_count} significant trade{'s' if sig_count != 1 else ''}")
    if cluster_count > 0:
        parts.append(f"{cluster_count} cluster signal{'s' if cluster_count != 1 else ''}")

    return f"<b>Insider Activity</b>\n  {' | '.join(parts)}"


async def _macro_regime() -> str | None:
    """Get the latest macro regime classification."""
    try:
        from app.api.v1.macro import macro_regime
        resp = await macro_regime()
        data = resp.get("data", {})
        regime = data.get("regime")
        confidence = data.get("confidence", "")
        if regime:
            return f"<b>Macro</b>\n  Regime: {telegram._escape(regime)} ({telegram._escape(confidence)})"
    except Exception as e:
        logger.warning("weekly_digest.macro_failed", error=str(e))

    return None
