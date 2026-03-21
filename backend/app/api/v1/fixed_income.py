"""Fixed income portfolio — bond tracking, yield calculations, ladder, income projections."""

from datetime import date, datetime, timezone
from decimal import Decimal

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func

from app.db.engine import async_session
from app.db.models.bonds import Bond
from app.db.models.securities import Security
from app.db.models.prices import Price
from app.services.bond_calculator import (
    calculate_annual_coupon_cents,
    calculate_current_yield,
    calculate_ytm,
    project_income_stream,
)

logger = structlog.get_logger()

router = APIRouter()

# Glidepath targets — shared with risk.py
GLIDEPATH = {
    45: {"equity": 0.75, "fixed_income": 0.15, "crypto": 0.07, "cash": 0.03},
    50: {"equity": 0.65, "fixed_income": 0.22, "crypto": 0.06, "cash": 0.07},
    55: {"equity": 0.50, "fixed_income": 0.38, "crypto": 0.04, "cash": 0.08},
    60: {"equity": 0.30, "fixed_income": 0.60, "crypto": 0.02, "cash": 0.08},
}


class BondCreate(BaseModel):
    # Security fields (create security + bond together)
    ticker: str
    name: str
    currency: str = "EUR"
    isin: str | None = None
    exchange: str | None = None
    # Bond-specific
    issuer: str
    issuer_type: str = "government"  # government, corporate, municipal, supranational
    coupon_rate: float | None = None
    coupon_frequency: str = "annual"  # annual, semi_annual, quarterly, zero_coupon
    face_value_cents: int
    issue_date: str | None = None
    maturity_date: str
    call_date: str | None = None
    purchase_price_cents: int | None = None
    purchase_date: str | None = None
    quantity: float = 1.0
    credit_rating: str | None = None
    rating_agency: str | None = None
    is_inflation_linked: bool = False
    is_callable: bool = False
    notes: str | None = None


class BondUpdate(BaseModel):
    coupon_rate: float | None = None
    purchase_price_cents: int | None = None
    quantity: float | None = None
    credit_rating: str | None = None
    rating_agency: str | None = None
    is_inflation_linked: bool | None = None
    is_callable: bool | None = None
    call_date: str | None = None
    notes: str | None = None


def _bond_to_dict(b: Bond, sec: Security, market_price: int | None = None) -> dict:
    today = date.today()
    days_to_maturity = (b.maturity_date - today).days
    years_to_maturity = max(days_to_maturity / 365.25, 0)

    # Calculate yields
    ytm = None
    cur_yield = None
    price_for_yield = market_price or b.purchase_price_cents
    if price_for_yield and b.face_value_cents:
        ytm = calculate_ytm(
            b.face_value_cents, price_for_yield,
            b.coupon_rate, b.coupon_frequency, years_to_maturity,
        )
        cur_yield = calculate_current_yield(b.coupon_rate, b.face_value_cents, price_for_yield)

    annual_income = calculate_annual_coupon_cents(
        b.face_value_cents, b.coupon_rate, b.quantity,
    )
    market_value = int(float(b.quantity) * (market_price or b.purchase_price_cents or b.face_value_cents))

    return {
        "id": b.id,
        "securityId": b.security_id,
        "ticker": sec.ticker,
        "name": sec.name,
        "isin": sec.isin,
        "issuer": b.issuer,
        "issuerType": b.issuer_type,
        "couponRate": float(b.coupon_rate) if b.coupon_rate else None,
        "couponFrequency": b.coupon_frequency,
        "faceValueCents": b.face_value_cents,
        "currency": b.currency,
        "issueDate": b.issue_date.isoformat() if b.issue_date else None,
        "maturityDate": b.maturity_date.isoformat(),
        "callDate": b.call_date.isoformat() if b.call_date else None,
        "purchasePriceCents": b.purchase_price_cents,
        "purchaseDate": b.purchase_date.isoformat() if b.purchase_date else None,
        "quantity": float(b.quantity),
        "yieldToMaturity": round(ytm * 100, 3) if ytm is not None else None,
        "currentYield": round(cur_yield * 100, 3) if cur_yield is not None else None,
        "creditRating": b.credit_rating,
        "ratingAgency": b.rating_agency,
        "isInflationLinked": b.is_inflation_linked,
        "isCallable": b.is_callable,
        "daysToMaturity": max(days_to_maturity, 0),
        "yearsToMaturity": round(years_to_maturity, 2),
        "annualIncomeCents": annual_income,
        "marketValueCents": market_value,
        "marketPriceCents": market_price,
        "notes": b.notes,
    }


@router.get("/portfolio")
async def get_bond_portfolio():
    """List all bond holdings with computed metrics."""
    async with async_session() as session:
        result = await session.execute(
            select(Bond, Security)
            .join(Security, Bond.security_id == Security.id)
            .order_by(Bond.maturity_date)
        )
        rows = result.all()

        # Get market prices
        prices: dict[int, int] = {}
        for bond, sec in rows:
            price_result = await session.execute(
                select(Price.close_cents)
                .where(Price.security_id == bond.security_id)
                .order_by(Price.date.desc())
                .limit(1)
            )
            p = price_result.scalar_one_or_none()
            if p:
                prices[bond.security_id] = p

    data = [_bond_to_dict(b, sec, prices.get(b.security_id)) for b, sec in rows]
    return {
        "data": data,
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/summary")
async def get_bond_summary():
    """Aggregate fixed income metrics."""
    async with async_session() as session:
        result = await session.execute(
            select(Bond, Security)
            .join(Security, Bond.security_id == Security.id)
        )
        rows = result.all()

    if not rows:
        return {
            "data": {
                "totalFaceValueCents": 0,
                "totalMarketValueCents": 0,
                "weightedAvgYtm": None,
                "weightedAvgCoupon": None,
                "totalAnnualIncomeCents": 0,
                "bondCount": 0,
                "byIssuerType": {},
                "avgCreditRating": None,
            },
            "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
        }

    total_face = 0
    total_market = 0
    total_income = 0
    ytm_weighted_sum = 0.0
    coupon_weighted_sum = 0.0
    weight_sum = 0
    by_issuer_type: dict[str, dict] = {}
    ratings: list[str] = []

    today = date.today()

    for bond, sec in rows:
        face = int(float(bond.quantity) * bond.face_value_cents)
        market = int(float(bond.quantity) * (bond.purchase_price_cents or bond.face_value_cents))
        income = calculate_annual_coupon_cents(bond.face_value_cents, bond.coupon_rate, bond.quantity)
        years = max((bond.maturity_date - today).days / 365.25, 0.01)

        total_face += face
        total_market += market
        total_income += income

        if bond.coupon_rate:
            coupon_weighted_sum += float(bond.coupon_rate) * face
        weight_sum += face

        ytm = calculate_ytm(
            bond.face_value_cents,
            bond.purchase_price_cents or bond.face_value_cents,
            bond.coupon_rate, bond.coupon_frequency, years,
        )
        if ytm is not None:
            ytm_weighted_sum += ytm * face

        if bond.credit_rating:
            ratings.append(bond.credit_rating)

        it = bond.issuer_type
        if it not in by_issuer_type:
            by_issuer_type[it] = {"count": 0, "faceValueCents": 0, "annualIncomeCents": 0}
        by_issuer_type[it]["count"] += 1
        by_issuer_type[it]["faceValueCents"] += face
        by_issuer_type[it]["annualIncomeCents"] += income

    avg_ytm = (ytm_weighted_sum / weight_sum * 100) if weight_sum > 0 else None
    avg_coupon = (coupon_weighted_sum / weight_sum * 100) if weight_sum > 0 else None

    return {
        "data": {
            "totalFaceValueCents": total_face,
            "totalMarketValueCents": total_market,
            "weightedAvgYtm": round(avg_ytm, 3) if avg_ytm is not None else None,
            "weightedAvgCoupon": round(avg_coupon, 3) if avg_coupon is not None else None,
            "totalAnnualIncomeCents": total_income,
            "bondCount": len(rows),
            "byIssuerType": by_issuer_type,
            "avgCreditRating": ratings[0] if len(ratings) == 1 else (ratings[len(ratings) // 2] if ratings else None),
        },
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/ladder")
async def get_maturity_ladder():
    """Maturity ladder bucketed visualization data."""
    buckets_def = [
        ("0-1Y", 0, 365),
        ("1-2Y", 365, 730),
        ("2-3Y", 730, 1095),
        ("3-5Y", 1095, 1825),
        ("5-7Y", 1825, 2555),
        ("7-10Y", 2555, 3650),
        ("10Y+", 3650, 999999),
    ]

    async with async_session() as session:
        result = await session.execute(
            select(Bond, Security)
            .join(Security, Bond.security_id == Security.id)
            .order_by(Bond.maturity_date)
        )
        rows = result.all()

    today = date.today()
    buckets = []
    for label, min_days, max_days in buckets_def:
        bucket_bonds = []
        for bond, sec in rows:
            days = (bond.maturity_date - today).days
            if min_days <= days < max_days:
                face = int(float(bond.quantity) * bond.face_value_cents)
                bucket_bonds.append({
                    "ticker": sec.ticker,
                    "issuer": bond.issuer,
                    "maturityDate": bond.maturity_date.isoformat(),
                    "faceValueCents": face,
                    "couponRate": float(bond.coupon_rate) if bond.coupon_rate else None,
                    "creditRating": bond.credit_rating,
                })

        total_face = sum(b["faceValueCents"] for b in bucket_bonds)
        avg_coupon = None
        if bucket_bonds:
            coupons = [b["couponRate"] for b in bucket_bonds if b["couponRate"]]
            avg_coupon = round(sum(coupons) / len(coupons), 3) if coupons else None

        buckets.append({
            "label": label,
            "count": len(bucket_bonds),
            "totalFaceValueCents": total_face,
            "avgCouponRate": avg_coupon,
            "bonds": bucket_bonds,
        })

    return {
        "data": buckets,
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/income-projection")
async def get_income_projection(
    target_monthly_cents: int = Query(300000, alias="targetMonthlyCents", description="Target monthly income at age 60 in cents"),
):
    """Project coupon income stream over 15 years toward retirement target."""
    async with async_session() as session:
        result = await session.execute(select(Bond))
        bonds = result.scalars().all()

    bond_dicts = [
        {
            "face_value_cents": b.face_value_cents,
            "coupon_rate": b.coupon_rate,
            "quantity": b.quantity,
            "maturity_date": b.maturity_date,
            "currency": b.currency,
        }
        for b in bonds
    ]

    projection = project_income_stream(bond_dicts, years_ahead=15)

    # Add target comparison
    target_annual = target_monthly_cents * 12
    for p in projection:
        p["targetAnnualCents"] = target_annual
        p["gapCents"] = target_annual - p["annualIncomeCents"]
        p["coveragePct"] = round(p["annualIncomeCents"] / target_annual * 100, 1) if target_annual > 0 else 0

    return {
        "data": {
            "projection": projection,
            "targetMonthlyCents": target_monthly_cents,
            "targetAnnualCents": target_annual,
            "currentAnnualIncomeCents": projection[0]["annualIncomeCents"] if projection else 0,
        },
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/glidepath")
async def get_glidepath_integration():
    """Fixed income allocation in context of the glidepath schedule."""
    # Import portfolio data
    from app.api.v1.risk import _get_holdings_with_values, _get_fx_rates, ASSET_CLASS_MAP
    from app.db.models.accounts import Account

    holdings = await _get_holdings_with_values()
    total_value = sum(h["marketValueEurCents"] or 0 for h in holdings)

    # Get cash
    total_cash = 0
    fx_rates = await _get_fx_rates()
    async with async_session() as session:
        acct_ids = list({h["accountId"] for h in holdings}) if holdings else []
        if acct_ids:
            res = await session.execute(select(Account).where(Account.id.in_(acct_ids)))
            for acct in res.scalars().all():
                if acct.cash_currency == "EUR":
                    total_cash += acct.cash_balance_cents
                else:
                    fx = fx_rates.get(acct.cash_currency, Decimal("1"))
                    total_cash += int(acct.cash_balance_cents / float(fx))

    portfolio_total = total_value + total_cash

    current_fi = 0
    for h in holdings:
        if ASSET_CLASS_MAP.get(h["assetClass"]) == "fixed_income":
            current_fi += h["marketValueEurCents"] or 0

    current_fi_pct = (current_fi / portfolio_total * 100) if portfolio_total > 0 else 0
    current_age = 45

    schedule = []
    for age, targets in sorted(GLIDEPATH.items()):
        target_fi_pct = targets["fixed_income"] * 100
        target_fi_cents = int(portfolio_total * targets["fixed_income"]) if portfolio_total > 0 else 0
        gap_cents = max(target_fi_cents - current_fi, 0)
        schedule.append({
            "age": age,
            "targetFixedIncomePct": round(target_fi_pct, 1),
            "targetFixedIncomeCents": target_fi_cents,
            "gapCents": gap_cents if age >= current_age else 0,
        })

    target_now = GLIDEPATH.get(current_age, GLIDEPATH[45])
    target_fi_now_cents = int(portfolio_total * target_now["fixed_income"])

    return {
        "data": {
            "currentAge": current_age,
            "currentFixedIncomeCents": current_fi,
            "currentFixedIncomePct": round(current_fi_pct, 1),
            "targetFixedIncomePct": round(target_now["fixed_income"] * 100, 1),
            "targetFixedIncomeCents": target_fi_now_cents,
            "gapCents": max(target_fi_now_cents - current_fi, 0),
            "portfolioTotalCents": portfolio_total,
            "schedule": schedule,
        },
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.post("/bonds")
async def create_bond(body: BondCreate):
    """Create a bond (creates security + bond metadata together)."""
    async with async_session() as session:
        # Check if security already exists
        existing = await session.execute(
            select(Security).where(Security.ticker == body.ticker)
        )
        sec = existing.scalar_one_or_none()

        if not sec:
            sec = Security(
                ticker=body.ticker,
                name=body.name,
                asset_class="bond",
                currency=body.currency,
                isin=body.isin,
                exchange=body.exchange,
            )
            session.add(sec)
            await session.flush()

        # Check no bond already exists for this security
        existing_bond = await session.execute(
            select(Bond).where(Bond.security_id == sec.id)
        )
        if existing_bond.scalar_one_or_none():
            raise HTTPException(409, "Bond metadata already exists for this security")

        bond = Bond(
            security_id=sec.id,
            issuer=body.issuer,
            issuer_type=body.issuer_type,
            coupon_rate=Decimal(str(body.coupon_rate)) if body.coupon_rate is not None else None,
            coupon_frequency=body.coupon_frequency,
            face_value_cents=body.face_value_cents,
            currency=body.currency,
            issue_date=date.fromisoformat(body.issue_date) if body.issue_date else None,
            maturity_date=date.fromisoformat(body.maturity_date),
            call_date=date.fromisoformat(body.call_date) if body.call_date else None,
            purchase_price_cents=body.purchase_price_cents,
            purchase_date=date.fromisoformat(body.purchase_date) if body.purchase_date else None,
            quantity=Decimal(str(body.quantity)),
            credit_rating=body.credit_rating,
            rating_agency=body.rating_agency,
            is_inflation_linked=body.is_inflation_linked,
            is_callable=body.is_callable,
            notes=body.notes,
        )
        session.add(bond)
        await session.commit()
        await session.refresh(bond)
        await session.refresh(sec)

    return {
        "data": _bond_to_dict(bond, sec),
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.put("/bonds/{bond_id}")
async def update_bond(bond_id: int, body: BondUpdate):
    """Update bond metadata."""
    async with async_session() as session:
        bond = await session.get(Bond, bond_id)
        if not bond:
            raise HTTPException(404, "Bond not found")

        if body.coupon_rate is not None:
            bond.coupon_rate = Decimal(str(body.coupon_rate))
        if body.purchase_price_cents is not None:
            bond.purchase_price_cents = body.purchase_price_cents
        if body.quantity is not None:
            bond.quantity = Decimal(str(body.quantity))
        if body.credit_rating is not None:
            bond.credit_rating = body.credit_rating
        if body.rating_agency is not None:
            bond.rating_agency = body.rating_agency
        if body.is_inflation_linked is not None:
            bond.is_inflation_linked = body.is_inflation_linked
        if body.is_callable is not None:
            bond.is_callable = body.is_callable
        if body.call_date is not None:
            bond.call_date = date.fromisoformat(body.call_date)
        if body.notes is not None:
            bond.notes = body.notes

        await session.commit()
        await session.refresh(bond)
        sec = await session.get(Security, bond.security_id)

    return {
        "data": _bond_to_dict(bond, sec),
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.delete("/bonds/{bond_id}")
async def delete_bond(bond_id: int):
    """Delete bond metadata (keeps the security)."""
    async with async_session() as session:
        bond = await session.get(Bond, bond_id)
        if not bond:
            raise HTTPException(404, "Bond not found")
        await session.delete(bond)
        await session.commit()

    return {
        "data": {"deleted": True, "id": bond_id},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }
