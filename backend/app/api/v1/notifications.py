"""Telegram notification endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter

from app.services import telegram

router = APIRouter()


@router.post("/test")
async def test_notification():
    """Send a test message to verify Telegram setup."""
    if not telegram.is_configured():
        return {
            "data": {"sent": False, "reason": "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set"},
            "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
        }

    ok = await telegram.send("<b>Bloomvalley</b> — test notification", force=True)
    return {
        "data": {"sent": ok},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.post("/send")
async def send_notification(body: dict):
    """Internal endpoint for swarm/cron to trigger notifications.

    Body: {"event": "recommendations", "data": {...}}
    """
    event = body.get("event")

    if event == "recommendations":
        recs = body.get("data", {}).get("recommendations", [])
        date_str = body.get("data", {}).get("date", "")
        await telegram.notify_recommendations(recs, date_str)

    elif event == "macro_regime_change":
        d = body.get("data", {})
        await telegram.notify_macro_regime_change(
            d.get("previous", "unknown"),
            d.get("current", "unknown"),
            d.get("confidence", "unknown"),
        )

    return {
        "data": {"event": event, "handled": True},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }
