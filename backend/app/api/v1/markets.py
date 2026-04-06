"""Market status endpoint using exchange_calendars for holiday/half-day awareness."""

from datetime import datetime, timedelta

import exchange_calendars as xcals
import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session
from app.db.models.securities import Security

logger = structlog.get_logger()
router = APIRouter()

# Market groups — exchanges sharing the same trading hours shown as one entry.
# calendar_key is the exchange_calendars identifier.
MARKET_GROUPS = [
    {
        "label": "Nordic",
        "mics": ["XHEL", "XSTO", "XCSE"],
        "calendar_key": "XHEL",  # Helsinki drives the Nordic display
        "tz": "Europe/Helsinki",
        "pre_market_hour": None,
        "after_hours_end_hour": None,
    },
    {
        "label": "EU",
        "mics": ["XAMS", "XETR", "XPAR", "XSWX"],
        "calendar_key": "XAMS",
        "tz": "Europe/Amsterdam",
        "pre_market_hour": None,
        "after_hours_end_hour": None,
    },
    {
        "label": "London",
        "mics": ["XLON"],
        "calendar_key": "XLON",
        "tz": "Europe/London",
        "pre_market_hour": None,
        "after_hours_end_hour": None,
    },
    {
        "label": "US",
        "mics": ["XNYS", "XNAS", "NMS", "NGS", "NYQ"],
        "calendar_key": "XNYS",
        "tz": "America/New_York",
        "pre_market_hour": 4,
        "after_hours_end_hour": 20,
    },
]

# Cache calendars so we don't rebuild them on every request
_calendar_cache: dict[str, xcals.ExchangeCalendar] = {}


def _get_calendar(key: str) -> xcals.ExchangeCalendar:
    if key not in _calendar_cache:
        _calendar_cache[key] = xcals.get_calendar(key)
    return _calendar_cache[key]


def _fmt_duration(total_min: int) -> str:
    h, m = divmod(total_min, 60)
    d, h = divmod(h, 24)
    parts = []
    if d > 0:
        parts.append(f"{d}d")
    if h > 0:
        parts.append(f"{h}h")
    if m > 0 and d == 0:
        parts.append(f"{m}m")
    return " ".join(parts) or "0m"


def _get_market_status(group: dict) -> dict:
    """Compute current market status for a group using exchange_calendars."""
    from zoneinfo import ZoneInfo

    cal = _get_calendar(group["calendar_key"])
    tz = ZoneInfo(group["tz"])
    now = datetime.now(tz)
    today = now.date()
    today_ts = today.isoformat()

    # Check if today is a trading session
    is_session = cal.is_session(today_ts)

    if is_session:
        # Get open/close times for today (may be early close)
        open_time = cal.session_open(today_ts).to_pydatetime()
        close_time = cal.session_close(today_ts).to_pydatetime()

        # Ensure timezone-aware comparison
        now_utc = now.astimezone(ZoneInfo("UTC"))
        open_utc = open_time.astimezone(ZoneInfo("UTC"))
        close_utc = close_time.astimezone(ZoneInfo("UTC"))

        if open_utc <= now_utc < close_utc:
            mins_left = int((close_utc - now_utc).total_seconds() / 60)
            return {
                "label": group["label"],
                "status": "open",
                "tooltip": f"Closes in {_fmt_duration(mins_left)}",
            }

        # Pre-market check (US only)
        if group["pre_market_hour"] is not None:
            pre_open = now.replace(
                hour=group["pre_market_hour"], minute=0, second=0, microsecond=0
            )
            if pre_open <= now < open_time.astimezone(tz):
                mins_to_open = int(
                    (open_time.astimezone(tz) - now).total_seconds() / 60
                )
                return {
                    "label": group["label"],
                    "status": "pre-market",
                    "tooltip": f"Opens in {_fmt_duration(mins_to_open)}",
                }

        # After-hours check (US only)
        if group["after_hours_end_hour"] is not None:
            after_end = now.replace(
                hour=group["after_hours_end_hour"],
                minute=0,
                second=0,
                microsecond=0,
            )
            if close_time.astimezone(tz) <= now < after_end:
                return {
                    "label": group["label"],
                    "status": "after-hours",
                    "tooltip": f"After-hours until {group['after_hours_end_hour']}:00",
                }

        # Before open today
        if now_utc < open_utc:
            mins_to_open = int((open_utc - now_utc).total_seconds() / 60)
            return {
                "label": group["label"],
                "status": "closed",
                "tooltip": f"Opens in {_fmt_duration(mins_to_open)}",
            }

    # Market is closed — find next trading session
    search_date = today + timedelta(days=1) if is_session else today
    for i in range(14):
        check = (search_date + timedelta(days=i)).isoformat()
        try:
            if cal.is_session(check):
                next_open = cal.session_open(check).to_pydatetime()
                next_open_local = next_open.astimezone(tz)
                day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                day_name = day_names[next_open_local.weekday()]
                open_str = next_open_local.strftime("%H:%M")

                mins_away = int((next_open.astimezone(ZoneInfo("UTC")) - now.astimezone(ZoneInfo("UTC"))).total_seconds() / 60)
                return {
                    "label": group["label"],
                    "status": "closed",
                    "tooltip": f"Opens in {_fmt_duration(mins_away)}",
                }
        except Exception:
            continue

    return {
        "label": group["label"],
        "status": "closed",
        "tooltip": "Schedule unavailable",
    }


@router.get("/status")
async def market_status(session: AsyncSession = Depends(get_session)):
    """Return market status for all exchange groups that have tracked securities."""
    # Find which exchanges are in use
    result = await session.execute(
        select(Security.exchange, Security.asset_class).where(
            Security.is_active == True  # noqa: E712
        )
    )
    rows = result.all()
    exchanges = {r.exchange for r in rows if r.exchange}
    has_crypto = any(r.asset_class == "crypto" for r in rows)

    # Filter to groups with active securities
    active = []
    for group in MARKET_GROUPS:
        if any(mic in exchanges for mic in group["mics"]):
            active.append(_get_market_status(group))

    if has_crypto:
        active.append({
            "label": "Crypto",
            "status": "open",
            "tooltip": "24/7 market",
        })

    return {"data": active}
