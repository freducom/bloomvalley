"""Signal bot — handles inbound `bv …` messages routed from signal-gateway.

The signal-gateway router POSTs Note-to-Self messages prefixed with
SIGNAL_PREFIX (default `bv`) to /api/v1/notifications/signal-webhook
with the prefix already stripped. We dispatch on the first word as a
command, falling back to LLM chat for free-form text.

Differs from telegram_bot in being request/response (no polling) and
in returning plain text rather than HTML.
"""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import structlog

logger = structlog.get_logger()

HELP_TEXT = (
    "Bloomvalley Signal Bot\n\n"
    "  help            This message.\n"
    "  portfolio       Current holdings + allocation.\n"
    "  chart [DAYS]    Portfolio value chart, DAYS window (default 90).\n"
    "  gains [YEAR]    Realized gains + dividends for YEAR (default: YTD).\n"
    "  brief           Latest analyst brief for today.\n"
    "  status          Swarm + pipeline health.\n"
    "  analyze TICKER  Quick analysis of a security.\n"
    "  clear           Reset chat history.\n\n"
    "Or just type a question and I'll answer it."
)

_REDIS_HISTORY_KEY = "bloomvalley:signal:history"
_HISTORY_TTL = 60 * 60 * 24  # 24 h
_HISTORY_MAX = 20
_BASE_URL = "http://localhost:8000/api/v1"


async def process_message(text: str, redis, api_key: str) -> str:
    text = (text or "").strip()
    if not text:
        return HELP_TEXT

    first, _, rest = text.partition(" ")
    cmd = first.lower()
    args = rest.strip()

    headers = {"X-API-Key": api_key} if api_key else {}

    try:
        if cmd in ("help", "?", "/help"):
            return HELP_TEXT
        if cmd == "clear":
            await redis.delete(_REDIS_HISTORY_KEY)
            return "History cleared."
        if cmd == "portfolio":
            return await _portfolio_summary(headers)
        if cmd == "chart":
            days = 90
            if args:
                try:
                    days = int(args.split()[0])
                except ValueError:
                    return "Usage: chart [DAYS]"
            return await _portfolio_chart(headers, days)
        if cmd == "gains":
            year = None
            if args:
                try:
                    year = int(args.split()[0])
                except ValueError:
                    return "Usage: gains [YEAR]"
            return await _ytd_gains(headers, year)
        if cmd == "status":
            return await _system_status(headers)
        if cmd == "brief":
            return await _latest_brief(headers)
        if cmd == "analyze":
            if not args:
                return "Usage: analyze TICKER"
            return await _analyze(args.split()[0].upper())
    except Exception as e:
        logger.error("signal_bot_command_error", cmd=cmd, error=str(e))
        return f"Error running '{cmd}': {e}"

    return await _chat(text, redis)


async def _portfolio_summary(headers: dict) -> str:
    async with httpx.AsyncClient(timeout=15, base_url=_BASE_URL, headers=headers) as client:
        summary_resp = await client.get("/portfolio/summary")
        holdings_resp = await client.get("/portfolio/holdings")
        if summary_resp.status_code != 200:
            return f"Failed to fetch portfolio summary (HTTP {summary_resp.status_code})."
        d = summary_resp.json().get("data", {})
        holdings = (
            holdings_resp.json().get("data", [])
            if holdings_resp.status_code == 200
            else []
        )

    total = d.get("totalValueEurCents", 0) / 100
    cost = d.get("totalCostEurCents", 0) / 100
    cash = d.get("totalCashEurCents", 0) / 100
    pnl = d.get("unrealizedPnlPct", 0) or 0
    count = d.get("holdingsCount", 0)
    alloc_total = d.get("totalValueEurCents", 1) or 1

    parts = [
        "Portfolio",
        f"Total: {total:,.0f} EUR ({count} holdings)",
        f"Cost basis: {cost:,.0f} EUR",
        f"Cash: {cash:,.0f} EUR",
        f"P&L: {pnl:+.1f}%",
    ]

    alloc_lines = []
    for cls, val in sorted((d.get("allocation") or {}).items(), key=lambda x: x[1], reverse=True):
        pct = val / alloc_total * 100
        alloc_lines.append(f"  {cls}: {pct:.1f}%")
    if alloc_lines:
        parts.append("")
        parts.append("Allocation:")
        parts.extend(alloc_lines)

    if holdings:
        rows = sorted(
            holdings,
            key=lambda h: h.get("marketValueEurCents") or 0,
            reverse=True,
        )
        parts.append("")
        parts.append(f"Holdings ({len(rows)}):")
        for h in rows:
            ticker = (h.get("ticker") or "?")[:12]
            qty = float(h.get("quantity") or 0)
            qty_s = f"{qty:,.0f}" if abs(qty - round(qty)) < 1e-9 else f"{qty:,.4f}".rstrip("0").rstrip(".")
            mv_eur = (h.get("marketValueEurCents") or 0) / 100
            pnl_pct = h.get("unrealizedPnlPct") or 0
            parts.append(
                f"  {ticker:12s} {qty_s:>11s}  {mv_eur:>9,.0f}€  {pnl_pct:+6.1f}%"
            )
    return "\n".join(parts)


async def _ytd_gains(headers: dict, year: int | None = None) -> str:
    year = year or datetime.now(ZoneInfo("Europe/Helsinki")).year
    async with httpx.AsyncClient(timeout=15, base_url=_BASE_URL, headers=headers) as client:
        gains_resp = await client.get(f"/tax/gains?year={year}")
        div_resp = await client.get(f"/dividends/tax-summary?year={year}")

    parts = [f"Realized P&L — {year}"]

    if gains_resp.status_code == 200:
        g = gains_resp.json().get("data", {}) or {}
        realized = (g.get("realizedGainsCents") or 0) / 100
        losses = (g.get("realizedLossesCents") or 0) / 100
        net = (g.get("netRealizedCents") or 0) / 100
        tax = ((g.get("estimatedTax") or {}).get("taxCents") or 0) / 100
        parts.append("")
        parts.append("Capital gains (taxable accounts):")
        parts.append(f"  Gains:    {realized:>+12,.2f} EUR")
        parts.append(f"  Losses:   {losses:>+12,.2f} EUR")
        parts.append(f"  Net:      {net:>+12,.2f} EUR")
        parts.append(f"  Est. tax: {tax:>12,.2f} EUR (FI 30%/34%)")

        # Aggregate closed lots by ticker
        per_sec = g.get("perSecurity") or []
        by_ticker: dict[str, dict] = {}
        for s in per_sec:
            if s.get("isTaxFree"):
                continue
            sym = s.get("ticker") or "?"
            slot = by_ticker.setdefault(sym, {"proceeds": 0, "gain": 0})
            slot["proceeds"] += s.get("proceedsCents") or 0
            slot["gain"] += s.get("taxableGainCents") or 0

        if by_ticker:
            parts.append("")
            parts.append("Closed positions:")
            rows = sorted(by_ticker.items(), key=lambda kv: kv[1]["gain"], reverse=True)
            for sym, d in rows:
                parts.append(
                    f"  {sym[:12]:12s} proc={d['proceeds']/100:>9,.0f}€  "
                    f"P&L={d['gain']/100:>+9,.0f}€"
                )
    else:
        parts.append(f"(capital gains unavailable, HTTP {gains_resp.status_code})")

    if div_resp.status_code == 200:
        dv = div_resp.json().get("data", {}) or {}
        gross = (dv.get("totalGrossCents") or 0) / 100
        wht = (dv.get("totalWithholdingCents") or 0) / 100
        net = (dv.get("totalNetCents") or 0) / 100
        reclaim = (dv.get("totalReclaimableCents") or 0) / 100
        parts.append("")
        parts.append("Dividend income:")
        parts.append(f"  Gross:        {gross:>10,.2f} EUR")
        parts.append(f"  Withholding:  {wht:>10,.2f} EUR")
        parts.append(f"  Net received: {net:>10,.2f} EUR")
        if reclaim > 0:
            parts.append(f"  Reclaimable:  {reclaim:>10,.2f} EUR")
    else:
        parts.append(f"(dividends unavailable, HTTP {div_resp.status_code})")

    return "\n".join(parts)


async def _system_status(headers: dict) -> str:
    async with httpx.AsyncClient(timeout=10, base_url=_BASE_URL, headers=headers) as client:
        swarm_resp = await client.get("/swarm/status")
        pipe_resp = await client.get("/pipelines")
    swarm = swarm_resp.json().get("data", {}) if swarm_resp.status_code == 200 else {}
    pipes = pipe_resp.json().get("data", []) if pipe_resp.status_code == 200 else []
    failed = [p for p in pipes if p.get("status") == "failed"]

    return (
        "System Status\n"
        f"Swarm: {swarm.get('status', 'unknown')}\n"
        f"Pipelines: {len(pipes)} total, {len(failed)} failed"
    )


async def _latest_brief(headers: dict) -> str:
    date_str = datetime.now(ZoneInfo("Europe/Helsinki")).strftime("%Y-%m-%d")
    async with httpx.AsyncClient(timeout=10, base_url=_BASE_URL, headers=headers) as client:
        for brief_type in ("evening", "midday", "morning", "weekend"):
            resp = await client.get(f"/notifications/brief-summary/{date_str}/{brief_type}")
            if resp.status_code != 200:
                continue
            summary = (resp.json().get("data") or {}).get("summary", "")
            if summary:
                return f"{brief_type.title()} brief — {date_str}\n\n{summary}"
    return "No brief available for today yet."


async def _analyze(ticker: str) -> str:
    from app.api.v1.chat import ChatMessage, _fetch_security_context, get_full_response
    ctx = await _fetch_security_context(ticker)
    if not ctx:
        return f"No data found for ticker {ticker}."
    msg = ChatMessage(role="user", content=f"Give me a concise 5-bullet analysis of {ticker}.")
    return await get_full_response([msg], security_context=ctx, channel="signal")


_WATCHLIST_KEYWORDS = (
    "watchlist", "watch list", "watchable",
    "munger", "buffett", "graham",
    "moat", "compounder", "compounding",
    "value investing", "value stock", "value stocks", "value pick", "value picks",
    "quality stock", "quality stocks", "quality pick", "quality picks",
    "undervalued", "intrinsic value", "fair value",
    "p/b", "p/e", "roic", "roe", "fcf yield", "fundamental", "fundamentals",
)


async def _portfolio_chart(headers: dict, days: int) -> str:
    """Fetch /portfolio/value-history for DAYS, render a line chart, send via
    signal-gateway-notify as an image attachment. Returns a short ack.
    """
    days = max(7, min(days, 730))
    async with httpx.AsyncClient(timeout=30, base_url=_BASE_URL, headers=headers) as client:
        resp = await client.get(f"/portfolio/value-history?days={days}")
    if resp.status_code != 200:
        return f"Chart failed (value-history HTTP {resp.status_code})."
    body = resp.json()
    points = body.get("data") or []
    if not points:
        return "Chart failed (no history returned)."

    # Points shape: [{"date": "YYYY-MM-DD", "valueCents": int, ...}]
    try:
        dates = [datetime.strptime(p["date"], "%Y-%m-%d") for p in points]
        values_eur = [float(p.get("valueCents", 0)) / 100 for p in points]
    except (KeyError, ValueError) as e:
        return f"Chart failed (bad history shape: {e})."

    png = _render_value_history_png(dates, values_eur, days)
    if png is None:
        return "Chart failed (matplotlib unavailable)."

    from app.services import signal as signal_provider
    latest = values_eur[-1]
    first = values_eur[0]
    delta = latest - first
    delta_pct = (delta / first * 100) if first else 0
    caption = (
        f"**Portfolio value — last {days} days**\n"
        f"{latest:,.0f} EUR ({delta:+,.0f} EUR, {delta_pct:+.1f}%)"
    )
    ok = await signal_provider.send_image(caption, png, force=True)
    # Empty return → signal-webhook responds with HTTP 204 → router suppresses
    # the text follow-up. The image + caption already convey what was sent.
    return "" if ok else "chart render OK but Signal send failed"


def _render_value_history_png(dates, values_eur, days: int):
    """Line chart of portfolio value. Returns PNG bytes or None if matplotlib
    isn't installed.
    """
    import io
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        return None

    fig, ax = plt.subplots(figsize=(8, 4.5), constrained_layout=True)
    fig.patch.set_facecolor("#1a1a1a")
    ax.set_facecolor("#222")

    ax.plot(dates, values_eur, color="#6cc26c", linewidth=1.4)
    ax.fill_between(dates, values_eur, alpha=0.15, color="#6cc26c")

    ax.set_title(
        f"Portfolio value — last {days} days",
        color="#eee",
        fontsize=11,
        loc="left",
        pad=6,
    )
    ax.tick_params(colors="#aaa", labelsize=8)
    for s in ax.spines.values():
        s.set_color("#444")
    ax.grid(True, color="#333", linewidth=0.5, alpha=0.5)
    ax.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda x, _: f"{x/1000:,.0f}k€")
    )
    if days > 60:
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO, interval=max(1, days // 14)))
    else:
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    fig.autofmt_xdate(rotation=30, ha="right")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


def _wants_watchlist_context(text: str) -> bool:
    lo = (text or "").lower()
    return any(kw in lo for kw in _WATCHLIST_KEYWORDS)


async def _chat(text: str, redis) -> str:
    from app.api.v1.chat import ChatMessage, _fetch_watchlist_context, get_full_response

    raw = await redis.get(_REDIS_HISTORY_KEY)
    history = json.loads(raw) if raw else []
    history.append({"role": "user", "content": text})
    history = history[-_HISTORY_MAX:]

    messages = [ChatMessage(role=m["role"], content=m["content"]) for m in history]

    security_context = ""
    if _wants_watchlist_context(text):
        try:
            security_context = await _fetch_watchlist_context()
        except Exception as e:
            logger.warning("watchlist_context_failed", error=str(e))

    response = await get_full_response(messages, security_context=security_context, channel="signal")

    history.append({"role": "assistant", "content": response})
    await redis.set(_REDIS_HISTORY_KEY, json.dumps(history), ex=_HISTORY_TTL)
    return response
