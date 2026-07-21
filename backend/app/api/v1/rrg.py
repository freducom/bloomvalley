"""Relative Rotation Graph endpoint (F23)."""

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException, Query

from app.services.rrg import compute_rrg

logger = structlog.get_logger()

router = APIRouter()


@router.get("")
async def get_rrg(
    weeks: int = Query(14, ge=4, le=52, description="Rolling window in weekly bars (default 14)."),
    tail: int = Query(4, ge=1, le=13, description="Trailing weekly points returned per sector."),
):
    """S&P 500 sector Relative Rotation Graph vs SPY."""
    result = await compute_rrg(weeks=weeks, tail=tail)

    if result.get("error") == "missing_securities":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "missing_securities",
                "message": (
                    "SPY and/or one or more SPDR sector ETFs are not in the securities table. "
                    "Run `python -m scripts.seed-securities` in the backend container, then "
                    "trigger the `yahoo_daily_prices` pipeline."
                ),
                "missing": result["missing"],
            },
        )
    if result.get("error") == "insufficient_history":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "insufficient_history",
                "message": (
                    "Not enough price history to compute the RRG. "
                    "Trigger the `yahoo_daily_prices` pipeline for SPY and the SPDR sector ETFs."
                ),
                "missing": result.get("missing", []),
            },
        )

    logger.info(
        "rrg.compute",
        sectors=len(result.get("sectors", [])),
        insufficient=len(result.get("insufficientHistory") or []),
        weeks=weeks,
        tail=tail,
    )

    return {
        "data": result,
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "weeks": weeks,
            "tail": tail,
        },
    }
