"""Earnings calendar and estimates endpoints."""

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query
from sqlalchemy import select, and_

from app.db.engine import async_session
from app.db.models.fundamentals import EarningsReport
from app.db.models.securities import Security

router = APIRouter()


@router.get("/calendar")
async def earnings_calendar(
    days: int = Query(90, ge=1, le=365, description="Look-ahead days"),
):
    """Get upcoming earnings dates for held securities."""
    today = date.today()
    cutoff = date.fromordinal(today.toordinal() + days)

    async with async_session() as session:
        result = await session.execute(
            select(EarningsReport, Security.ticker, Security.name)
            .join(Security, EarningsReport.security_id == Security.id)
            .where(
                and_(
                    EarningsReport.report_date.isnot(None),
                    EarningsReport.report_date >= today,
                    EarningsReport.report_date <= cutoff,
                )
            )
            .order_by(EarningsReport.report_date)
        )
        rows = result.all()

    data = []
    for report, ticker, name in rows:
        data.append({
            "securityId": report.security_id,
            "ticker": ticker,
            "name": name,
            "reportDate": report.report_date.isoformat() if report.report_date else None,
            "fiscalQuarter": report.fiscal_quarter,
            "epsEstimateCents": report.eps_estimate_cents,
            "revenueEstimateCents": report.revenue_estimate_cents,
        })

    return {
        "data": data,
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat(), "count": len(data)},
    }


@router.get("/estimates/{security_id}")
async def earnings_estimates(
    security_id: int,
    limit: int = Query(12, ge=1, le=40),
):
    """Get earnings history with estimates and surprise data for a security."""
    async with async_session() as session:
        result = await session.execute(
            select(EarningsReport)
            .where(EarningsReport.security_id == security_id)
            .order_by(EarningsReport.fiscal_year.desc(), EarningsReport.quarter.desc())
            .limit(limit)
        )
        reports = result.scalars().all()

    data = []
    for r in reports:
        data.append({
            "id": r.id,
            "fiscalQuarter": r.fiscal_quarter,
            "fiscalYear": r.fiscal_year,
            "quarter": r.quarter,
            "reportDate": r.report_date.isoformat() if r.report_date else None,
            "epsActualCents": r.eps_cents,
            "epsEstimateCents": r.eps_estimate_cents,
            "surprisePct": float(r.surprise_pct) if r.surprise_pct is not None else None,
            "revenueCents": r.revenue_cents,
            "revenueEstimateCents": r.revenue_estimate_cents,
            "revenueYoyPct": float(r.revenue_yoy_pct) if r.revenue_yoy_pct is not None else None,
            "epsYoyPct": float(r.eps_yoy_pct) if r.eps_yoy_pct is not None else None,
            "grossMarginPct": float(r.gross_margin_pct) if r.gross_margin_pct is not None else None,
            "operatingMarginPct": float(r.operating_margin_pct) if r.operating_margin_pct is not None else None,
            "source": r.source,
        })

    return {
        "data": data,
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/surprises")
async def earnings_surprises(
    limit: int = Query(20, ge=1, le=100),
):
    """Get recent earnings surprises across all held securities."""
    async with async_session() as session:
        result = await session.execute(
            select(EarningsReport, Security.ticker, Security.name)
            .join(Security, EarningsReport.security_id == Security.id)
            .where(
                and_(
                    EarningsReport.surprise_pct.isnot(None),
                    EarningsReport.eps_cents.isnot(None),
                )
            )
            .order_by(EarningsReport.report_date.desc().nullslast())
            .limit(limit)
        )
        rows = result.all()

    data = []
    for report, ticker, name in rows:
        data.append({
            "securityId": report.security_id,
            "ticker": ticker,
            "name": name,
            "fiscalQuarter": report.fiscal_quarter,
            "reportDate": report.report_date.isoformat() if report.report_date else None,
            "epsActualCents": report.eps_cents,
            "epsEstimateCents": report.eps_estimate_cents,
            "surprisePct": float(report.surprise_pct),
            "beat": report.surprise_pct > 0 if report.surprise_pct is not None else None,
        })

    return {
        "data": data,
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }
