"""Notification endpoints (provider-agnostic)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from app.services import notifier, telegram
from app.services.insider_alerts import check_and_notify as check_insider_alerts
from app.services.weekly_digest import compose_and_send_digest

router = APIRouter()

# Redis key for storing brief summaries: bloomvalley:brief:{date}:{brief_type}
_BRIEF_KEY = "bloomvalley:brief:{date}:{brief_type}"
_BRIEF_TTL = 86400  # 24 hours


@router.post("/test")
async def test_notification():
    """Send a test message to verify notification setup."""
    provider = notifier.get_provider()
    if not notifier.is_configured():
        return {
            "data": {"sent": False, "provider": provider, "reason": f"provider={provider!r} is not configured"},
            "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
        }

    ok = await notifier.send("<b>Bloomvalley</b> — test notification", force=True)
    return {
        "data": {"sent": ok, "provider": provider},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/brief-summary/{date_str}/{brief_type}")
async def get_brief_summary(date_str: str, brief_type: str, request: Request):
    """Retrieve a stored brief summary (used by midday run to fetch morning brief)."""
    redis = request.app.state.redis
    key = _BRIEF_KEY.format(date=date_str, brief_type=brief_type)
    summary = await redis.get(key)
    return {
        "data": {"summary": summary or "", "date": date_str, "brief_type": brief_type},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.post("/brief-summary")
async def store_brief_summary(body: dict, request: Request):
    """Store a brief summary in Redis for later retrieval by subsequent runs."""
    redis = request.app.state.redis
    date_str = body.get("date", "")
    brief_type = body.get("brief_type", "")
    summary = body.get("summary", "")
    if date_str and brief_type and summary:
        key = _BRIEF_KEY.format(date=date_str, brief_type=brief_type)
        await redis.set(key, summary, ex=_BRIEF_TTL)
    return {
        "data": {"stored": True, "date": date_str, "brief_type": brief_type},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.post("/send")
async def send_notification(body: dict, request: Request):
    """Internal endpoint for swarm/cron to trigger notifications.

    Body: {"event": "recommendations", "data": {...}}
    """
    event = body.get("event")

    if event == "recommendations":
        summary = body.get("data", {}).get("summary", "")
        date_str = body.get("data", {}).get("date", "")
        brief_type = body.get("data", {}).get("brief_type", "morning")
        await telegram.notify_recommendations(summary, date_str, brief_type)

        # Store the summary in Redis for subsequent briefs to reference
        if summary and date_str:
            redis = request.app.state.redis
            key = _BRIEF_KEY.format(date=date_str, brief_type=brief_type)
            await redis.set(key, summary, ex=_BRIEF_TTL)

    elif event == "macro_regime_change":
        d = body.get("data", {})
        await telegram.notify_macro_regime_change(
            d.get("previous", "unknown"),
            d.get("current", "unknown"),
            d.get("confidence", "unknown"),
        )

    elif event == "insider_alerts":
        await check_insider_alerts()

    elif event == "weekly_digest":
        await compose_and_send_digest()

    return {
        "data": {"event": event, "handled": True},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.post("/check-insider-alerts")
async def trigger_insider_alert_check():
    """Manually trigger insider alert detection and Telegram notifications."""
    if not notifier.is_configured():
        return {
            "data": {"sent": False, "reason": f"notification provider {notifier.get_provider()!r} is not configured"},
            "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
        }

    await check_insider_alerts()
    return {
        "data": {"checked": True},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.post("/signal-webhook")
async def signal_webhook(body: dict, request: Request):
    """Inbound endpoint hit by signal-gateway's router.

    Body is `{"message": "..."}` — the user's Signal Note-to-Self message
    with the prefix already stripped. Authenticated via the global
    X-API-Key middleware; signal-gateway is registered at startup to
    forward the API key on every dispatch.
    """
    text = (body.get("message") or "").strip()

    from app.services import signal_bot
    from app.config import settings

    response = await signal_bot.process_message(text, request.app.state.redis, settings.API_KEY)
    # An empty response means the handler already delivered everything via a
    # side-channel (typically an image attachment through signal-gateway-notify).
    # Return HTTP 204 so signal-gateway's router doesn't post a redundant text
    # follow-up ("ok" or "chart sent").
    if not response:
        return PlainTextResponse("", status_code=204)
    return PlainTextResponse(response)


@router.post("/weekly-digest")
async def trigger_weekly_digest():
    """Manually trigger weekly digest notification."""
    if not notifier.is_configured():
        return {
            "data": {"sent": False, "reason": f"notification provider {notifier.get_provider()!r} is not configured"},
            "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
        }

    ok = await compose_and_send_digest()
    return {
        "data": {"sent": ok},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }
