"""Weekly digest — composes and sends a Monday morning Telegram summary.

Privacy-safe: no absolute portfolio values, only % changes, counts, and tickers.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import structlog
from sqlalchemy import func, select

from app.db.engine import async_session
from app.db.models.dividends import DividendEvent
from app.db.models.insider import InsiderTrade
from app.db.models.recommendations import Recommendation
from app.db.models.securities import Security
from app.services import notifier, telegram

logger = structlog.get_logger()


# Plain-language regime blurbs used in the Macro section.
_REGIME_BLURB = {
    "expansion": "broad growth; cyclicals and equities favoured",
    "recovery":  "growth improving from a low; cyclicals turning up",
    "slowdown":  "growth moderating; defensive tilt, quality, duration",
    "recession": "contracting growth; capital preservation, long duration, gold",
}


async def compose_and_send_digest():
    """Build and send the weekly digest message."""
    logger.info("weekly_digest.start")

    today = date.today()
    week_ago = today - timedelta(days=7)
    week_ahead = today + timedelta(days=7)

    sections = []
    sections.append("<b>Weekly Digest</b>")
    sections.append(
        "<i>New/changed recommendations, insider activity, upcoming "
        "dividends, and macro regime from Bloomvalley — sent every Monday 08:00.</i>"
    )
    sections.append("")

    # 1. Recommendations — counts + new-this-week tickers by action.
    rec_section = await _recommendations_summary(week_ago)
    if rec_section:
        sections.append(rec_section)

    # 2. Upcoming dividends (next 7 days) — already listed tickers.
    div_section = await _upcoming_dividends(today, week_ahead)
    if div_section:
        sections.append(div_section)

    # 3. Insider activity (last 7 days) — counts + top trades + cluster tickers.
    insider_section = await _insider_summary(week_ago, today)
    if insider_section:
        sections.append(insider_section)

    # 4. Macro regime with a plain-language blurb.
    macro_section = await _macro_regime()
    if macro_section:
        sections.append(macro_section)

    if len(sections) <= 3:
        sections.append("<i>No notable activity this week.</i>")

    text = "\n".join(sections)
    ok = await notifier.send(text, force=True)
    logger.info("weekly_digest.complete", sent=ok)
    return ok


async def _recommendations_summary(week_ago: date) -> str | None:
    """Aggregate counts of active recommendations, plus new-this-week tickers by action."""
    async with async_session() as session:
        # Aggregate counts (all active).
        result = await session.execute(
            select(Recommendation.action, func.count().label("cnt"))
            .where(Recommendation.status == "active")
            .group_by(Recommendation.action)
        )
        rows = result.all()

        # New recommendations in the last 7 days.
        new_result = await session.execute(
            select(Recommendation.action, Security.ticker)
            .join(Security, Recommendation.security_id == Security.id)
            .where(
                Recommendation.status == "active",
                Recommendation.recommended_date >= week_ago,
            )
            .order_by(Recommendation.recommended_date.desc(), Recommendation.id.desc())
        )
        new_rows = new_result.all()

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
        f"<b>Recommendations</b> ({total} active)",
        f"  {' | '.join(parts)}",
    ]

    # Group new tickers by action; only show actionable ones (BUY / SELL).
    # HOLD and WAIT are non-actions and would flood the section.
    by_action: dict[str, list[str]] = {}
    for row in new_rows:
        by_action.setdefault(row.action, []).append(row.ticker)

    actionable = False
    for action in ["buy", "sell"]:
        tickers = by_action.get(action, [])
        if not tickers:
            continue
        actionable = True
        shown = tickers[:8]
        more = f" +{len(tickers) - 8}" if len(tickers) > 8 else ""
        lines.append(
            f"  New {action.upper()} ({len(tickers)}): "
            f"{', '.join(telegram._escape(t) for t in shown)}{more}"
        )

    # Bare hold/wait counts so the reader knows the swarm was active.
    hw = by_action.get("hold", []) or by_action.get("wait", [])
    hold_n = len(by_action.get("hold", []))
    wait_n = len(by_action.get("wait", []))
    if hold_n or wait_n:
        parts_hw = []
        if hold_n:
            parts_hw.append(f"{hold_n} HOLD")
        if wait_n:
            parts_hw.append(f"{wait_n} WAIT")
        lines.append(f"  (also {' / '.join(parts_hw)} — no action)")

    if not actionable and hold_n == 0 and wait_n == 0:
        lines.append("  <i>No new recommendations this week.</i>")

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
    """Summarize insider activity in the last 7 days.

    Returns a section with:
      - aggregate counts (significant trades + cluster-buying signals)
      - top 5 significant trades by |value| with ticker + role + direction + $ value
      - up to 5 cluster-buy tickers (3+ distinct buyers in the last 30 days)
    """
    async with async_session() as session:
        # Count significant trades in the disclosure-date window.
        sig_count = (await session.execute(
            select(func.count())
            .where(
                InsiderTrade.disclosure_date >= week_ago,
                InsiderTrade.is_significant.is_(True),
            )
        )).scalar_one()

        # Top-5 significant trades by |value_cents|, most recent first as tiebreak.
        top_trades = (await session.execute(
            select(InsiderTrade, Security)
            .join(Security, InsiderTrade.security_id == Security.id)
            .where(
                InsiderTrade.disclosure_date >= week_ago,
                InsiderTrade.is_significant.is_(True),
                InsiderTrade.value_cents.isnot(None),
            )
            .order_by(func.abs(InsiderTrade.value_cents).desc(),
                      InsiderTrade.disclosure_date.desc())
            .limit(5)
        )).all()

        # Cluster tickers (3+ distinct buyers in last 30 days).
        cluster_rows = (await session.execute(
            select(Security.ticker,
                   func.count(func.distinct(InsiderTrade.insider_name)).label("buyers"))
            .join(InsiderTrade, InsiderTrade.security_id == Security.id)
            .where(
                InsiderTrade.trade_type == "buy",
                InsiderTrade.trade_date >= today - timedelta(days=30),
            )
            .group_by(Security.ticker)
            .having(func.count(func.distinct(InsiderTrade.insider_name)) >= 3)
            .order_by(func.count(func.distinct(InsiderTrade.insider_name)).desc())
            .limit(8)
        )).all()

    if sig_count == 0 and not cluster_rows:
        return None

    parts = []
    if sig_count > 0:
        parts.append(f"{sig_count} significant trade{'s' if sig_count != 1 else ''}")
    if cluster_rows:
        parts.append(f"{len(cluster_rows)} cluster signal{'s' if len(cluster_rows) != 1 else ''}")

    lines = [f"<b>Insider Activity</b> (last 7d)", f"  {' | '.join(parts)}"]

    if top_trades:
        lines.append("  Top significant trades:")
        for trade, sec in top_trades:
            direction = trade.trade_type.upper()
            role = (trade.role or "?").strip() or "?"
            value_str = _fmt_value(trade.value_cents, trade.currency)
            lines.append(
                f"    {telegram._escape(sec.ticker)} — "
                f"{telegram._escape(trade.insider_name)} ({telegram._escape(role)}, {direction}) "
                f"— {value_str}"
            )

    if cluster_rows:
        shown = [f"{r.ticker} ({r.buyers})" for r in cluster_rows[:5]]
        more = f" +{len(cluster_rows) - 5}" if len(cluster_rows) > 5 else ""
        lines.append(
            "  Cluster buys (3+ insiders, 30d): "
            + ", ".join(telegram._escape(s) for s in shown)
            + more
        )

    return "\n".join(lines)


async def _macro_regime() -> str | None:
    """Get the latest macro regime classification, with plain-language blurb."""
    try:
        from app.api.v1.macro import macro_regime
        resp = await macro_regime()
        data = resp.get("data", {})
        regime = data.get("regime")
        confidence = data.get("confidence", "")
        if regime:
            blurb = _REGIME_BLURB.get(regime, "")
            line = (
                f"  Regime: {telegram._escape(regime)} "
                f"({telegram._escape(confidence)} confidence)"
            )
            if blurb:
                line += f" — {telegram._escape(blurb)}"
            return f"<b>Macro</b>\n{line}"
    except Exception as e:
        logger.warning("weekly_digest.macro_failed", error=str(e))

    return None


def _fmt_value(value_cents: int | None, currency: str) -> str:
    """Human-readable trade value: $1.2M / €340k / £8k. Returns '—' if missing."""
    if value_cents is None:
        return "—"
    val = abs(value_cents) / 100.0
    sign = "-" if value_cents < 0 else ""
    sym = {"USD": "$", "EUR": "€", "GBP": "£", "SEK": "kr", "NOK": "kr", "DKK": "kr"}.get(
        (currency or "").upper(), (currency or "").upper() + " "
    )
    if val >= 1_000_000:
        return f"{sign}{sym}{val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"{sign}{sym}{val / 1_000:.0f}k"
    return f"{sign}{sym}{val:.0f}"
