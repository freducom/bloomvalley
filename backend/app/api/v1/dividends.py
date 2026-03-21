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

# Withholding tax rates for a Finnish tax resident by country of domicile.
# OST (osakesaastotili) holdings are tax-deferred — 0% withholding inside the wrapper.
_WHT_RATES: dict[str, float] = {
    "FI": 0.30,
    "US": 0.15,
    "SE": 0.30,
    "DE": 0.26375,
    "IE": 0.0,
    "LU": 0.0,
}
_WHT_DEFAULT = 0.30

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

    # Get TTM dividends per security for yield calculation
    one_year_ago = date.today() - timedelta(days=365)
    async with async_session() as session:
        ttm_result = await session.execute(
            select(
                DividendEvent.security_id,
                func.sum(DividendEvent.amount_cents).label("ttm_cents"),
            )
            .where(
                DividendEvent.security_id.in_(list(holdings.keys())),
                DividendEvent.ex_date >= one_year_ago,
            )
            .group_by(DividendEvent.security_id)
        )
        ttm_by_sec = {r.security_id: int(r.ttm_cents) for r in ttm_result.all()}

    data = []
    for event, sec in rows:
        qty = Decimal(str(holdings[sec.id]["qty"]))
        total_cents = int(event.amount_cents * qty)

        # Current yield based on TTM dividends / current price
        price_data = prices.get(sec.id)
        current_yield = None
        ttm = ttm_by_sec.get(sec.id)
        if price_data and price_data["close_cents"] > 0 and ttm:
            current_yield = round((ttm / price_data["close_cents"]) * 100, 2)

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

    one_year_ago = date.today() - timedelta(days=365)

    async with async_session() as session:
        # Get trailing 12-month dividends per security (sum of per-share amounts)
        result = await session.execute(
            select(
                DividendEvent.security_id,
                func.sum(DividendEvent.amount_cents).label("ttm_cents"),
                func.count(DividendEvent.id).label("event_count"),
                func.max(DividendEvent.frequency).label("frequency"),
            )
            .where(
                DividendEvent.security_id.in_(sec_ids),
                DividendEvent.ex_date >= one_year_ago,
            )
            .group_by(DividendEvent.security_id)
        )
        ttm_dividends = {
            r.security_id: {
                "ttm_cents": int(r.ttm_cents),
                "event_count": r.event_count,
                "frequency": r.frequency,
            }
            for r in result.all()
        }

        # Get all events from last 12 months for monthly breakdown
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

        # Annual dividend estimate using trailing 12-month actual dividends
        annual_div_eur = 0
        div_yield = None
        yoc = None
        frequency = None

        if sid in ttm_dividends:
            ttm = ttm_dividends[sid]
            # TTM per-share dividend * quantity = total annual dividend
            annual_div_cents = int(ttm["ttm_cents"] * float(qty))
            frequency = ttm["frequency"]

            # Convert to EUR — need to know the dividend currency
            # Find currency from recent events
            div_currency = sec.currency
            for ev in recent_events:
                if ev.security_id == sid:
                    div_currency = ev.currency
                    break

            if div_currency == "EUR":
                annual_div_eur = annual_div_cents
            else:
                fx = fx_rates.get(div_currency, Decimal("1"))
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
            "frequency": frequency,
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


# ---------------------------------------------------------------------------
# Helper: holdings with account-level detail (needed for tax-summary)
# ---------------------------------------------------------------------------

async def _get_holdings_with_accounts() -> list[dict]:
    """Return held positions with account type info.

    Each entry: {security_id, qty, account_id, account_type}.
    A single security may appear multiple times if held in different accounts.
    """
    async with async_session() as session:
        qty_case = case(
            (Transaction.type.in_(["buy", "transfer_in"]), Transaction.quantity),
            (Transaction.type.in_(["sell", "transfer_out"]), -Transaction.quantity),
            else_=literal_column("0"),
        )
        result = await session.execute(
            select(
                Transaction.account_id,
                Transaction.security_id,
                func.sum(qty_case).label("qty"),
            )
            .where(
                Transaction.security_id.isnot(None),
                Transaction.type.in_(["buy", "sell", "transfer_in", "transfer_out"]),
            )
            .group_by(Transaction.account_id, Transaction.security_id)
            .having(func.sum(qty_case) > 0)
        )
        rows = result.all()

    if not rows:
        return []

    # Load account types
    acct_ids = {r.account_id for r in rows}
    async with async_session() as session:
        acct_result = await session.execute(
            select(Account).where(Account.id.in_(acct_ids))
        )
        accounts = {a.id: a for a in acct_result.scalars().all()}

    return [
        {
            "security_id": r.security_id,
            "qty": float(r.qty),
            "account_id": r.account_id,
            "account_type": accounts[r.account_id].type if r.account_id in accounts else "regular",
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Income projection endpoint
# ---------------------------------------------------------------------------

@router.get("/income-projection")
async def income_projection(
    years: int = Query(5, ge=1, le=20),
):
    """Project annual dividend income for the next N years.

    Uses historical dividend data (up to 3 years) to compute a per-share
    annual dividend and its CAGR, then projects forward.
    """
    holdings = await _get_held_security_ids()
    if not holdings:
        return {
            "data": {
                "currentAnnualIncomeCents": 0,
                "projections": [],
                "byHolding": [],
                "byMonth": [{"month": m, "expectedIncomeCents": 0} for m in range(1, 13)],
            },
            "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
        }

    sec_ids = list(holdings.keys())
    prices = await _get_latest_prices()
    fx_rates = await _get_fx_rates()
    today = date.today()

    # Fetch up to 3 years of dividend history per security
    three_years_ago = today - timedelta(days=3 * 365)

    async with async_session() as session:
        result = await session.execute(
            select(DividendEvent, Security)
            .join(Security, DividendEvent.security_id == Security.id)
            .where(
                DividendEvent.security_id.in_(sec_ids),
                DividendEvent.ex_date >= three_years_ago,
            )
            .order_by(DividendEvent.security_id, DividendEvent.ex_date)
        )
        rows = result.all()

        # Also load securities that may have no events
        sec_result = await session.execute(
            select(Security).where(Security.id.in_(sec_ids))
        )
        all_securities = {s.id: s for s in sec_result.scalars().all()}

    # Group dividend events by security and calendar year
    # events_by_sec: {security_id: {year: total_per_share_cents}}
    events_by_sec: dict[int, dict[int, int]] = {}
    event_list_by_sec: dict[int, list[dict]] = {}
    div_currency_by_sec: dict[int, str] = {}

    for event, sec in rows:
        sid = event.security_id
        yr = event.ex_date.year
        events_by_sec.setdefault(sid, {})
        events_by_sec[sid][yr] = events_by_sec[sid].get(yr, 0) + event.amount_cents
        div_currency_by_sec[sid] = event.currency

        event_list_by_sec.setdefault(sid, [])
        event_list_by_sec[sid].append({
            "exDate": event.ex_date.isoformat(),
            "amountCents": event.amount_cents,
            "currency": event.currency,
        })

    # Build month-level breakdown from last 12 months of events
    one_year_ago = today - timedelta(days=365)
    monthly_totals: dict[int, int] = {m: 0 for m in range(1, 13)}
    for event, sec in rows:
        if event.ex_date < one_year_ago:
            continue
        qty = Decimal(str(holdings.get(event.security_id, {}).get("qty", 0)))
        total = int(event.amount_cents * qty)
        ccy = event.currency
        if ccy != "EUR":
            fx = fx_rates.get(ccy, Decimal("1"))
            total = int(total / float(fx))
        monthly_totals[event.ex_date.month] = monthly_totals.get(event.ex_date.month, 0) + total

    # Compute per-holding projection data
    by_holding: list[dict] = []
    total_current_annual_eur = 0
    # Accumulate per-year projected totals across all holdings
    year_totals: dict[int, int] = {}

    for sid, h in holdings.items():
        sec = all_securities.get(sid)
        if not sec:
            continue

        yearly = events_by_sec.get(sid)
        if not yearly:
            continue  # No dividend history — skip

        qty = Decimal(str(h["qty"]))
        div_ccy = div_currency_by_sec.get(sid, sec.currency)

        # Compute average annual dividend per share (cents in dividend currency)
        sorted_years = sorted(yearly.keys())
        # Exclude current incomplete year from averages if it exists
        complete_years = [y for y in sorted_years if y < today.year]
        if not complete_years:
            # Only current year data — use it as-is
            annual_per_share = yearly[sorted_years[0]]
            growth_rate = 0.0
        else:
            annual_per_share = sum(yearly[y] for y in complete_years) // len(complete_years)

            # CAGR from earliest to latest complete year
            if len(complete_years) >= 2:
                first_yr_div = yearly[complete_years[0]]
                last_yr_div = yearly[complete_years[-1]]
                n_periods = complete_years[-1] - complete_years[0]
                if first_yr_div > 0 and n_periods > 0:
                    growth_rate = round(
                        (last_yr_div / first_yr_div) ** (1 / n_periods) - 1, 4
                    )
                else:
                    growth_rate = 0.0
            else:
                growth_rate = 0.0

        # Current annual income in div currency cents
        annual_income_cents = int(annual_per_share * float(qty))

        # Convert to EUR
        if div_ccy == "EUR":
            annual_income_eur = annual_income_cents
        else:
            fx = fx_rates.get(div_ccy, Decimal("1"))
            annual_income_eur = int(annual_income_cents / float(fx))

        total_current_annual_eur += annual_income_eur

        # Yield on cost (using current price as proxy)
        yoc = None
        price_data = prices.get(sid)
        if price_data and price_data["close_cents"] > 0:
            price_cents = price_data["close_cents"]
            price_ccy = price_data["currency"]
            if div_ccy == price_ccy:
                yoc = round((annual_per_share / price_cents) * 100, 2)

        # Project forward per year
        for i in range(years):
            proj_year = today.year + i
            factor = (1 + growth_rate) ** i
            projected_eur = int(annual_income_eur * factor)
            year_totals[proj_year] = year_totals.get(proj_year, 0) + projected_eur

        by_holding.append({
            "securityId": sid,
            "ticker": sec.ticker,
            "annualDividendPerShare": round(annual_per_share / 100, 2),
            "quantity": str(qty),
            "annualIncomeCents": annual_income_eur,
            "yieldOnCost": yoc,
            "growthRate": growth_rate,
            "dividendHistory": event_list_by_sec.get(sid, []),
        })

    # Sort by income descending
    by_holding.sort(key=lambda x: x["annualIncomeCents"], reverse=True)

    # Build projections list with yield %
    total_portfolio_value_eur = 0
    for sid, h in holdings.items():
        price_data = prices.get(sid)
        if not price_data:
            continue
        qty_f = float(h["qty"])
        mv = int(price_data["close_cents"] * qty_f)
        ccy = price_data["currency"]
        if ccy == "EUR":
            total_portfolio_value_eur += mv
        else:
            fx = fx_rates.get(ccy, Decimal("1"))
            total_portfolio_value_eur += int(mv / float(fx))

    projections = []
    for i in range(years):
        proj_year = today.year + i
        est = year_totals.get(proj_year, 0)
        yield_pct = round((est / total_portfolio_value_eur) * 100, 2) if total_portfolio_value_eur > 0 else None
        projections.append({
            "year": proj_year,
            "estimatedIncomeCents": est,
            "yieldPct": yield_pct,
        })

    by_month = [{"month": m, "expectedIncomeCents": monthly_totals.get(m, 0)} for m in range(1, 13)]

    return {
        "data": {
            "currentAnnualIncomeCents": total_current_annual_eur,
            "projections": projections,
            "byHolding": by_holding,
            "byMonth": by_month,
        },
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


# ---------------------------------------------------------------------------
# Tax summary endpoint
# ---------------------------------------------------------------------------

@router.get("/tax-summary")
async def dividend_tax_summary():
    """Dividend withholding tax summary by holding and country.

    Takes into account:
    - Country-specific withholding rates for Finnish investors
    - Account type (osakesaastotili is tax-deferred => 0% withholding)
    - Reclaimable excess withholding where applicable
    """
    positions = await _get_holdings_with_accounts()
    if not positions:
        return {
            "data": {
                "totalGrossCents": 0,
                "totalWithholdingCents": 0,
                "totalNetCents": 0,
                "totalReclaimableCents": 0,
                "byHolding": [],
                "byCountry": [],
            },
            "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
        }

    sec_ids = list({p["security_id"] for p in positions})
    fx_rates = await _get_fx_rates()

    # Load securities
    async with async_session() as session:
        sec_result = await session.execute(
            select(Security).where(Security.id.in_(sec_ids))
        )
        securities = {s.id: s for s in sec_result.scalars().all()}

    # Get TTM dividend per share per security (in dividend currency cents)
    one_year_ago = date.today() - timedelta(days=365)
    async with async_session() as session:
        result = await session.execute(
            select(
                DividendEvent.security_id,
                func.sum(DividendEvent.amount_cents).label("ttm_cents"),
                func.max(DividendEvent.currency).label("currency"),
            )
            .where(
                DividendEvent.security_id.in_(sec_ids),
                DividendEvent.ex_date >= one_year_ago,
            )
            .group_by(DividendEvent.security_id)
        )
        ttm_by_sec = {
            r.security_id: {"ttm_cents": int(r.ttm_cents), "currency": r.currency}
            for r in result.all()
        }

    total_gross_eur = 0
    total_wht_eur = 0
    total_net_eur = 0
    total_reclaimable_eur = 0
    by_holding: list[dict] = []
    country_agg: dict[str, dict] = {}

    for pos in positions:
        sid = pos["security_id"]
        sec = securities.get(sid)
        if not sec:
            continue

        ttm = ttm_by_sec.get(sid)
        if not ttm:
            continue  # No dividend history — skip

        qty = Decimal(str(pos["qty"]))
        account_type = pos["account_type"]
        country = sec.country or "FI"
        div_ccy = ttm["currency"]

        # Gross annual dividend in dividend currency cents
        gross_cents = int(ttm["ttm_cents"] * float(qty))

        # Convert to EUR
        if div_ccy == "EUR":
            gross_eur = gross_cents
        else:
            fx = fx_rates.get(div_ccy, Decimal("1"))
            gross_eur = int(gross_cents / float(fx))

        # Determine withholding rate
        if account_type == "osakesaastotili":
            wht_rate = 0.0
        else:
            wht_rate = _WHT_RATES.get(country, _WHT_DEFAULT)

        wht_eur = int(gross_eur * wht_rate)
        net_eur = gross_eur - wht_eur

        # Reclaimable: excess withholding above Finnish tax treaty rate (15%).
        # E.g. Germany withholds 26.375% but treaty allows 15% => 11.375% reclaimable.
        # Finland domestic 30% is NOT reclaimable (it's domestic tax, not foreign WHT).
        reclaimable_eur = 0
        reclaimable = False
        treaty_rate = 0.15
        if account_type != "osakesaastotili" and wht_rate > treaty_rate and country not in ("FI",):
            excess_rate = wht_rate - treaty_rate
            reclaimable_eur = int(gross_eur * excess_rate)
            reclaimable = True

        total_gross_eur += gross_eur
        total_wht_eur += wht_eur
        total_net_eur += net_eur
        total_reclaimable_eur += reclaimable_eur

        by_holding.append({
            "securityId": sid,
            "ticker": sec.ticker,
            "country": country,
            "accountType": account_type,
            "grossCents": gross_eur,
            "withholdingRate": round(wht_rate, 5),
            "withholdingCents": wht_eur,
            "netCents": net_eur,
            "reclaimable": reclaimable,
            "reclaimableCents": reclaimable_eur,
        })

        # Country aggregation
        if country not in country_agg:
            country_agg[country] = {"grossCents": 0, "withholdingCents": 0, "rate": wht_rate}
        country_agg[country]["grossCents"] += gross_eur
        country_agg[country]["withholdingCents"] += wht_eur

    # Sort by gross descending
    by_holding.sort(key=lambda x: x["grossCents"], reverse=True)

    by_country = [
        {
            "country": c,
            "grossCents": v["grossCents"],
            "withholdingCents": v["withholdingCents"],
            "rate": round(v["rate"], 5),
        }
        for c, v in sorted(country_agg.items(), key=lambda x: x[1]["grossCents"], reverse=True)
    ]

    return {
        "data": {
            "totalGrossCents": total_gross_eur,
            "totalWithholdingCents": total_wht_eur,
            "totalNetCents": total_net_eur,
            "totalReclaimableCents": total_reclaimable_eur,
            "byHolding": by_holding,
            "byCountry": by_country,
        },
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }
