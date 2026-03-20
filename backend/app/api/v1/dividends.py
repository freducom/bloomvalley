"""Dividend endpoints — calendar, history, income projections, yield metrics."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import structlog
from fastapi import APIRouter, Query
from sqlalchemy import func, select, case, literal_column

from app.db.engine import async_session
from app.db.models.dividends import DividendEvent
from app.db.models.securities import Security
from app.db.models.transactions import Transaction
from app.db.models.accounts import Account
from app.db.models.prices import FxRate
from app.api.v1.portfolio import _get_fx_rates, _get_latest_prices

logger = structlog.get_logger()

router = APIRouter()


async def _get_held_security_ids() -> dict[int, dict]:
    """Get securities with positive holdings. Returns {security_id: {qty, account_ids}}."""
    async with async_session() as session:
        qty_case = case(
            (Transaction.type.in_(["buy", "transfer_in"]), Transaction.quantity),
            (Transaction.type.in_(["sell", "transfer_out"]), -Transaction.quantity),
            else_=literal_column("0"),
        )
        result = await session.execute(
            select(
                Transaction.security_id,
                func.sum(qty_case).label("qty"),
            )
            .where(
                Transaction.security_id.isnot(None),
                Transaction.type.in_(["buy", "sell", "transfer_in", "transfer_out"]),
            )
            .group_by(Transaction.security_id)
            .having(func.sum(qty_case) > 0)
        )
        return {r.security_id: {"qty": float(r.qty)} for r in result.all()}


@router.get("/upcoming")
async def upcoming_dividends(
    days: int = Query(90, ge=1, le=365),
):
    """Upcoming dividend events for held securities."""
    holdings = await _get_held_security_ids()
    if not holdings:
        return {"data": [], "meta": {"timestamp": datetime.now(timezone.utc).isoformat()}}

    today = date.today()
    end = today + timedelta(days=days)

    async with async_session() as session:
        result = await session.execute(
            select(DividendEvent, Security)
            .join(Security, DividendEvent.security_id == Security.id)
            .where(
                DividendEvent.security_id.in_(list(holdings.keys())),
                DividendEvent.ex_date >= today,
                DividendEvent.ex_date <= end,
            )
            .order_by(DividendEvent.ex_date)
        )
        rows = result.all()

    prices = await _get_latest_prices()
    fx_rates = await _get_fx_rates()

    data = []
    for event, sec in rows:
        qty = Decimal(str(holdings[sec.id]["qty"]))
        total_cents = int(event.amount_cents * qty)

        # Current yield
        price_data = prices.get(sec.id)
        current_yield = None
        if price_data and price_data["close_cents"] > 0 and event.frequency:
            freq_mult = {"quarterly": 4, "semi_annual": 2, "annual": 1, "monthly": 12}.get(event.frequency, 1)
            annual_div = event.amount_cents * freq_mult
            current_yield = round((annual_div / price_data["close_cents"]) * 100, 2)

        # Convert to EUR
        total_eur_cents = total_cents
        if event.currency != "EUR":
            fx = fx_rates.get(event.currency)
            if fx:
                total_eur_cents = int(total_cents / float(fx))

        data.append({
            "securityId": sec.id,
            "ticker": sec.ticker,
            "name": sec.name,
            "exDate": event.ex_date.isoformat(),
            "paymentDate": event.payment_date.isoformat() if event.payment_date else None,
            "amountPerShareCents": event.amount_cents,
            "currency": event.currency,
            "frequency": event.frequency,
            "sharesHeld": str(qty),
            "totalCents": total_cents,
            "totalEurCents": total_eur_cents,
            "currentYield": current_yield,
        })

    return {"data": data, "meta": {"timestamp": datetime.now(timezone.utc).isoformat()}}


@router.get("/history")
async def dividend_history(
    security_id: int | None = Query(None, alias="securityId"),
    year: int | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
):
    """Historical dividend events, optionally filtered."""
    query = (
        select(DividendEvent, Security)
        .join(Security, DividendEvent.security_id == Security.id)
        .order_by(DividendEvent.ex_date.desc())
    )

    if security_id:
        query = query.where(DividendEvent.security_id == security_id)
    if year:
        query = query.where(
            func.extract("year", DividendEvent.ex_date) == year
        )

    query = query.limit(limit)

    async with async_session() as session:
        result = await session.execute(query)
        rows = result.all()

    data = []
    for event, sec in rows:
        data.append({
            "securityId": sec.id,
            "ticker": sec.ticker,
            "name": sec.name,
            "exDate": event.ex_date.isoformat(),
            "paymentDate": event.payment_date.isoformat() if event.payment_date else None,
            "amountPerShareCents": event.amount_cents,
            "currency": event.currency,
            "frequency": event.frequency,
        })

    return {"data": data, "meta": {"timestamp": datetime.now(timezone.utc).isoformat()}}


@router.get("/yield-metrics")
async def yield_metrics():
    """Portfolio-level dividend yield metrics."""
    holdings = await _get_held_security_ids()
    if not holdings:
        return {
            "data": {
                "portfolioDividendYield": None,
                "yieldOnCost": None,
                "annualDividendIncomeCents": 0,
                "monthlyBreakdown": [],
                "byHolding": [],
            },
            "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
        }

    sec_ids = list(holdings.keys())
    prices = await _get_latest_prices()
    fx_rates = await _get_fx_rates()

    # Get latest dividend event per security to estimate annual dividend
    async with async_session() as session:
        # Get most recent dividend event per security
        subq = (
            select(
                DividendEvent.security_id,
                func.max(DividendEvent.ex_date).label("max_date"),
            )
            .where(DividendEvent.security_id.in_(sec_ids))
            .group_by(DividendEvent.security_id)
            .subquery()
        )
        result = await session.execute(
            select(DividendEvent, Security)
            .join(Security, DividendEvent.security_id == Security.id)
            .join(
                subq,
                (DividendEvent.security_id == subq.c.security_id)
                & (DividendEvent.ex_date == subq.c.max_date),
            )
        )
        latest_events = {event.security_id: (event, sec) for event, sec in result.all()}

        # Get all events from last 12 months for monthly breakdown
        one_year_ago = date.today() - timedelta(days=365)
        result = await session.execute(
            select(DividendEvent)
            .where(
                DividendEvent.security_id.in_(sec_ids),
                DividendEvent.ex_date >= one_year_ago,
            )
            .order_by(DividendEvent.ex_date)
        )
        recent_events = result.scalars().all()

    # Get cost basis per security
    async with async_session() as session:
        cost_case = case(
            (Transaction.type.in_(["buy", "transfer_in"]), Transaction.total_cents),
            (Transaction.type.in_(["sell", "transfer_out"]), -Transaction.total_cents),
            else_=literal_column("0"),
        )
        result = await session.execute(
            select(
                Transaction.security_id,
                func.sum(cost_case).label("cost"),
            )
            .where(
                Transaction.security_id.in_(sec_ids),
                Transaction.type.in_(["buy", "sell", "transfer_in", "transfer_out"]),
            )
            .group_by(Transaction.security_id)
        )
        cost_basis = {r.security_id: int(r.cost or 0) for r in result.all()}

        # Load securities for those without events
        sec_result = await session.execute(
            select(Security).where(Security.id.in_(sec_ids))
        )
        all_securities = {s.id: s for s in sec_result.scalars().all()}

    total_annual_div_eur = 0
    total_market_value_eur = 0
    total_cost_eur = 0
    by_holding = []

    for sid, h in holdings.items():
        qty = Decimal(str(h["qty"]))
        sec = all_securities.get(sid)
        if not sec:
            continue

        # Market value in EUR
        price_data = prices.get(sid)
        market_value_eur = 0
        if price_data:
            mv = int(price_data["close_cents"] * float(qty))
            ccy = price_data["currency"]
            if ccy == "EUR":
                market_value_eur = mv
            else:
                fx = fx_rates.get(ccy, Decimal("1"))
                market_value_eur = int(mv / float(fx))

        # Cost in EUR
        cost_eur = cost_basis.get(sid, 0)
        if sec.currency != "EUR":
            fx = fx_rates.get(sec.currency, Decimal("1"))
            cost_eur = int(cost_eur / float(fx))

        total_market_value_eur += market_value_eur
        total_cost_eur += cost_eur

        # Annual dividend estimate
        annual_div_eur = 0
        div_yield = None
        yoc = None

        if sid in latest_events:
            event, _ = latest_events[sid]
            freq_mult = {"quarterly": 4, "semi_annual": 2, "annual": 1, "monthly": 12}.get(event.frequency, 1)
            annual_div_cents = int(event.amount_cents * freq_mult * float(qty))

            # Convert to EUR
            if event.currency == "EUR":
                annual_div_eur = annual_div_cents
            else:
                fx = fx_rates.get(event.currency, Decimal("1"))
                annual_div_eur = int(annual_div_cents / float(fx))

            total_annual_div_eur += annual_div_eur

            if market_value_eur > 0:
                div_yield = round((annual_div_eur / market_value_eur) * 100, 2)
            if cost_eur > 0:
                yoc = round((annual_div_eur / cost_eur) * 100, 2)

        by_holding.append({
            "securityId": sid,
            "ticker": sec.ticker,
            "name": sec.name,
            "sharesHeld": str(qty),
            "annualDividendEurCents": annual_div_eur,
            "dividendYield": div_yield,
            "yieldOnCost": yoc,
            "frequency": latest_events[sid][0].frequency if sid in latest_events else None,
        })

    # Sort by annual dividend descending
    by_holding.sort(key=lambda x: x["annualDividendEurCents"], reverse=True)

    # Monthly breakdown from recent events
    monthly: dict[str, int] = {}
    for ev in recent_events:
        month_key = ev.ex_date.strftime("%Y-%m")
        qty = Decimal(str(holdings.get(ev.security_id, {}).get("qty", 0)))
        total = int(ev.amount_cents * qty)
        if ev.currency != "EUR":
            fx = fx_rates.get(ev.currency, Decimal("1"))
            total = int(total / float(fx))
        monthly[month_key] = monthly.get(month_key, 0) + total

    monthly_list = [
        {"month": m, "amountEurCents": v}
        for m, v in sorted(monthly.items())
    ]

    portfolio_yield = round((total_annual_div_eur / total_market_value_eur) * 100, 2) if total_market_value_eur > 0 else None
    portfolio_yoc = round((total_annual_div_eur / total_cost_eur) * 100, 2) if total_cost_eur > 0 else None

    return {
        "data": {
            "portfolioDividendYield": portfolio_yield,
            "yieldOnCost": portfolio_yoc,
            "annualDividendIncomeCents": total_annual_div_eur,
            "monthlyBreakdown": monthly_list,
            "byHolding": by_holding,
        },
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/calendar")
async def dividend_calendar(
    from_date: str | None = Query(None, alias="fromDate"),
    to_date: str | None = Query(None, alias="toDate"),
):
    """Dividend events for a date range (default: next 6 months)."""
    today = date.today()
    start = date.fromisoformat(from_date) if from_date else today - timedelta(days=30)
    end = date.fromisoformat(to_date) if to_date else today + timedelta(days=180)

    holdings = await _get_held_security_ids()

    async with async_session() as session:
        query = (
            select(DividendEvent, Security)
            .join(Security, DividendEvent.security_id == Security.id)
            .where(DividendEvent.ex_date >= start, DividendEvent.ex_date <= end)
        )
        # Only show events for held securities
        if holdings:
            query = query.where(DividendEvent.security_id.in_(list(holdings.keys())))

        result = await session.execute(query.order_by(DividendEvent.ex_date))
        rows = result.all()

    data = []
    for event, sec in rows:
        qty = holdings.get(sec.id, {}).get("qty", 0)
        data.append({
            "securityId": sec.id,
            "ticker": sec.ticker,
            "name": sec.name,
            "exDate": event.ex_date.isoformat(),
            "paymentDate": event.payment_date.isoformat() if event.payment_date else None,
            "amountPerShareCents": event.amount_cents,
            "currency": event.currency,
            "frequency": event.frequency,
            "sharesHeld": str(qty) if qty else None,
            "totalCents": int(event.amount_cents * qty) if qty else None,
        })

    return {"data": data, "meta": {"timestamp": datetime.now(timezone.utc).isoformat()}}
