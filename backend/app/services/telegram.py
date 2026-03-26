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


async def notify_recommendations(recs: list[dict], date_str: str):
    """Send notification about new PM recommendations (privacy-safe)."""
    if not is_configured() or not recs:
        return

    buys = [r for r in recs if r.get("action") == "buy"]
    sells = [r for r in recs if r.get("action") == "sell"]
    holds = [r for r in recs if r.get("action") == "hold"]
    waits = [r for r in recs if r.get("action") == "wait"]

    lines = [f"<b>PM Recommendations — {_escape(date_str)}</b>", ""]

    if buys:
        tickers = ", ".join(_escape(r.get("ticker", "?")) for r in buys)
        lines.append(f"BUY ({len(buys)}): {tickers}")
    if sells:
        tickers = ", ".join(_escape(r.get("ticker", "?")) for r in sells)
        lines.append(f"SELL ({len(sells)}): {tickers}")
    if holds:
        lines.append(f"HOLD: {len(holds)} positions")
    if waits:
        lines.append(f"WAIT: {len(waits)} watchlist items")

    lines.append("")
    lines.append(f"<i>{len(recs)} total recommendations</i>")

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
