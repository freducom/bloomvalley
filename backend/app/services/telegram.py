"""Telegram notification service — sends alerts to a private chat."""

from datetime import datetime

import httpx
import structlog
from zoneinfo import ZoneInfo

from app.config import settings

logger = structlog.get_logger()

HELSINKI = ZoneInfo("Europe/Helsinki")
QUIET_START = 21  # 21:00
QUIET_END = 7     # 07:00

API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def is_configured() -> bool:
    return bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID)


def _is_quiet_hours() -> bool:
    hour = datetime.now(HELSINKI).hour
    return hour >= QUIET_START or hour < QUIET_END


async def send(text: str, force: bool = False) -> bool:
    """Send a message to the configured Telegram chat.

    Args:
        text: Message text (HTML parse mode).
        force: If True, send even during quiet hours.

    Returns True if sent, False if skipped or failed.
    """
    if not is_configured():
        return False

    if not force and _is_quiet_hours():
        logger.info("telegram_skipped_quiet_hours")
        return False

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                API_URL.format(token=settings.TELEGRAM_BOT_TOKEN),
                json={
                    "chat_id": settings.TELEGRAM_CHAT_ID,
                    "text": text[:4096],
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            if resp.status_code == 200:
                logger.info("telegram_sent", chars=len(text))
                return True
            else:
                logger.warning("telegram_send_failed", status=resp.status_code, body=resp.text[:200])
                return False
    except Exception as e:
        logger.error("telegram_send_error", error=str(e))
        return False


def _escape(text: str) -> str:
    """Escape HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def notify_recommendations(summary: str, date_str: str):
    """Send PM recommendations summary via Telegram."""
    if not is_configured() or not summary:
        return

    text = f"<b>PM Report — {_escape(date_str)}</b>\n\n{_escape(summary)}"
    await send(text)


def _fmt_eur(cents: int | None) -> str:
    """Format cents as EUR string (e.g. 12345600 -> '€123,456')."""
    if not cents:
        return "n/a"
    eur = abs(cents) / 100
    if eur >= 1_000_000:
        return f"€{eur / 1_000_000:.2f}M"
    if eur >= 1_000:
        return f"€{eur / 1_000:.0f}k"
    return f"€{eur:.0f}"


async def notify_insider_cluster_buying(clusters: list[dict]):
    """Send notification about cluster insider buying signals.

    Each cluster dict: {ticker, securityName, insiderCount, insiders, jurisdiction,
                        totalValueCents, currency, pctOfMarketCap}
    """
    if not is_configured() or not clusters:
        return

    lines = ["<b>Insider Cluster Buying Detected</b>", ""]

    for c in clusters:
        ticker = _escape(c.get("ticker", "?"))
        name = _escape(c.get("securityName", ""))
        count = c.get("insiderCount", 0)
        insiders = c.get("insiders", [])
        jurisdiction = c.get("jurisdiction", "").upper()
        total_value = c.get("totalValueCents")
        pct = c.get("pctOfMarketCap")

        lines.append(f"<b>{ticker}</b> ({name})")

        # Summary line with value and market cap %
        summary_parts = [f"{count} insiders bought within 30 days"]
        if jurisdiction:
            summary_parts[0] += f" [{jurisdiction}]"
        lines.append(f"  {summary_parts[0]}")

        value_line = f"  Total: {_fmt_eur(total_value)}"
        if pct is not None:
            value_line += f" ({pct:.3f}% of market cap)"
        lines.append(value_line)

        if insiders:
            for ins in insiders[:5]:
                role = _escape(ins.get("role", "").upper())
                name_ins = _escape(ins.get("name", ""))
                ins_val = ins.get("valueCents")
                detail = f"  • {role} {name_ins}"
                if ins_val:
                    detail += f" — {_fmt_eur(ins_val)}"
                lines.append(detail)
        lines.append("")

    lines.append(f"<i>{len(clusters)} cluster signal{'s' if len(clusters) != 1 else ''}</i>")

    await send("\n".join(lines))


async def notify_insider_held_trades(trades: list[dict]):
    """Send notification about new insider/congress trades on held securities.

    Each trade dict: {ticker, securityName, insiderName, role, tradeType,
                      shares, valueCents, currency, source}
    """
    if not is_configured() or not trades:
        return

    buys = [t for t in trades if t.get("tradeType") == "buy"]
    sells = [t for t in trades if t.get("tradeType") != "buy"]

    lines = ["<b>Insider Trades on Your Holdings</b>", ""]

    for group, label in [(buys, "BUYS"), (sells, "SELLS")]:
        if not group:
            continue
        lines.append(f"<b>{label}</b>")
        for t in group[:10]:
            ticker = _escape(t.get("ticker", "?"))
            role = _escape(t.get("role", "").upper())
            name = _escape(t.get("insiderName", t.get("memberName", "?")))
            shares = t.get("shares", "")
            source = t.get("source", "")

            detail = f"  {ticker}: {role} {name}"
            if shares:
                detail += f" — {shares} shares"
            if source == "congress":
                detail += " [CONGRESS]"
            lines.append(detail)
        if len(group) > 10:
            lines.append(f"  ... and {len(group) - 10} more")
        lines.append("")

    lines.append(f"<i>{len(trades)} trade{'s' if len(trades) != 1 else ''} on held securities</i>")

    await send("\n".join(lines))


async def notify_macro_regime_change(previous: str, current: str, confidence: str):
    """Send notification about macro regime change."""
    if not is_configured():
        return

    text = (
        f"<b>Macro Regime Change</b>\n\n"
        f"Previous: {_escape(previous)}\n"
        f"Current: <b>{_escape(current)}</b>\n"
        f"Confidence: {_escape(confidence)}\n\n"
        f"<i>Review allocation</i>"
    )

    await send(text)
