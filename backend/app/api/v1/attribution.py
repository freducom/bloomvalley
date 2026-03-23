"""Brinson-Hood-Beebower return attribution endpoint."""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select, and_

from app.db.engine import async_session
from app.db.models.holdings_snapshot import HoldingsSnapshot
from app.db.models.prices import Price
from app.db.models.securities import Security

logger = structlog.get_logger()
router = APIRouter()

# Default benchmark: MSCI World via iShares ETF (IWDA.L or EUNL.DE)
# We'll look for any of these tickers in the DB
BENCHMARK_TICKERS = ["IWDA.L", "EUNL.DE", "IWDA.AS", "URTH", "VWCE.DE"]


async def _get_benchmark_security_id() -> int | None:
    """Find benchmark ETF in our securities table."""
    async with async_session() as session:
        for ticker in BENCHMARK_TICKERS:
            result = await session.execute(
                select(Security.id).where(Security.ticker == ticker)
            )
            sid = result.scalar_one_or_none()
            if sid:
                return sid
    return None


async def _get_price_on_date(security_id: int, target_date: date) -> int | None:
    """Get closing price (cents) for a security on or just before a date."""
    async with async_session() as session:
        result = await session.execute(
            select(Price.close_cents)
            .where(Price.security_id == security_id)
            .where(Price.date <= target_date)
            .order_by(Price.date.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


async def _get_snapshot_on_date(target_date: date) -> list[dict]:
    """Get holdings snapshot nearest to target_date."""
    async with async_session() as session:
        # Find nearest snapshot date <= target_date
        nearest = await session.execute(
            select(func.max(HoldingsSnapshot.snapshot_date))
            .where(HoldingsSnapshot.snapshot_date <= target_date)
        )
        snap_date = nearest.scalar_one_or_none()
        if not snap_date:
            return []

        result = await session.execute(
            select(
                HoldingsSnapshot.security_id,
                HoldingsSnapshot.market_value_eur_cents,
                HoldingsSnapshot.weight_pct,
                Security.ticker,
                Security.name,
                Security.sector,
                Security.asset_class,
            )
            .join(Security, HoldingsSnapshot.security_id == Security.id)
            .where(HoldingsSnapshot.snapshot_date == snap_date)
        )
        rows = result.all()

    return [
        {
            "security_id": r.security_id,
            "market_value_eur_cents": r.market_value_eur_cents,
            "weight_pct": float(r.weight_pct) if r.weight_pct else 0,
            "ticker": r.ticker,
            "name": r.name,
            "sector": r.sector or "Unknown",
            "asset_class": r.asset_class or "Unknown",
        }
        for r in rows
    ]


def _compute_return(start_price: int | None, end_price: int | None) -> float:
    """Compute return between two prices in cents."""
    if not start_price or not end_price or start_price == 0:
        return 0.0
    return (end_price - start_price) / start_price


@router.get("/brinson")
async def brinson_attribution(
    from_date: date = Query(..., alias="from", description="Start date"),
    to_date: date = Query(..., alias="to", description="End date"),
    group_by: str = Query("sector", description="Group by: sector or assetClass"),
):
    """
    Brinson-Hood-Beebower return attribution.

    Decomposes portfolio active return into:
    - Allocation effect: over/underweighting sectors vs benchmark
    - Selection effect: picking better/worse securities within sectors
    - Interaction effect: cross-product of allocation and selection
    """
    if from_date >= to_date:
        raise HTTPException(400, "from must be before to")

    # Get holdings snapshot at start date
    holdings = await _get_snapshot_on_date(from_date)
    if not holdings:
        raise HTTPException(404, f"No holdings snapshot found on or before {from_date}")

    # Compute total portfolio value at start
    total_value = sum(h["market_value_eur_cents"] for h in holdings)
    if total_value == 0:
        raise HTTPException(400, "Portfolio value is zero at start date")

    # Group holdings by sector/asset_class
    group_key = "sector" if group_by == "sector" else "asset_class"
    groups: dict[str, list[dict]] = {}
    for h in holdings:
        g = h[group_key]
        groups.setdefault(g, []).append(h)

    # Compute portfolio weights and returns by group
    portfolio_sectors: dict[str, dict] = {}
    for group_name, group_holdings in groups.items():
        group_value = sum(h["market_value_eur_cents"] for h in group_holdings)
        weight = group_value / total_value

        # Compute weighted return for this group
        weighted_return = 0.0
        for h in group_holdings:
            h_weight = h["market_value_eur_cents"] / group_value if group_value > 0 else 0
            start_price = await _get_price_on_date(h["security_id"], from_date)
            end_price = await _get_price_on_date(h["security_id"], to_date)
            h_return = _compute_return(start_price, end_price)
            weighted_return += h_weight * h_return

        portfolio_sectors[group_name] = {
            "weight": weight,
            "return": weighted_return,
            "holdings": len(group_holdings),
        }

    # Get benchmark return (total, not by sector — simplified)
    benchmark_id = await _get_benchmark_security_id()
    benchmark_total_return = 0.0
    benchmark_ticker = None

    if benchmark_id:
        bm_start = await _get_price_on_date(benchmark_id, from_date)
        bm_end = await _get_price_on_date(benchmark_id, to_date)
        benchmark_total_return = _compute_return(bm_start, bm_end)

        async with async_session() as session:
            result = await session.execute(
                select(Security.ticker).where(Security.id == benchmark_id)
            )
            benchmark_ticker = result.scalar_one_or_none()

    # For simplified Brinson: use equal benchmark weight across all sectors
    # (since we don't have actual benchmark sector weights for MSCI World)
    n_sectors = len(portfolio_sectors)
    benchmark_weight = 1.0 / n_sectors if n_sectors > 0 else 0
    benchmark_return_per_sector = benchmark_total_return  # Assume uniform

    # Compute BHB effects
    attribution = []
    total_allocation = 0.0
    total_selection = 0.0
    total_interaction = 0.0
    portfolio_total_return = 0.0

    for group_name, pf in portfolio_sectors.items():
        wp = pf["weight"]
        rp = pf["return"]
        wb = benchmark_weight
        rb = benchmark_return_per_sector

        allocation = (wp - wb) * rb
        selection = (rp - rb) * wb
        interaction = (wp - wb) * (rp - rb)
        active_return = allocation + selection + interaction

        total_allocation += allocation
        total_selection += selection
        total_interaction += interaction
        portfolio_total_return += wp * rp

        attribution.append({
            "group": group_name,
            "portfolioWeight": round(wp * 100, 2),
            "benchmarkWeight": round(wb * 100, 2),
            "portfolioReturn": round(rp * 100, 2),
            "benchmarkReturn": round(rb * 100, 2),
            "allocationEffect": round(allocation * 100, 4),
            "selectionEffect": round(selection * 100, 4),
            "interactionEffect": round(interaction * 100, 4),
            "activeReturn": round(active_return * 100, 4),
            "holdings": pf["holdings"],
        })

    # Sort by absolute active return (most impactful first)
    attribution.sort(key=lambda x: abs(x["activeReturn"]), reverse=True)

    return {
        "data": {
            "attribution": attribution,
            "summary": {
                "portfolioReturn": round(portfolio_total_return * 100, 2),
                "benchmarkReturn": round(benchmark_total_return * 100, 2),
                "activeReturn": round((portfolio_total_return - benchmark_total_return) * 100, 2),
                "allocationEffect": round(total_allocation * 100, 4),
                "selectionEffect": round(total_selection * 100, 4),
                "interactionEffect": round(total_interaction * 100, 4),
            },
            "benchmark": {
                "ticker": benchmark_ticker,
                "found": benchmark_id is not None,
            },
            "period": {
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
            },
            "groupBy": group_by,
        },
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }
