"""Data digest layer — transforms raw API JSON into compact text summaries.

Used by the swarm orchestrator to pre-process data before sending to LLMs.
Smaller models (gemma4) benefit hugely from structured text vs raw JSON dumps.
"""

from __future__ import annotations

import json
from typing import Any


def _safe_parse(json_str: str) -> Any:
    """Parse JSON string, return empty dict/list on failure."""
    if not json_str or json_str.startswith("ERROR"):
        return {}
    try:
        d = json.loads(json_str)
        return d.get("data", d) if isinstance(d, dict) else d
    except (json.JSONDecodeError, TypeError):
        return {}


def _cents_to_eur(cents: int | None) -> str:
    if cents is None:
        return "N/A"
    return f"€{cents / 100:,.2f}"


def _pct(val: float | None, decimals: int = 1) -> str:
    if val is None:
        return "N/A"
    return f"{val:+.{decimals}f}%"


# ── Portfolio ──


def digest_holdings(json_str: str) -> str:
    """Convert holdings JSON into a readable table."""
    items = _safe_parse(json_str)
    if not items or not isinstance(items, list):
        return "No holdings data available."

    lines = ["PORTFOLIO HOLDINGS"]
    lines.append(f"{'Ticker':<14} {'Name':<30} {'Qty':>8} {'Price':>10} "
                 f"{'Value EUR':>12} {'Wt%':>6} {'P&L%':>7} {'Class':<6}")
    lines.append("-" * 100)

    total = sum(h.get("marketValueEurCents", 0) for h in items)
    for h in sorted(items, key=lambda x: x.get("marketValueEurCents", 0), reverse=True):
        ticker = h.get("ticker", "?")
        name = (h.get("name") or "")[:28]
        qty = h.get("quantity", "0")
        # Handle string quantities (decimals from API)
        try:
            qty_f = float(qty)
            qty_s = f"{qty_f:.2f}" if qty_f != int(qty_f) else str(int(qty_f))
        except (ValueError, TypeError):
            qty_s = str(qty)
        price = _cents_to_eur(h.get("currentPriceCents"))
        value = _cents_to_eur(h.get("marketValueEurCents"))
        weight = f"{h.get('marketValueEurCents', 0) / total * 100:.1f}%" if total else "N/A"
        pnl = _pct(h.get("unrealizedPnlPct"))
        cls = h.get("assetClass", "?")[:6]
        lines.append(f"{ticker:<14} {name:<30} {qty_s:>8} {price:>10} "
                     f"{value:>12} {weight:>6} {pnl:>7} {cls:<6}")

    lines.append(f"\nTotal: {_cents_to_eur(total)} across {len(items)} positions")
    return "\n".join(lines)


def digest_portfolio_summary(json_str: str) -> str:
    """Convert portfolio summary into readable text."""
    d = _safe_parse(json_str)
    if not d or not isinstance(d, dict):
        return "No portfolio summary available."

    total = _cents_to_eur(d.get("totalValueEurCents"))
    cost = _cents_to_eur(d.get("totalCostEurCents"))
    cash = _cents_to_eur(d.get("totalCashEurCents"))
    pnl = _pct(d.get("unrealizedPnlPct"))
    count = d.get("holdingsCount", 0)

    lines = [f"PORTFOLIO SUMMARY: {total} total ({count} holdings), Cost basis: {cost}, Cash: {cash}, P&L: {pnl}"]

    alloc = d.get("allocation", {})
    if alloc:
        total_cents = d.get("totalValueEurCents", 1) or 1
        parts = []
        for cls, val in sorted(alloc.items(), key=lambda x: x[1], reverse=True):
            pct = val / total_cents * 100
            parts.append(f"{cls}: {_cents_to_eur(val)} ({pct:.1f}%)")
        lines.append("Allocation: " + " | ".join(parts))

    accounts = d.get("accounts", [])
    if accounts:
        acct_parts = [f"{a['accountName']}: {_cents_to_eur(a['valueCents'])}" for a in accounts]
        lines.append("Accounts: " + " | ".join(acct_parts))

    return "\n".join(lines)


# ── Fundamentals ──


def digest_fundamentals_for_security(json_str: str, ticker: str) -> str:
    """Extract and format fundamentals for a single security."""
    items = _safe_parse(json_str)
    if not isinstance(items, list):
        return ""

    rec = next((f for f in items if f.get("ticker") == ticker), None)
    if not rec:
        return f"No fundamental data available for {ticker}."

    lines = [f"FUNDAMENTALS: {ticker}"]
    fields = [
        ("P/E", rec.get("peRatio")),
        ("P/B", rec.get("priceToBook")),
        ("ROIC", f"{rec['roic']:.1%}" if rec.get("roic") else None),
        ("ROE", f"{rec['roe']:.1%}" if rec.get("roe") else None),
        ("FCF Yield", f"{rec['fcfYield']:.1%}" if rec.get("fcfYield") else None),
        ("Net Debt/EBITDA", rec.get("netDebtEbitda")),
        ("Gross Margin", f"{rec['grossMargin']:.1%}" if rec.get("grossMargin") else None),
        ("Operating Margin", f"{rec['operatingMargin']:.1%}" if rec.get("operatingMargin") else None),
        ("Dividend Yield", f"{rec['dividendYield']:.1%}" if rec.get("dividendYield") else None),
    ]
    for label, val in fields:
        if val is not None:
            lines.append(f"  {label}: {val}")

    # DCF valuation
    dcf_per_share = rec.get("dcfPerShareCents")
    current = rec.get("currentPriceCents")
    if dcf_per_share and current:
        upside = rec.get("dcfUpsidePct")
        lines.append(f"  DCF Value: {_cents_to_eur(dcf_per_share)}/share "
                     f"(current: {_cents_to_eur(current)}, upside: {_pct(upside)})")
        if rec.get("dcfModelNotes"):
            lines.append(f"  DCF Model: {rec['dcfModelNotes']}")

    # Short interest
    si = rec.get("shortInterestPct")
    if si:
        lines.append(f"  Short Interest: {si}% (risk: {rec.get('shortSqueezeRisk', '?')})")

    # Smart money
    sm = rec.get("smartMoneySignal")
    if sm and sm != "neutral":
        lines.append(f"  Smart Money: {sm}")

    return "\n".join(lines)


def digest_fundamentals_table(json_str: str) -> str:
    """Summarize all fundamentals as a ranked table."""
    items = _safe_parse(json_str)
    if not isinstance(items, list) or not items:
        return "No fundamental data available."

    lines = ["FUNDAMENTALS OVERVIEW (sorted by DCF upside)"]
    lines.append(f"{'Ticker':<14} {'P/E':>6} {'P/B':>6} {'ROIC':>7} "
                 f"{'FCF Yld':>8} {'DCF Up%':>8} {'SmartMoney':<10}")
    lines.append("-" * 65)

    sorted_items = sorted(items, key=lambda x: x.get("dcfUpsidePct") or -999, reverse=True)
    for f in sorted_items[:40]:  # Top 40
        ticker = f.get("ticker", "?")
        pe = f"{f['peRatio']:.1f}" if f.get("peRatio") else "N/A"
        pb = f"{f['priceToBook']:.1f}" if f.get("priceToBook") else "N/A"
        roic = f"{f['roic']:.0%}" if f.get("roic") else "N/A"
        fcf = f"{f['fcfYield']:.1%}" if f.get("fcfYield") else "N/A"
        dcf_up = _pct(f.get("dcfUpsidePct")) if f.get("dcfUpsidePct") is not None else "N/A"
        sm = f.get("smartMoneySignal", "")[:10]
        lines.append(f"{ticker:<14} {pe:>6} {pb:>6} {roic:>7} "
                     f"{fcf:>8} {dcf_up:>8} {sm:<10}")

    return "\n".join(lines)


# ── Insider Signals ──


def digest_insider_signals(json_str: str, ticker: str | None = None) -> str:
    """Convert insider signals into actionable text."""
    items = _safe_parse(json_str)
    if not isinstance(items, list) or not items:
        return "No insider signals."

    if ticker:
        items = [s for s in items if s.get("ticker") == ticker]
        if not items:
            return f"No insider signals for {ticker}."

    lines = ["INSIDER SIGNALS"]
    for s in items[:20]:
        sev = s.get("severity", "?").upper()
        t = s.get("ticker", "?")
        msg = s.get("message", "")
        name = s.get("securityName", "")
        lines.append(f"  [{sev}] {t} ({name}): {msg}")

    return "\n".join(lines)


# ── News ──


def digest_news(json_str: str, ticker: str | None = None) -> str:
    """Summarize news items, optionally filtered by security."""
    items = _safe_parse(json_str)
    if not isinstance(items, list) or not items:
        return "No recent news."

    if ticker:
        items = [n for n in items if any(
            s.get("ticker") == ticker for s in n.get("securities", [])
        )]
        if not items:
            return f"No recent news for {ticker}."

    lines = ["RECENT NEWS"]
    for n in items[:15]:
        title = (n.get("title") or "")[:100]
        source = n.get("source", "?")
        date = (n.get("publishedAt") or "")[:10]
        tickers = ", ".join(s.get("ticker", "") for s in n.get("securities", []))
        ticker_tag = f" [{tickers}]" if tickers else ""
        lines.append(f"  {date} ({source}){ticker_tag}: {title}")

    return "\n".join(lines)


# ── Macro ──


def digest_macro(json_str: str) -> str:
    """Convert macro summary into a narrative paragraph."""
    data = _safe_parse(json_str)
    if not data:
        return "No macro data available."

    # data is a list of regions with categories
    if not isinstance(data, list):
        return "No macro data available."

    lines = ["MACRO INDICATORS"]
    for region in data:
        region_label = region.get("regionLabel", "?")
        cats = region.get("categories", [])
        for cat in cats:
            cat_label = cat.get("label", "?")
            indicators = cat.get("indicators", [])
            for ind in indicators:
                name = ind.get("name", "?")
                val = ind.get("value")
                unit = ind.get("unit", "")
                change = ind.get("change")
                date = (ind.get("date") or "")[:10]
                change_str = f" (chg: {change:+.2f})" if change is not None else ""
                lines.append(f"  {region_label} | {name}: {val}{unit}{change_str} [{date}]")

    return "\n".join(lines)


def digest_macro_regime(json_str: str) -> str:
    """Convert macro regime into readable text."""
    d = _safe_parse(json_str)
    if not d or not isinstance(d, dict):
        return "No regime data available."

    regime = d.get("regime", "?")
    confidence = d.get("confidence", "?")
    score = d.get("compositeScore", 0)

    lines = [f"MACRO REGIME: {regime.upper()} (confidence: {confidence}, score: {score:.2f})"]

    for sig in d.get("signals", []):
        name = sig.get("name", "?")
        signal = sig.get("signal", "?")
        detail = sig.get("detail", "")
        lines.append(f"  {name}: {signal} — {detail}")

    implications = d.get("assetClassImplications", {})
    if implications:
        lines.append("Asset class implications:")
        for cls, impl in implications.items():
            lines.append(f"  {cls}: {impl}")

    return "\n".join(lines)


# ── Risk ──


def digest_risk(json_str: str) -> str:
    """Convert risk metrics into readable text."""
    d = _safe_parse(json_str)
    if not d or not isinstance(d, dict):
        return "No risk metrics available."

    lines = ["RISK METRICS"]
    for key, label in [
        ("portfolioBeta", "Portfolio Beta"),
        ("sharpeRatio", "Sharpe Ratio"),
        ("volatility", "Volatility"),
        ("maxDrawdown", "Max Drawdown"),
        ("var95", "VaR 95%"),
        ("cvar95", "CVaR 95%"),
    ]:
        val = d.get(key)
        if val is not None:
            lines.append(f"  {label}: {val}")

    # Concentration
    conc = d.get("concentration", {})
    if conc:
        lines.append(f"  Top 5 concentration: {conc.get('top5Pct', '?')}%")
        lines.append(f"  HHI: {conc.get('hhi', '?')}")

    return "\n".join(lines)


def digest_stress_tests(json_str: str) -> str:
    """Convert stress test results into readable text."""
    d = _safe_parse(json_str)
    if not d:
        return "No stress test data."

    scenarios = d if isinstance(d, list) else d.get("scenarios", [])
    if not scenarios:
        return "No stress test scenarios."

    lines = ["STRESS TEST SCENARIOS"]
    for s in scenarios:
        name = s.get("name", "?")
        impact = s.get("portfolioImpactPct") or s.get("impact")
        lines.append(f"  {name}: {_pct(impact) if isinstance(impact, (int, float)) else impact}")

    return "\n".join(lines)


# ── Technical ──


def digest_technical(ohlc_json: str, ticker: str) -> str:
    """Convert OHLC + indicators into a one-line technical summary."""
    d = _safe_parse(ohlc_json)
    if not d or not isinstance(d, dict):
        return f"No technical data for {ticker}."

    indicators = d.get("indicators", {})
    candles = d.get("candles", [])

    parts = [f"TECHNICAL: {ticker}"]

    # Latest price from candles
    if candles:
        last = candles[-1]
        parts.append(f"  Latest: O={last.get('open')} H={last.get('high')} "
                     f"L={last.get('low')} C={last.get('close')} V={last.get('volume')}")

    # Helper to get last value from indicator list [{time, value}, ...]
    def _last_val(indicator_data):
        if isinstance(indicator_data, list) and indicator_data:
            last = indicator_data[-1]
            return last.get("value") if isinstance(last, dict) else last
        return None

    # SMA
    sma = indicators.get("sma", [])
    val = _last_val(sma)
    if val is not None:
        parts.append(f"  SMA: {val:.2f}")

    # EMA
    ema = indicators.get("ema", [])
    val = _last_val(ema)
    if val is not None:
        parts.append(f"  EMA: {val:.2f}")

    # RSI
    rsi = indicators.get("rsi", [])
    val = _last_val(rsi)
    if val is not None:
        status = "overbought" if val > 70 else "oversold" if val < 30 else "neutral"
        parts.append(f"  RSI: {val:.1f} ({status})")

    # MACD
    macd = indicators.get("macd", {})
    if isinstance(macd, dict):
        macd_line = macd.get("macd", [])
        signal_line = macd.get("signal", [])
        hist = macd.get("histogram", [])
        m = _last_val(macd_line)
        s = _last_val(signal_line)
        h = _last_val(hist)
        if m is not None and s is not None:
            status = "bullish" if m > s else "bearish"
            parts.append(f"  MACD: {m:.4f} vs Signal: {s:.4f} "
                         f"(hist: {h:.4f}, {status})" if h else f"  MACD: {m:.4f} ({status})")

    # Bollinger Bands
    bb = indicators.get("bb", {})
    if isinstance(bb, dict):
        upper = _last_val(bb.get("upper", []))
        lower = _last_val(bb.get("lower", []))
        if upper is not None and lower is not None:
            parts.append(f"  Bollinger: {lower:.2f} — {upper:.2f}")

    return "\n".join(parts)


# ── Dividends ──


def digest_dividends(json_str: str) -> str:
    """Summarize upcoming dividends."""
    items = _safe_parse(json_str)
    if not isinstance(items, list) or not items:
        return "No upcoming dividends."

    lines = ["UPCOMING DIVIDENDS"]
    for div in items[:20]:
        ticker = div.get("ticker", "?")
        ex_date = div.get("exDate", "?")
        amount = div.get("amount") or div.get("amountCents")
        currency = div.get("currency", "EUR")
        lines.append(f"  {ticker}: {amount} {currency} (ex-date: {ex_date})")

    return "\n".join(lines)


# ── Watchlist ──


def digest_watchlist(json_str: str) -> str:
    """Summarize watchlist items."""
    d = _safe_parse(json_str)
    if not d:
        return "No watchlist data."

    # Could be the /watchlists/ response or /watchlists/items
    items = d if isinstance(d, list) else d.get("items", [])

    if not items:
        return "Watchlist is empty."

    lines = ["WATCHLIST"]
    for item in items:
        # Handle both watchlist summary and item detail formats
        if "items" in item:
            # This is a watchlist with nested items
            wl_name = item.get("name", "?")
            for sub in item.get("items", []):
                ticker = sub.get("ticker", "?")
                name = (sub.get("securityName") or sub.get("name", ""))[:30]
                lines.append(f"  [{wl_name}] {ticker} — {name}")
        else:
            ticker = item.get("ticker", "?")
            name = (item.get("securityName") or item.get("name", ""))[:30]
            wl = item.get("watchlistName", "")
            tag = f" [{wl}]" if wl else ""
            lines.append(f"  {ticker} — {name}{tag}")

    return "\n".join(lines)


# ── Transactions ──


def digest_transactions(json_str: str) -> str:
    """Summarize recent transactions."""
    items = _safe_parse(json_str)
    if not isinstance(items, list) or not items:
        return "No recent transactions."

    lines = ["RECENT TRANSACTIONS"]
    for t in items[:30]:
        date = (t.get("date") or t.get("tradeDate") or "?")[:10]
        action = t.get("type", "?")
        ticker = t.get("ticker", "?")
        qty = t.get("quantity", "?")
        price = t.get("priceCents")
        price_str = _cents_to_eur(price) if price else "?"
        lines.append(f"  {date} {action:>6} {ticker:<14} {qty:>8} @ {price_str}")

    return "\n".join(lines)


# ── Tax ──


def digest_tax_lots(json_str: str) -> str:
    """Summarize tax lots."""
    items = _safe_parse(json_str)
    if not isinstance(items, list) or not items:
        return "No tax lot data."

    lines = ["TAX LOTS"]
    for lot in items[:30]:
        ticker = lot.get("ticker", "?")
        qty = lot.get("quantity", "?")
        cost = _cents_to_eur(lot.get("costBasisCents"))
        acquired = (lot.get("acquiredDate") or "?")[:10]
        gain = _cents_to_eur(lot.get("unrealizedGainCents"))
        lines.append(f"  {ticker}: {qty} shares, cost {cost}, acquired {acquired}, unrealized {gain}")

    return "\n".join(lines)


def digest_tax_gains(json_str: str) -> str:
    """Summarize realized gains."""
    d = _safe_parse(json_str)
    if not d:
        return "No tax gains data."

    if isinstance(d, dict):
        total = _cents_to_eur(d.get("totalRealizedGainsCents"))
        return f"TAX GAINS: Total realized: {total}"
    return "No tax gains data."


# ── Screener ──


def digest_munger_screen(json_str: str) -> str:
    """Summarize Munger quality screen results."""
    items = _safe_parse(json_str)
    if not isinstance(items, list) or not items:
        return "No Munger screen results."

    lines = ["MUNGER QUALITY SCREEN"]
    lines.append(f"{'#':>3} {'Ticker':<14} {'ROIC':>7} {'P/B':>6} "
                 f"{'FCF Yld':>8} {'Debt/EBITDA':>12} {'Score':>6}")
    lines.append("-" * 60)

    for i, s in enumerate(items[:25], 1):
        ticker = s.get("ticker", "?")
        roic = f"{s['roic']:.0%}" if s.get("roic") else "N/A"
        pb = f"{s['priceToBook']:.1f}" if s.get("priceToBook") else "N/A"
        fcf = f"{s['fcfYield']:.1%}" if s.get("fcfYield") else "N/A"
        debt = f"{s['netDebtEbitda']:.1f}" if s.get("netDebtEbitda") is not None else "N/A"
        score = f"{s.get('score', '?')}"
        lines.append(f"{i:>3} {ticker:<14} {roic:>7} {pb:>6} "
                     f"{fcf:>8} {debt:>12} {score:>6}")

    return "\n".join(lines)


# ── Analyst Summaries (for PM) ──


def digest_analyst_summaries(json_str: str) -> str:
    """Format analyst report summaries for the portfolio manager."""
    items = _safe_parse(json_str)
    if not isinstance(items, list) or not items:
        return "No analyst summaries available."

    lines = ["ANALYST TEAM SUMMARIES"]
    for note in items:
        tags = note.get("tags", [])
        # Find the agent name tag (second tag, after 'analyst_report')
        agent = next((t for t in tags if t not in ("analyst_report", "swarm")), "unknown")
        title = note.get("title", "?")
        thesis = note.get("thesis", "")
        # Truncate each analyst summary to keep PM prompt manageable
        if len(thesis) > 3000:
            thesis = thesis[:3000] + "\n[... truncated]"
        lines.append(f"\n### {agent.replace('-', ' ').title()} Summary")
        lines.append(thesis)

    return "\n".join(lines)


# ── Deployment Plans ──


def digest_deployment_plan(json_str: str) -> str:
    """Summarize the current capital deployment plan."""
    d = _safe_parse(json_str)
    if not d or not isinstance(d, dict):
        return "No active deployment plan."

    lines = [f"CAPITAL DEPLOYMENT PLAN: {d.get('name', '?')}"]
    lines.append(f"Status: {d.get('status', '?')} | "
                 f"Period: {d.get('startDate', '?')} to {d.get('endDate', '?')}")
    total = d.get("totalAmountCents", 0)
    deployed = d.get("deployedAmountCents", 0)
    lines.append(f"Total: {_cents_to_eur(total)} | Deployed: {_cents_to_eur(deployed)} | "
                 f"Remaining: {_cents_to_eur(total - deployed)}")

    review = d.get("nextReviewDate")
    if review:
        lines.append(f"Next review date: {review}")

    notes = d.get("strategyNotes")
    if notes:
        lines.append(f"Strategy: {notes[:500]}")

    tranches = d.get("tranches", [])
    if tranches:
        lines.append(f"\nTRANCHES ({len(tranches)}):")
        for t in tranches:
            status = t.get("status", "?").upper()
            label = t.get("quarterLabel", "?")
            date = t.get("plannedDate", "?")
            amount = _cents_to_eur(t.get("amountCents", 0))
            core = t.get("coreAllocationPct", 0)
            conv = t.get("convictionAllocationPct", 0)
            cash = t.get("cashBufferPct", 0)

            lines.append(f"  [{status}] {label} — {date} — {amount}")
            lines.append(f"    Allocation: {core}% core / {conv}% conviction / {cash}% cash buffer")

            candidates = t.get("candidateTickers") or []
            if candidates:
                tickers = ", ".join(c.get("ticker", "?") for c in candidates[:8])
                lines.append(f"    Candidates: {tickers}")

            triggers = t.get("conditionalTriggers") or []
            if triggers:
                for tr in triggers:
                    lines.append(f"    Trigger: {tr.get('condition', '?')} "
                                 f"→ {tr.get('action', '?')}")

            if t.get("executedDate"):
                lines.append(f"    Executed: {t['executedDate']} — "
                             f"{_cents_to_eur(t.get('executedAmountCents', 0))}")

    return "\n".join(lines)


# ── Auto-digest dispatcher ──

# Maps endpoint patterns to digest functions
_DIGEST_MAP: dict[str, callable] = {
    "/portfolio/holdings": digest_holdings,
    "/portfolio/summary": digest_portfolio_summary,
    "/fundamentals": digest_fundamentals_table,
    "/insiders/signals": digest_insider_signals,
    "/news": digest_news,
    "/macro/summary": digest_macro,
    "/macro/regime": digest_macro_regime,
    "/risk/metrics": digest_risk,
    "/risk/stress-tests": digest_stress_tests,
    "/watchlists/": digest_watchlist,
    "/transactions": digest_transactions,
    "/tax/lots": digest_tax_lots,
    "/tax/gains": digest_tax_gains,
    "/screener/munger": digest_munger_screen,
    "/dividends/upcoming": digest_dividends,
    "/dividends/income": digest_dividends,
    "/research/notes?tag=analyst_report": digest_analyst_summaries,
    "/deployment-plans/current": digest_deployment_plan,
}


def auto_digest(data: dict[str, str]) -> dict[str, str]:
    """Auto-digest all fetched API data using appropriate functions.

    Args:
        data: dict mapping endpoint path to raw JSON string

    Returns:
        dict mapping descriptive label to digested text
    """
    result = {}
    for endpoint, json_str in data.items():
        # Find matching digest function
        matched = False
        for pattern, func in _DIGEST_MAP.items():
            if pattern in endpoint:
                label = func.__doc__.split(".", 1)[0].strip() if func.__doc__ else endpoint
                try:
                    result[label] = func(json_str)
                except Exception:
                    result[label] = f"[Error digesting {endpoint}]"
                matched = True
                break

        if not matched:
            # No digest function — include raw but truncated
            result[endpoint] = json_str[:5000] if json_str else ""

    return result
