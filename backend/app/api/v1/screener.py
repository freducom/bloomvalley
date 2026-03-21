"""Screener endpoints — Munger quality screen, Boglehead ETF screen, factor detail."""

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException, Query

from app.services.screener import run_munger_screen, run_etf_screen, get_security_factors

logger = structlog.get_logger()

router = APIRouter()


@router.get("/munger")
async def munger_screen(
    min_roic: float | None = Query(None, alias="minRoic", description="Min ROIC ratio (e.g. 0.15 for 15%)"),
    min_roe: float | None = Query(None, alias="minRoe", description="Min ROE ratio"),
    max_debt_equity: float | None = Query(None, alias="maxDebtEquity", description="Max Debt/Equity ratio"),
    min_fcf_yield: float | None = Query(None, alias="minFcfYield", description="Min FCF yield ratio"),
    min_gross_margin: float | None = Query(None, alias="minGrossMargin", description="Min gross margin ratio"),
    max_pe: float | None = Query(None, alias="maxPe", description="Max P/E ratio"),
    max_pfcf: float | None = Query(None, alias="maxPfcf", description="Max P/FCF ratio"),
    sort_by: str = Query("composite", alias="sortBy", description="Sort field: composite, roic, roe, pe, etc."),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Munger/Buffett quality screen — ranks stocks on 10 fundamental factors.

    Computes ROIC, ROE, D/E, 10Y earnings growth, earnings consistency,
    FCF yield, gross margin, owner-earnings growth, P/E, and P/FCF.
    Results are z-score normalised and ranked by composite score.
    Financial-sector companies exclude D/E and gross margin factors.
    """
    logger.info(
        "screener.munger",
        min_roic=min_roic, min_roe=min_roe, max_debt_equity=max_debt_equity,
        sort_by=sort_by, limit=limit, offset=offset,
    )

    data = await run_munger_screen(
        min_roic=min_roic,
        min_roe=min_roe,
        max_debt_equity=max_debt_equity,
        min_fcf_yield=min_fcf_yield,
        min_gross_margin=min_gross_margin,
        max_pe=max_pe,
        max_pfcf=max_pfcf,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
    )

    return {
        "data": data,
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/etf")
async def etf_screen(
    max_ter: float | None = Query(None, alias="maxTer", description="Max TER as decimal (e.g. 0.003 for 0.30%)"),
    min_aum: float | None = Query(None, alias="minAum", description="Min AUM in EUR (e.g. 100000000)"),
    domicile: str | None = Query(None, description="Comma-separated domicile codes (e.g. IE,LU)"),
    sort_by: str = Query("composite", alias="sortBy", description="Sort field: composite, ter, aum, trackingDifference"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Boglehead ETF screen — filters and ranks ETFs for core portfolio.

    Hard filters: accumulating distribution, physical replication, IE/LU domicile.
    Scores on TER (0.35), tracking difference (0.35), AUM (0.30).
    """
    logger.info(
        "screener.etf",
        max_ter=max_ter, min_aum=min_aum, domicile=domicile,
        sort_by=sort_by, limit=limit, offset=offset,
    )

    data = await run_etf_screen(
        max_ter=max_ter,
        min_aum=min_aum,
        domicile=domicile,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
    )

    return {
        "data": data,
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/factors/{security_id}")
async def factor_detail(security_id: int):
    """Get all computed screening factors for a single security.

    Returns Munger factors for stocks, ETF profile factors for ETFs.
    """
    logger.info("screener.factors", security_id=security_id)

    data = await get_security_factors(security_id)
    if data is None:
        raise HTTPException(404, "Security not found")

    return {
        "data": data,
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }
