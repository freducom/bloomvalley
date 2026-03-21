"""Security fundamentals — DCF, P/B, short interest, smart money, earnings reports."""

from datetime import date, datetime, timezone
from decimal import Decimal

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.db.engine import async_session
from app.db.models.fundamentals import SecurityFundamentals, EarningsReport
from app.db.models.securities import Security
from app.db.models.prices import Price

logger = structlog.get_logger()

router = APIRouter()


# ── Pydantic models ──

class FundamentalsUpsert(BaseModel):
    security_id: int
    price_to_book: float | None = None
    free_cash_flow_cents: int | None = None
    fcf_currency: str | None = None
    dcf_value_cents: int | None = None
    dcf_discount_rate: float | None = None
    dcf_terminal_growth: float | None = None
    dcf_model_notes: str | None = None
    short_interest_pct: float | None = None
    short_interest_change_pct: float | None = None
    short_squeeze_risk: str | None = None  # low, medium, high
    days_to_cover: float | None = None
    institutional_ownership_pct: float | None = None
    institutional_flow: str | None = None  # accumulating, distributing, neutral
    smart_money_signal: str | None = None
    smart_money_outlook_days: int | None = 90


class EarningsReportCreate(BaseModel):
    security_id: int
    fiscal_quarter: str  # e.g. "Q1 2026"
    fiscal_year: int
    quarter: int  # 1-4
    report_date: str | None = None
    revenue_cents: int | None = None
    revenue_currency: str | None = None
    revenue_yoy_pct: float | None = None
    eps_cents: int | None = None
    eps_yoy_pct: float | None = None
    gross_margin_pct: float | None = None
    operating_margin_pct: float | None = None
    forward_guidance: str | None = None
    red_flags: str | None = None
    recommendation: str | None = None  # buy, hold, sell
    recommendation_reasoning: str | None = None
    source: str | None = None


# ── Helpers ──

def _fundamentals_to_dict(f: SecurityFundamentals, sec: Security, current_price: int | None = None) -> dict:
    # Calculate DCF upside/downside
    dcf_upside = None
    if f.dcf_value_cents and current_price and current_price > 0:
        dcf_upside = round((f.dcf_value_cents - current_price) / current_price * 100, 2)

    return {
        "id": f.id,
        "securityId": f.security_id,
        "ticker": sec.ticker,
        "securityName": sec.name,
        "assetClass": sec.asset_class,
        "currency": sec.currency,
        # Valuation
        "priceToBook": float(f.price_to_book) if f.price_to_book is not None else None,
        "freeCashFlowCents": f.free_cash_flow_cents,
        "fcfCurrency": f.fcf_currency,
        "dcfValueCents": f.dcf_value_cents,
        "dcfDiscountRate": float(f.dcf_discount_rate) if f.dcf_discount_rate is not None else None,
        "dcfTerminalGrowth": float(f.dcf_terminal_growth) if f.dcf_terminal_growth is not None else None,
        "dcfModelNotes": f.dcf_model_notes,
        "dcfUpsidePct": dcf_upside,
        "currentPriceCents": current_price,
        # Short interest
        "shortInterestPct": float(f.short_interest_pct) if f.short_interest_pct is not None else None,
        "shortInterestChangePct": float(f.short_interest_change_pct) if f.short_interest_change_pct is not None else None,
        "shortSqueezeRisk": f.short_squeeze_risk,
        "daysToCover": float(f.days_to_cover) if f.days_to_cover is not None else None,
        # Institutional
        "institutionalOwnershipPct": float(f.institutional_ownership_pct) if f.institutional_ownership_pct is not None else None,
        "institutionalFlow": f.institutional_flow,
        "smartMoneySignal": f.smart_money_signal,
        "smartMoneyOutlookDays": f.smart_money_outlook_days,
        "updatedAt": f.updated_at.isoformat(),
    }


def _earnings_to_dict(e: EarningsReport, sec: Security | None = None) -> dict:
    return {
        "id": e.id,
        "securityId": e.security_id,
        "ticker": sec.ticker if sec else None,
        "securityName": sec.name if sec else None,
        "fiscalQuarter": e.fiscal_quarter,
        "fiscalYear": e.fiscal_year,
        "quarter": e.quarter,
        "reportDate": e.report_date.isoformat() if e.report_date else None,
        "revenueCents": e.revenue_cents,
        "revenueCurrency": e.revenue_currency,
        "revenueYoyPct": float(e.revenue_yoy_pct) if e.revenue_yoy_pct is not None else None,
        "epsCents": e.eps_cents,
        "epsYoyPct": float(e.eps_yoy_pct) if e.eps_yoy_pct is not None else None,
        "grossMarginPct": float(e.gross_margin_pct) if e.gross_margin_pct is not None else None,
        "operatingMarginPct": float(e.operating_margin_pct) if e.operating_margin_pct is not None else None,
        "forwardGuidance": e.forward_guidance,
        "redFlags": e.red_flags,
        "recommendation": e.recommendation,
        "recommendationReasoning": e.recommendation_reasoning,
        "source": e.source,
        "updatedAt": e.updated_at.isoformat(),
    }


