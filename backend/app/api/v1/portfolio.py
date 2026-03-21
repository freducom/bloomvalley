"""Portfolio endpoints — holdings, summary, performance."""

from datetime import date, datetime, timezone
from decimal import Decimal

import structlog
from fastapi import APIRouter, Query
from sqlalchemy import func, select, case, literal_column

from app.db.engine import async_session
from app.db.models.accounts import Account
from app.db.models.imports import Import, ImportRow
from app.db.models.prices import FxRate, Price
from app.db.models.securities import Security
from app.db.models.transactions import Transaction

logger = structlog.get_logger()

router = APIRouter()


async def _get_fx_rates() -> dict[str, Decimal]:
    """Get latest FX rates to EUR. Returns {currency: rate_to_eur}."""
    rates: dict[str, Decimal] = {"EUR": Decimal("1.0")}
    async with async_session() as session:
        # Get latest rate per currency pair
        subq = (
            select(
                FxRate.quote_currency,
                func.max(FxRate.date).label("max_date"),
            )
            .where(FxRate.base_currency == "EUR")
            .group_by(FxRate.quote_currency)
            .subquery()
        )
        result = await session.execute(
            select(FxRate).join(
                subq,
                (FxRate.quote_currency == subq.c.quote_currency)
                & (FxRate.date == subq.c.max_date)
                & (FxRate.base_currency == "EUR"),
            )
        )
        for fx in result.scalars().all():
            rates[fx.quote_currency] = fx.rate
    return rates


async def _get_latest_prices() -> dict[int, dict]:
    """Get latest price per security."""
    prices: dict[int, dict] = {}
    async with async_session() as session:
        subq = (
            select(
                Price.security_id,
                func.max(Price.date).label("max_date"),
            )
            .group_by(Price.security_id)
            .subquery()
        )
        result = await session.execute(
            select(Price).join(
                subq,
                (Price.security_id == subq.c.security_id)
                & (Price.date == subq.c.max_date),
            )
        )
        for p in result.scalars().all():
            prices[p.security_id] = {
                "close_cents": p.close_cents,
                "currency": p.currency,
                "date": p.date.isoformat(),
                "source": p.source,
            }
    return prices


