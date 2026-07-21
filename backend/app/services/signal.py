"""Signal notification backend — pushes messages to a local signal-gateway.

See https://github.com/freducom/signal-gateway. The gateway runs in a
sibling docker-compose stack and is reachable on the shared `signal`
network at signal-gateway-notify:8090.

Wire format is plain text — Telegram-HTML is stripped before sending.
"""

import asyncio
import html as html_lib
import re
from datetime import datetime

import httpx
import structlog
from zoneinfo import ZoneInfo

from app.config import settings

logger = structlog.get_logger()

HELSINKI = ZoneInfo("Europe/Helsinki")
QUIET_START = 21  # 21:00
QUIET_END = 7     # 07:00

# Conservative cap. signal-cli accepts much more, but Signal clients render
# very long single messages poorly. Anything bigger gets truncated.
_MAX_LEN = 4000

# Shared lock so notify_* helpers don't interleave their multi-line messages.
send_lock = asyncio.Lock()

_LINK_RE = re.compile(r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r'<[^>]+>')


def is_configured() -> bool:
    return bool(settings.SIGNAL_NOTIFY_URL and settings.SIGNAL_NOTIFY_TOKEN)


def _is_quiet_hours() -> bool:
    hour = datetime.now(HELSINKI).hour
    return hour >= QUIET_START or hour < QUIET_END


def html_to_plain(text: str) -> str:
    """Convert Telegram-HTML to plain text for Signal."""
    text = _LINK_RE.sub(lambda m: f"{m.group(2)} ({m.group(1)})", text)
    text = _TAG_RE.sub('', text)
    return html_lib.unescape(text)


async def send(text_html: str, force: bool = False) -> bool:
    """Send a message via signal-gateway."""
    if not is_configured():
        return False

    if not force and _is_quiet_hours():
        logger.info("signal_skipped_quiet_hours")
        return False

    text = html_to_plain(text_html).strip()
    if not text:
        return False

    if len(text) > _MAX_LEN:
        text = text[: _MAX_LEN - 20] + "\n\n[...truncated]"

    try:
        async with send_lock:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    settings.SIGNAL_NOTIFY_URL,
                    headers={"X-Token": settings.SIGNAL_NOTIFY_TOKEN},
                    content=text.encode("utf-8"),
                )
                if resp.status_code != 200:
                    logger.warning(
                        "signal_send_failed",
                        status=resp.status_code,
                        body=resp.text[:200],
                    )
                    return False
                logger.info("signal_sent", chars=len(text))
                return True
    except Exception as e:
        logger.error("signal_send_error", error=str(e))
        return False


async def send_image(caption: str, png_bytes: bytes, force: bool = False) -> bool:
    """Send an image with a styled caption via signal-gateway-notify (JSON body,
    text_mode=styled, base64 attachment). Respects quiet hours the same way
    as send() unless force=True.
    """
    import base64
    if not is_configured():
        return False
    if not force and _is_quiet_hours():
        logger.info("signal_skipped_quiet_hours", kind="image")
        return False
    b64 = base64.b64encode(png_bytes).decode()
    try:
        async with send_lock:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    settings.SIGNAL_NOTIFY_URL,
                    headers={
                        "X-Token": settings.SIGNAL_NOTIFY_TOKEN,
                        "Content-Type": "application/json",
                    },
                    json={
                        "message": caption,
                        "attachments_base64": [f"data:image/png;base64,{b64}"],
                        "text_mode": "styled",
                    },
                )
                if resp.status_code != 200:
                    logger.warning(
                        "signal_send_image_failed",
                        status=resp.status_code,
                        body=resp.text[:200],
                    )
                    return False
                logger.info("signal_sent_image", bytes=len(png_bytes))
                return True
    except Exception as e:
        logger.error("signal_send_image_error", error=str(e))
        return False
