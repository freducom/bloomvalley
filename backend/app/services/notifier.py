"""Provider-agnostic notification dispatcher.

Outbound notifications flow through here so call sites stay agnostic
about which messenger is configured. The wire format passed in is
Telegram-HTML (because Telegram needs it natively); the Signal backend
strips HTML to plain text before sending.

Provider selection is via NOTIFICATION_PROVIDER:
  - "signal"   (default) — push to a local signal-gateway
  - "telegram"           — direct Telegram Bot API
  - "none"               — disabled
"""

import structlog

from app.config import settings

logger = structlog.get_logger()


def get_provider() -> str:
    p = (settings.NOTIFICATION_PROVIDER or "").lower().strip()
    if p in ("telegram", "signal", "none"):
        return p
    logger.warning("notifier_unknown_provider", provider=p)
    return "none"


def is_configured() -> bool:
    p = get_provider()
    if p == "telegram":
        from app.services import telegram
        return telegram.is_configured()
    if p == "signal":
        from app.services import signal as signal_provider
        return signal_provider.is_configured()
    return False


async def send(text_html: str, force: bool = False) -> bool:
    """Send a notification through the configured provider.

    Args:
        text_html: Telegram-HTML body. Stripped to plain text for Signal.
        force: If True, bypass quiet-hours suppression.

    Returns True on dispatch, False if skipped or failed.
    """
    p = get_provider()
    if p == "telegram":
        from app.services import telegram
        return await telegram._send_via_telegram(text_html, force=force)
    if p == "signal":
        from app.services import signal as signal_provider
        return await signal_provider.send(text_html, force=force)
    return False