@router.get("/holdings")
async def get_holdings(
    account_id: int | None = Query(None, alias="accountId"),
):
    """Calculate current holdings from transactions.

    Groups buy/sell/transfer_in/transfer_out transactions to compute
    net quantity per security per account, then joins with latest prices.
    """
    async with async_session() as session:
        # Calculate net quantity per (account, security) from transactions
        qty_case = case(
            (Transaction.type.in_(["buy", "transfer_in"]), Transaction.quantity),
            (Transaction.type.in_(["sell", "transfer_out"]), -Transaction.quantity),
            else_=literal_column("0"),
        )
        cost_case = case(
            (Transaction.type.in_(["buy", "transfer_in"]), Transaction.total_cents),
            (Transaction.type.in_(["sell", "transfer_out"]), -Transaction.total_cents),
            else_=literal_column("0"),
        )

        query = (
            select(
                Transaction.account_id,
                Transaction.security_id,
                func.sum(qty_case).label("net_quantity"),
                func.sum(cost_case).label("total_cost_cents"),
                func.count(Transaction.id).label("tx_count"),
            )
            .where(
                Transaction.security_id.isnot(None),
                Transaction.type.in_(["buy", "sell", "transfer_in", "transfer_out"]),
            )
            .group_by(Transaction.account_id, Transaction.security_id)
        )

        if account_id:
            query = query.where(Transaction.account_id == account_id)

        result = await session.execute(query)
        position_rows = result.all()

    if not position_rows:
        return {
            "data": [],
            "meta": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "cacheAge": None,
                "stale": False,
            },
        }

    # Load securities, accounts, prices, FX rates
    security_ids = {r.security_id for r in position_rows}
    account_ids = {r.account_id for r in position_rows}

    async with async_session() as session:
        sec_result = await session.execute(
            select(Security).where(Security.id.in_(security_ids))
        )
        securities = {s.id: s for s in sec_result.scalars().all()}

        acct_result = await session.execute(
            select(Account).where(Account.id.in_(account_ids))
        )
        accounts = {a.id: a for a in acct_result.scalars().all()}

    prices = await _get_latest_prices()
    fx_rates = await _get_fx_rates()

    # Get latest import values as fallback for securities without prices
    import_values: dict[int, dict] = {}  # security_id -> {market_value_eur_cents, last_price_cents, currency}
    async with async_session() as session:
        # Get the latest confirmed import rows with market values
        latest_imports = await session.execute(
            select(ImportRow)
            .join(Import, ImportRow.import_id == Import.id)
            .where(Import.status == "confirmed")
            .where(ImportRow.security_id.isnot(None))
            .where(ImportRow.parsed_market_value_cents.isnot(None))
            .order_by(Import.created_at.desc())
        )
        for ir in latest_imports.scalars().all():
            if ir.security_id not in import_values:
                import_values[ir.security_id] = {
                    "market_value_eur_cents": ir.parsed_market_value_cents,
                    "currency": ir.parsed_currency or "EUR",
                }

    holdings = []
    for row in position_rows:
        net_qty = row.net_quantity
        if net_qty is None or net_qty <= 0:
            continue  # No position

        sec = securities.get(row.security_id)
        acct = accounts.get(row.account_id)
        if not sec:
            continue

        price_data = prices.get(row.security_id)
        current_price_cents = price_data["close_cents"] if price_data else None
        price_currency = price_data["currency"] if price_data else sec.currency
        price_stale = False

        # Market value in security currency
        market_value_cents = None
        if current_price_cents is not None:
            market_value_cents = int(current_price_cents * float(net_qty))

        # Convert to EUR
        market_value_eur_cents = None
        if market_value_cents is not None:
            fx = fx_rates.get(price_currency)
            if price_currency == "EUR":
                market_value_eur_cents = market_value_cents
            elif fx:
                market_value_eur_cents = int(market_value_cents / float(fx))
            else:
                market_value_eur_cents = market_value_cents  # Fallback: treat as EUR

        # Fallback: use import values if no price data
        if market_value_eur_cents is None and row.security_id in import_values:
            iv = import_values[row.security_id]
            market_value_eur_cents = iv["market_value_eur_cents"]
            price_stale = True

        # Cost basis
        total_cost = int(row.total_cost_cents) if row.total_cost_cents else 0
        # Convert cost to EUR if needed
        tx_currency = sec.currency
        cost_eur_cents = total_cost
        if tx_currency != "EUR":
            fx = fx_rates.get(tx_currency)
            if fx:
                cost_eur_cents = int(total_cost / float(fx))

        # Average cost per unit
        avg_cost_cents = int(total_cost / float(net_qty)) if net_qty > 0 else 0

        # Unrealized P&L
        unrealized_pnl_cents = None
        unrealized_pnl_pct = None
        if market_value_eur_cents is not None and cost_eur_cents:
            unrealized_pnl_cents = market_value_eur_cents - cost_eur_cents
            if cost_eur_cents != 0:
                unrealized_pnl_pct = round(
                    (unrealized_pnl_cents / cost_eur_cents) * 100, 2
                )

        holdings.append({
            "accountId": row.account_id,
            "accountName": acct.name if acct else None,
            "accountType": acct.type if acct else None,
            "securityId": row.security_id,
            "ticker": sec.ticker,
            "name": sec.name,
            "assetClass": sec.asset_class,
            "sector": sec.sector,
            "quantity": str(net_qty),
            "avgCostCents": avg_cost_cents,
            "currentPriceCents": current_price_cents,
            "priceCurrency": price_currency,
            "priceDate": price_data["date"] if price_data else None,
            "priceSource": price_data["source"] if price_data else ("nordnet_import" if price_stale else None),
            "priceStale": price_stale,
            "marketValueCents": market_value_cents,
            "marketValueEurCents": market_value_eur_cents,
            "costBasisEurCents": cost_eur_cents,
            "unrealizedPnlCents": unrealized_pnl_cents,
            "unrealizedPnlPct": unrealized_pnl_pct,
            "currency": sec.currency,
        })

    return {
        "data": holdings,
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cacheAge": None,
            "stale": False,
        },
    }


