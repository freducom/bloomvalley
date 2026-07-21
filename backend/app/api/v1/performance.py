"""Period-scoped performance endpoint (F24)."""

from datetime import date, datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException, Query

from app.services.performance import compute_performance

logger = structlog.get_logger()

router = APIRouter()


@router.get("")
async def get_performance(
    from_date: date = Query(..., alias="fromDate", description="Start of period (inclusive)"),
    to_date: date = Query(..., alias="toDate", description="End of period (inclusive)"),
):
    """Portfolio P&L broken down into realized / dividend / unrealized buckets over the given period."""
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="fromDate must be <= toDate")

    result = await compute_performance(from_date=from_date, to_date=to_date)

    if result.get("error") == "invalid_range":
        raise HTTPException(status_code=400, detail="fromDate must be <= toDate")

    return {
        "data": result,
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fromDate": from_date.isoformat(),
            "toDate": to_date.isoformat(),
        },
    }
