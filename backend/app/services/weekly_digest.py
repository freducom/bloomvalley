"""Weekly digest — composes and sends a Monday morning Telegram summary.

Privacy-safe: no absolute portfolio values, only % changes, counts, and tickers.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import date, datetime, timedelta

import httpx
import structlog
from sqlalchemy import func, select

from app.db.engine import async_session
from app.db.models.dividends import DividendEvent
from app.db.models.fundamentals import EarningsReport
from app.db.models.holdings_snapshot import HoldingsSnapshot
from app.db.models.insider import InsiderTrade
from app.db.models.news import NewsItem, NewsItemSecurity
from app.db.models.prices import Price
from app.db.models.recommendations import Recommendation
from app.db.models.securities import Security
from app.db.models.watchlists import WatchlistItem
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

    # 1. Recommendations — counts + per-ticker context for new ones.
    rec_section = await _recommendations_summary(week_ago)
    if rec_section:
        sections.append(rec_section)

    # 2. Portfolio & watchlist weekly movers.
    movers_section = await _portfolio_watchlist_movers(today)
    if movers_section:
        sections.append(movers_section)

    # 3. Upcoming dividends (next 7 days) — already listed tickers.
    div_section = await _upcoming_dividends(today, week_ahead)
    if div_section:
        sections.append(div_section)

    # 4. Upcoming earnings (next 7 days) — held + watchlist securities.
    earnings_section = await _upcoming_earnings(today, week_ahead)
    if earnings_section:
        sections.append(earnings_section)

    # 5. Top-impact news (last 7 days) — held + watchlist securities.
    news_section = await _top_news_impact(week_ago)
    if news_section:
        sections.append(news_section)

    # 6. Insider activity (last 7 days) — counts + top trades + cluster tickers.
    insider_section = await _insider_summary(week_ago, today)
    if insider_section:
        sections.append(insider_section)

    # 7. Macro regime with a plain-language blurb.
    macro_section = await _macro_regime()
    if macro_section:
        sections.append(macro_section)

    if len(sections) <= 3:
        sections.append("<i>No notable activity this week.</i>")

    header = f"{sections[0]}\n{sections[1]}"
    structured_body = "\n".join(sections[2:])
    fallback_body = "\n".join(sections)

    # Claude rewrites the structured sections as readable prose. Failure
    # (no API key, timeout, non-200) is non-fatal — we fall back to the
    # original list format so Monday morning always ships.
    prose = await _claude_prose_digest(structured_body)
    if prose:
        text = f"{header}\n\n{telegram._escape(prose)}"
    else:
        text = fallback_body

    ok = await notifier.send(text, force=True)
    logger.info("weekly_digest.complete", sent=ok, prose=bool(prose))
    return ok


_PROSE_SYSTEM_PROMPT = (
    "You write a weekly investing digest for a single reader — a "
    "45-year-old Finnish long-term investor following a Munger+Boglehead "
    "hybrid (60-70% index core, 30-40% conviction satellite) with a "
    "15-year horizon to fixed income by 60. Asset classes: stocks, bonds, "
    "ETFs, crypto. Finnish broker.\n\n"
    "Rewrite the structured data below as 4-6 short paragraphs of plain, "
    "scannable prose. Cover these topics in this order:\n"
    "1. New recommendations and what to actually do (buys/sells worth attention)\n"
    "2. Portfolio and watchlist moves — biggest gainers and losers, flag held vs watchlist\n"
    "3. Dividends and earnings coming up this week\n"
    "4. Insider activity worth noting (cluster buys, large sells)\n"
    "5. Macro regime and what that implies for positioning\n\n"
    "Hard rules:\n"
    "- No bullet lists, no headers, no numbered points — paragraphs only.\n"
    "- Reference tickers in plain uppercase, no formatting.\n"
    "- When data for a topic is empty, skip the paragraph rather than saying 'nothing to report'.\n"
    "- No hedging language ('potentially', 'may want to consider'); state calls directly.\n"
    "- No emojis.\n"
    "- Keep each paragraph 2-4 sentences. Total ~250-400 words.\n"
    "- Open with the single most actionable thing, not a greeting."
)


async def _claude_prose_digest(structured_body: str) -> str | None:
    """Rewrite the structured section data as readable prose.

    Provider waterfall: Claude CLI → Anthropic API → ollama/gemma on the
    local LLM server. Returns None only if every provider is unreachable;
    the digest then falls back to the raw list format so Monday morning
    always ships something.
    """
    text = await _claude_prose_via_cli(structured_body)
    if text:
        return text
    text = await _claude_prose_via_api(structured_body)
    if text:
        return text
    return await _prose_via_ollama(structured_body)


async def _claude_prose_via_cli(structured_body: str) -> str | None:
    """Invoke the `claude` CLI binary — same pattern as app.api.v1.chat."""
    claude_bin = os.environ.get("CLAUDE_CLI_BINARY", "claude")
    full_prompt = f"{_PROSE_SYSTEM_PROMPT}\n\n---\n\n{structured_body}"

    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(full_prompt)
            tmp_path = f.name
        try:
            cmd = [claude_bin, "-p", "--output-format", "text"]
            model = os.environ.get("CLAUDE_CLI_MODEL", "").strip()
            if model:
                cmd.extend(["--model", model])
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            with open(tmp_path, "rb") as fh:
                stdin_data = fh.read()
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=stdin_data),
                timeout=180,
            )
            if proc.returncode != 0:
                logger.warning(
                    "weekly_digest.prose_cli_error",
                    rc=proc.returncode,
                    stderr=stderr.decode()[:300],
                )
                return None
            text = stdout.decode().strip()
            return text or None
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    except FileNotFoundError:
        logger.info("weekly_digest.prose_cli_unavailable", binary=claude_bin)
        return None
    except Exception as e:
        logger.warning("weekly_digest.prose_cli_failed", error=str(e))
        return None


async def _prose_via_ollama(structured_body: str) -> str | None:
    """Final fallback: ollama/gemma on the local LLM server (valas:11434)."""
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://192.168.1.160:11434").rstrip("/")
    # Match the analyst-swarm fallback convention (config.yaml: ollama_fallback.model).
    model = (
        os.environ.get("WEEKLY_DIGEST_OLLAMA_MODEL")
        or os.environ.get("OLLAMA_FALLBACK_MODEL")
        or "gemma4"
    )
    try:
        # Gemma on CPU with a long structured body can easily take 3-5 min.
        async with httpx.AsyncClient(timeout=600) as client:
            resp = await client.post(
                f"{base_url}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": _PROSE_SYSTEM_PROMPT},
                        {"role": "user", "content": structured_body},
                    ],
                    "stream": False,
                    "options": {"num_predict": 1500},
                },
            )
        if resp.status_code != 200:
            logger.warning(
                "weekly_digest.prose_ollama_http_error",
                status=resp.status_code,
                body=resp.text[:200],
            )
            return None
        payload = resp.json()
        text = (payload.get("message") or {}).get("content", "").strip()
        return text or None
    except Exception as e:
        logger.warning(
            "weekly_digest.prose_ollama_failed",
            error=repr(e),
            error_type=type(e).__name__,
            model=model,
        )
        return None


async def _claude_prose_via_api(structured_body: str) -> str | None:
    """Fallback: hit Anthropic API directly if ANTHROPIC_API_KEY is set."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        logger.info("weekly_digest.prose_api_skipped", reason="no_api_key")
        return None

    model = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 1500,
                    "system": _PROSE_SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": structured_body}],
                },
            )
        if resp.status_code != 200:
            logger.warning(
                "weekly_digest.prose_http_error",
                status=resp.status_code,
                body=resp.text[:200],
            )
            return None
        payload = resp.json()
        blocks = payload.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
        return text or None
    except Exception as e:
        logger.warning("weekly_digest.prose_api_failed", error=str(e))
        return None


async def _recommendations_summary(week_ago: date) -> str | None:
    """Aggregate counts of active recommendations, plus per-ticker context on new ones."""
    async with async_session() as session:
        # Aggregate counts (all active).
        result = await session.execute(
            select(Recommendation.action, func.count().label("cnt"))
            .where(Recommendation.status == "active")
            .group_by(Recommendation.action)
        )
        rows = result.all()

        # New recommendations in the last 7 days — pull context for each.
        new_result = await session.execute(
            select(Recommendation, Security.ticker)
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

    # Group new recommendations by action; only show actionable ones (BUY / SELL).
    # HOLD and WAIT are non-actions and would flood the section.
    by_action: dict[str, list[tuple[Recommendation, str]]] = {}
    for rec, ticker in new_rows:
        by_action.setdefault(rec.action, []).append((rec, ticker))

    actionable = False
    for action in ["buy", "sell"]:
        items = by_action.get(action, [])
        if not items:
            continue
        actionable = True
        shown = items[:5]
        lines.append(f"  New {action.upper()} ({len(items)}):")
        for rec, ticker in shown:
            lines.append("    " + _format_rec_line(rec, ticker))
        if len(items) > 5:
            lines.append(f"    +{len(items) - 5} more")

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


def _format_rec_line(rec: Recommendation, ticker: str) -> str:
    """One-line per-ticker rec: 'TICKER (horizon, +X%, source): thesis…'."""
    bits: list[str] = []
    if rec.time_horizon:
        bits.append(telegram._escape(rec.time_horizon))
    upside = _upside_pct(rec.entry_price_cents, rec.target_price_cents)
    if upside:
        bits.append(upside)
    if rec.source:
        bits.append(telegram._escape(rec.source))
    context = f" ({', '.join(bits)})" if bits else ""
    thesis = _first_sentence(rec.rationale, max_len=90)
    thesis_part = f" — {telegram._escape(thesis)}" if thesis else ""
    return f"{telegram._escape(ticker)}{context}{thesis_part}"


def _upside_pct(entry_cents: int | None, target_cents: int | None) -> str:
    """Return '+12%' or '-5%' from entry→target price, '' if either missing."""
    if not entry_cents or not target_cents:
        return ""
    pct = (target_cents - entry_cents) / entry_cents * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.0f}%"


def _first_sentence(text: str | None, max_len: int = 90) -> str:
    """First sentence of text, truncated at word boundary within max_len."""
    if not text:
        return ""
    cleaned = " ".join(text.strip().split())
    for sep in [". ", "; ", " — "]:
        idx = cleaned.find(sep)
        if 0 < idx <= max_len:
            cleaned = cleaned[:idx]
            break
    if len(cleaned) > max_len:
        trimmed = cleaned[:max_len].rsplit(" ", 1)[0]
        cleaned = trimmed + "…"
    return cleaned


async def _portfolio_watchlist_movers(today: date) -> str | None:
    """Top 5 gainers + top 5 losers over the last ~7 trading days.

    Universe = securities in the latest holdings snapshot ∪ all watchlist items.
    Price change is computed from the most recent close vs the latest close that
    is at least 7 calendar days older, so weekend/holiday gaps don't matter.
    """
    async with async_session() as session:
        # Universe: held + watchlist (deduped).
        latest_snap = (await session.execute(
            select(func.max(HoldingsSnapshot.snapshot_date))
        )).scalar_one_or_none()

        held_ids: set[int] = set()
        if latest_snap is not None:
            held_q = select(HoldingsSnapshot.security_id.distinct()).where(
                HoldingsSnapshot.snapshot_date == latest_snap
            )
            held_ids = {r[0] for r in (await session.execute(held_q)).all()}

        watch_q = select(WatchlistItem.security_id.distinct())
        watch_ids = {r[0] for r in (await session.execute(watch_q)).all()}

        universe = held_ids | watch_ids
        if not universe:
            return None

        # Pull last 15 days of prices for the universe — enough to find both
        # endpoints under normal exchange holidays. One query, Python-side pick.
        price_cutoff = today - timedelta(days=15)
        price_q = (
            select(Price.security_id, Price.date, Price.close_cents, Security.ticker)
            .join(Security, Price.security_id == Security.id)
            .where(Price.security_id.in_(universe), Price.date >= price_cutoff)
            .order_by(Price.security_id, Price.date)
        )
        price_rows = (await session.execute(price_q)).all()

    # Group by security.
    by_sec: dict[int, list[tuple[date, int, str]]] = {}
    for sec_id, d, close, ticker in price_rows:
        by_sec.setdefault(sec_id, []).append((d, close, ticker))

    movers: list[tuple[str, float, int, bool]] = []  # (ticker, pct, close, is_held)
    for sec_id, series in by_sec.items():
        if len(series) < 2:
            continue
        series.sort(key=lambda r: r[0])
        latest_d, latest_c, ticker = series[-1]
        prior_cutoff = latest_d - timedelta(days=7)
        prior = next(
            (c for d, c, _ in reversed(series[:-1]) if d <= prior_cutoff),
            None,
        )
        if prior is None or prior == 0:
            continue
        pct = (latest_c - prior) / prior * 100
        movers.append((ticker, pct, latest_c, sec_id in held_ids))

    if not movers:
        return None

    movers.sort(key=lambda m: m[1], reverse=True)
    gainers = [m for m in movers if m[1] > 0][:5]
    losers = [m for m in reversed(movers) if m[1] < 0][:5]

    lines = [f"<b>Portfolio & Watchlist Movers</b> (7d)"]
    if gainers:
        lines.append("  Top gainers:")
        for ticker, pct, _close, is_held in gainers:
            marker = "⬢" if is_held else "○"
            lines.append(
                f"    {marker} {telegram._escape(ticker):<10s} "
                f"{pct:+6.1f}%"
            )
    if losers:
        lines.append("  Top losers:")
        for ticker, pct, _close, is_held in losers:
            marker = "⬢" if is_held else "○"
            lines.append(
                f"    {marker} {telegram._escape(ticker):<10s} "
                f"{pct:+6.1f}%"
            )
    lines.append("  <i>⬢ held · ○ watchlist</i>")

    if not gainers and not losers:
        return None
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


async def _upcoming_earnings(today: date, week_ahead: date) -> str | None:
    """Upcoming earnings reports in the next 7 days for held + watchlist securities."""
    async with async_session() as session:
        held_q = select(HoldingsSnapshot.security_id.distinct()).where(
            HoldingsSnapshot.snapshot_date == (
                select(func.max(HoldingsSnapshot.snapshot_date)).scalar_subquery()
            )
        )
        held_ids = {r[0] for r in (await session.execute(held_q)).all()}

        watch_q = select(WatchlistItem.security_id.distinct())
        watch_ids = {r[0] for r in (await session.execute(watch_q)).all()}

        universe = held_ids | watch_ids
        if not universe:
            return None

        rows = (await session.execute(
            select(EarningsReport, Security.ticker)
            .join(Security, EarningsReport.security_id == Security.id)
            .where(
                EarningsReport.security_id.in_(universe),
                EarningsReport.report_date >= today,
                EarningsReport.report_date <= week_ahead,
            )
            .order_by(EarningsReport.report_date)
        )).all()

    if not rows:
        return None

    lines = ["<b>Earnings Next 7d</b>"]
    for er, ticker in rows[:10]:
        day_name = er.report_date.strftime("%a")
        marker = "⬢" if er.security_id in held_ids else "○"
        est_bits = []
        if er.eps_estimate_cents is not None:
            est_bits.append(f"est EPS {er.eps_estimate_cents / 100:.2f}")
        if er.fiscal_quarter:
            est_bits.append(telegram._escape(er.fiscal_quarter))
        est = f" — {', '.join(est_bits)}" if est_bits else ""
        lines.append(
            f"  {marker} {telegram._escape(ticker)} "
            f"({day_name} {er.report_date.strftime('%d %b')}){est}"
        )
    if len(rows) > 10:
        lines.append(f"  ... and {len(rows) - 10} more")
    return "\n".join(lines)


async def _top_news_impact(week_ago: date) -> str | None:
    """Top 5 highest-severity news items from the last 7 days for held/watchlist securities."""
    severity_rank = {"high": 3, "medium": 2, "low": 1}

    async with async_session() as session:
        held_q = select(HoldingsSnapshot.security_id.distinct()).where(
            HoldingsSnapshot.snapshot_date == (
                select(func.max(HoldingsSnapshot.snapshot_date)).scalar_subquery()
            )
        )
        held_ids = {r[0] for r in (await session.execute(held_q)).all()}

        watch_q = select(WatchlistItem.security_id.distinct())
        watch_ids = {r[0] for r in (await session.execute(watch_q)).all()}

        universe = held_ids | watch_ids
        if not universe:
            return None

        # Pull news-security links with impact for the last 7 days, scoped to universe.
        rows = (await session.execute(
            select(NewsItem, NewsItemSecurity, Security.ticker)
            .join(NewsItemSecurity, NewsItemSecurity.news_item_id == NewsItem.id)
            .join(Security, NewsItemSecurity.security_id == Security.id)
            .where(
                NewsItemSecurity.security_id.in_(universe),
                NewsItem.published_at >= week_ago,
                NewsItemSecurity.impact_severity.in_(["high", "medium"]),
            )
            .order_by(NewsItem.published_at.desc())
        )).all()

    if not rows:
        return None

    # De-dup by news_item (one item may link to multiple securities), rank by severity.
    seen_items: dict[int, tuple[NewsItem, NewsItemSecurity, str]] = {}
    for item, link, ticker in rows:
        if item.id in seen_items:
            continue
        seen_items[item.id] = (item, link, ticker)

    ranked = sorted(
        seen_items.values(),
        key=lambda t: (severity_rank.get(t[1].impact_severity or "", 0), t[0].published_at),
        reverse=True,
    )
    top = ranked[:5]
    if not top:
        return None

    lines = ["<b>Top News Impact</b> (last 7d)"]
    for item, link, ticker in top:
        marker = "⬢" if link.security_id in held_ids else "○"
        sev = (link.impact_severity or "?").upper()[:1]
        dir_char = {"positive": "▲", "negative": "▼", "neutral": "•"}.get(
            link.impact_direction or "", "•"
        )
        title = _first_sentence(item.title, max_len=80)
        lines.append(
            f"  {marker} {telegram._escape(ticker):<8s} "
            f"{sev}{dir_char} {telegram._escape(title)}"
        )
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