@router.get("/summary")
async def get_portfolio_summary(
    account_id: int | None = Query(None, alias="accountId"),
):
    """Portfolio summary: total value, day change, unrealized P&L, allocation."""
    # Reuse holdings calculation
    holdings_response = await get_holdings(account_id)
    holdings = holdings_response["data"]

    if not holdings:
        return {
            "data": {
                "totalValueEurCents": 0,
                "totalCostEurCents": 0,
                "unrealizedPnlCents": 0,
                "unrealizedPnlPct": None,
                "holdingsCount": 0,
                "allocation": {},
                "accounts": [],
            },
            "meta": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "cacheAge": None,
                "stale": False,
            },
        }

    total_value = sum(h["marketValueEurCents"] or 0 for h in holdings)
    total_cost = sum(h["costBasisEurCents"] or 0 for h in holdings)
    unrealized_pnl = total_value - total_cost
    unrealized_pnl_pct = (
        round((unrealized_pnl / total_cost) * 100, 2) if total_cost != 0 else None
    )

    # Allocation by asset class
    # Fixed income ETFs/funds (sector = "Fixed Income") count as fixed_income, not etf
    allocation: dict[str, int] = {}
    for h in holdings:
        ac = h["assetClass"] or "other"
        sector = (h.get("sector") or "").lower()
        if ac == "etf" and "fixed income" in sector:
            ac = "fixed_income"
        allocation[ac] = allocation.get(ac, 0) + (h["marketValueEurCents"] or 0)

    # Account breakdown with cash balances
    account_map: dict[int, dict] = {}
    for h in holdings:
        aid = h["accountId"]
        if aid not in account_map:
            account_map[aid] = {
                "accountId": aid,
                "accountName": h["accountName"],
                "accountType": h["accountType"],
                "valueCents": 0,
                "cashBalanceCents": 0,
                "cashCurrency": "EUR",
                "holdingsCount": 0,
            }
        account_map[aid]["valueCents"] += h["marketValueEurCents"] or 0
        account_map[aid]["holdingsCount"] += 1

    # Load cash balances
    total_cash = 0
    fx_rates = await _get_fx_rates()
    async with async_session() as session:
        acct_ids = list(account_map.keys()) if account_map else []
        if acct_ids:
            result = await session.execute(
                select(Account).where(Account.id.in_(acct_ids))
            )
            for acct in result.scalars().all():
                if acct.id in account_map:
                    account_map[acct.id]["cashBalanceCents"] = acct.cash_balance_cents
                    account_map[acct.id]["cashCurrency"] = acct.cash_currency
                    # Convert cash to EUR
                    if acct.cash_currency == "EUR":
                        cash_eur = acct.cash_balance_cents
                    else:
                        fx = fx_rates.get(acct.cash_currency, Decimal("1"))
                        cash_eur = int(acct.cash_balance_cents / float(fx))
                    total_cash += cash_eur
                    account_map[acct.id]["valueCents"] += cash_eur

    # Also check for accounts with only cash (no holdings)
    if account_id:
        async with async_session() as session:
            acct = await session.get(Account, account_id)
            if acct and account_id not in account_map and acct.cash_balance_cents > 0:
                account_map[account_id] = {
                    "accountId": account_id,
                    "accountName": acct.name,
                    "accountType": acct.type,
                    "valueCents": acct.cash_balance_cents,
                    "cashBalanceCents": acct.cash_balance_cents,
                    "cashCurrency": acct.cash_currency,
                    "holdingsCount": 0,
                }
                total_cash += acct.cash_balance_cents

    allocation["cash"] = total_cash
    total_value += total_cash

    return {
        "data": {
            "totalValueEurCents": total_value,
            "totalCostEurCents": total_cost,
            "totalCashEurCents": total_cash,
            "unrealizedPnlCents": unrealized_pnl,
            "unrealizedPnlPct": unrealized_pnl_pct,
            "holdingsCount": len(holdings),
            "allocation": allocation,
            "accounts": list(account_map.values()),
        },
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cacheAge": None,
            "stale": False,
        },
    }