# ── Fundamentals endpoints ──

@router.get("")
async def list_fundamentals(
    security_id: int | None = Query(None, alias="securityId"),
    has_dcf: bool | None = Query(None, alias="hasDcf"),
    has_short_interest: bool | None = Query(None, alias="hasShortInterest"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List security fundamentals with optional filters."""
    async with async_session() as session:
        query = (
            select(SecurityFundamentals, Security)
            .join(Security, SecurityFundamentals.security_id == Security.id)
            .order_by(Security.ticker)
        )
        if security_id:
            query = query.where(SecurityFundamentals.security_id == security_id)
        if has_dcf:
            query = query.where(SecurityFundamentals.dcf_value_cents.isnot(None))
        if has_short_interest:
            query = query.where(SecurityFundamentals.short_interest_pct.isnot(None))

        count_q = select(func.count()).select_from(query.subquery())
        total = (await session.execute(count_q)).scalar_one()

        result = await session.execute(query.offset(offset).limit(limit))
        rows = result.all()

        # Get current prices
        prices: dict[int, int] = {}
        for f, sec in rows:
            pr = await session.execute(
                select(Price.close_cents)
                .where(Price.security_id == f.security_id)
                .order_by(Price.date.desc())
                .limit(1)
            )
            p = pr.scalar_one_or_none()
            if p:
                prices[f.security_id] = p

    data = [_fundamentals_to_dict(f, sec, prices.get(f.security_id)) for f, sec in rows]
    return {
        "data": data,
        "pagination": {"total": total, "limit": limit, "offset": offset},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/security/{security_id}")
async def get_fundamentals(security_id: int):
    """Get fundamentals for a specific security."""
    async with async_session() as session:
        result = await session.execute(
            select(SecurityFundamentals).where(SecurityFundamentals.security_id == security_id)
        )
        f = result.scalar_one_or_none()
        sec = await session.get(Security, security_id)
        if not sec:
            raise HTTPException(404, "Security not found")

        current_price = None
        pr = await session.execute(
            select(Price.close_cents)
            .where(Price.security_id == security_id)
            .order_by(Price.date.desc())
            .limit(1)
        )
        current_price = pr.scalar_one_or_none()

    if not f:
        return {
            "data": None,
            "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
        }

    return {
        "data": _fundamentals_to_dict(f, sec, current_price),
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.post("")
async def upsert_fundamentals(body: FundamentalsUpsert):
    """Create or update fundamentals for a security (upsert)."""
    async with async_session() as session:
        sec = await session.get(Security, body.security_id)
        if not sec:
            raise HTTPException(404, "Security not found")

        result = await session.execute(
            select(SecurityFundamentals).where(SecurityFundamentals.security_id == body.security_id)
        )
        f = result.scalar_one_or_none()

        if f:
            # Update existing
            for field in [
                "price_to_book", "free_cash_flow_cents", "fcf_currency",
                "dcf_value_cents", "dcf_discount_rate", "dcf_terminal_growth", "dcf_model_notes",
                "short_interest_pct", "short_interest_change_pct", "short_squeeze_risk", "days_to_cover",
                "institutional_ownership_pct", "institutional_flow",
                "smart_money_signal", "smart_money_outlook_days",
            ]:
                val = getattr(body, field)
                if val is not None:
                    if field in ("price_to_book", "dcf_discount_rate", "dcf_terminal_growth",
                                 "short_interest_pct", "short_interest_change_pct", "days_to_cover",
                                 "institutional_ownership_pct"):
                        setattr(f, field, Decimal(str(val)))
                    else:
                        setattr(f, field, val)
        else:
            # Create new
            f = SecurityFundamentals(
                security_id=body.security_id,
                price_to_book=Decimal(str(body.price_to_book)) if body.price_to_book is not None else None,
                free_cash_flow_cents=body.free_cash_flow_cents,
                fcf_currency=body.fcf_currency,
                dcf_value_cents=body.dcf_value_cents,
                dcf_discount_rate=Decimal(str(body.dcf_discount_rate)) if body.dcf_discount_rate is not None else None,
                dcf_terminal_growth=Decimal(str(body.dcf_terminal_growth)) if body.dcf_terminal_growth is not None else None,
                dcf_model_notes=body.dcf_model_notes,
                short_interest_pct=Decimal(str(body.short_interest_pct)) if body.short_interest_pct is not None else None,
                short_interest_change_pct=Decimal(str(body.short_interest_change_pct)) if body.short_interest_change_pct is not None else None,
                short_squeeze_risk=body.short_squeeze_risk,
                days_to_cover=Decimal(str(body.days_to_cover)) if body.days_to_cover is not None else None,
                institutional_ownership_pct=Decimal(str(body.institutional_ownership_pct)) if body.institutional_ownership_pct is not None else None,
                institutional_flow=body.institutional_flow,
                smart_money_signal=body.smart_money_signal,
                smart_money_outlook_days=body.smart_money_outlook_days,
            )
            session.add(f)

        await session.commit()
        await session.refresh(f)

        current_price = None
        pr = await session.execute(
            select(Price.close_cents)
            .where(Price.security_id == body.security_id)
            .order_by(Price.date.desc())
            .limit(1)
        )
        current_price = pr.scalar_one_or_none()

    return {
        "data": _fundamentals_to_dict(f, sec, current_price),
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


# ── Earnings endpoints ──

@router.get("/earnings")
async def list_earnings(
    security_id: int | None = Query(None, alias="securityId"),
    fiscal_year: int | None = Query(None, alias="fiscalYear"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List earnings reports with filters."""
    async with async_session() as session:
        query = (
            select(EarningsReport, Security)
            .join(Security, EarningsReport.security_id == Security.id)
            .order_by(EarningsReport.fiscal_year.desc(), EarningsReport.quarter.desc())
        )
        if security_id:
            query = query.where(EarningsReport.security_id == security_id)
        if fiscal_year:
            query = query.where(EarningsReport.fiscal_year == fiscal_year)

        count_q = select(func.count()).select_from(query.subquery())
        total = (await session.execute(count_q)).scalar_one()

        result = await session.execute(query.offset(offset).limit(limit))
        rows = result.all()

    return {
        "data": [_earnings_to_dict(e, sec) for e, sec in rows],
        "pagination": {"total": total, "limit": limit, "offset": offset},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/earnings/security/{security_id}")
async def get_security_earnings(security_id: int):
    """Get all earnings reports for a specific security."""
    async with async_session() as session:
        sec = await session.get(Security, security_id)
        if not sec:
            raise HTTPException(404, "Security not found")

        result = await session.execute(
            select(EarningsReport)
            .where(EarningsReport.security_id == security_id)
            .order_by(EarningsReport.fiscal_year.desc(), EarningsReport.quarter.desc())
        )
        reports = result.scalars().all()

    return {
        "data": [_earnings_to_dict(e, sec) for e in reports],
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.post("/earnings")
async def create_earnings_report(body: EarningsReportCreate):
    """Create or update an earnings report (upsert by security + year + quarter)."""
    async with async_session() as session:
        sec = await session.get(Security, body.security_id)
        if not sec:
            raise HTTPException(404, "Security not found")

        # Check for existing
        existing = await session.execute(
            select(EarningsReport).where(
                EarningsReport.security_id == body.security_id,
                EarningsReport.fiscal_year == body.fiscal_year,
                EarningsReport.quarter == body.quarter,
            )
        )
        report = existing.scalar_one_or_none()

        if report:
            # Update
            for field in [
                "fiscal_quarter", "report_date", "revenue_cents", "revenue_currency",
                "revenue_yoy_pct", "eps_cents", "eps_yoy_pct",
                "gross_margin_pct", "operating_margin_pct",
                "forward_guidance", "red_flags",
                "recommendation", "recommendation_reasoning", "source",
            ]:
                val = getattr(body, field)
                if val is not None:
                    if field == "report_date":
                        setattr(report, field, date.fromisoformat(val))
                    elif field in ("revenue_yoy_pct", "eps_yoy_pct", "gross_margin_pct", "operating_margin_pct"):
                        setattr(report, field, Decimal(str(val)))
                    else:
                        setattr(report, field, val)
        else:
            report = EarningsReport(
                security_id=body.security_id,
                fiscal_quarter=body.fiscal_quarter,
                fiscal_year=body.fiscal_year,
                quarter=body.quarter,
                report_date=date.fromisoformat(body.report_date) if body.report_date else None,
                revenue_cents=body.revenue_cents,
                revenue_currency=body.revenue_currency,
                revenue_yoy_pct=Decimal(str(body.revenue_yoy_pct)) if body.revenue_yoy_pct is not None else None,
                eps_cents=body.eps_cents,
                eps_yoy_pct=Decimal(str(body.eps_yoy_pct)) if body.eps_yoy_pct is not None else None,
                gross_margin_pct=Decimal(str(body.gross_margin_pct)) if body.gross_margin_pct is not None else None,
                operating_margin_pct=Decimal(str(body.operating_margin_pct)) if body.operating_margin_pct is not None else None,
                forward_guidance=body.forward_guidance,
                red_flags=body.red_flags,
                recommendation=body.recommendation,
                recommendation_reasoning=body.recommendation_reasoning,
                source=body.source,
            )
            session.add(report)

        await session.commit()
        await session.refresh(report)

    return {
        "data": _earnings_to_dict(report, sec),
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }
