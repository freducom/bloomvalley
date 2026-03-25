"""Portfolio endpoints — holdings, summary, performance."""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, case, literal_column

from app.db.engine import async_session
from app.db.models.accounts import Account
from app.db.models.holdings_snapshot import HoldingsSnapshot
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


@router.get("/value-history")
async def get_value_history(
    days: int = Query(90, ge=7, le=730),
):
    """Compute daily total portfolio value (holdings + cash) over time.

    Holdings are replayed against historical prices. Cash balance is
    reconstructed from deposit/withdrawal/buy/sell/dividend/fee transactions.
    """
    from collections import defaultdict
    from datetime import timedelta

    from_date = date.today() - timedelta(days=days)

    # 1. Get current holdings (quantities)
    holdings_resp = await get_holdings(account_id=None)
    holdings_data = holdings_resp["data"]

    # Build {security_id: quantity} and track currencies
    positions: dict[int, float] = {}
    sec_currencies: dict[int, str] = {}
    for h in holdings_data:
        sid = h["securityId"]
        positions[sid] = float(h["quantity"])
        sec_currencies[sid] = h["priceCurrency"] or h["currency"]

    # 2. Fetch historical prices
    price_rows = []
    if positions:
        async with async_session() as session:
            result = await session.execute(
                select(Price.security_id, Price.date, Price.close_cents, Price.currency)
                .where(Price.security_id.in_(list(positions.keys())))
                .where(Price.date >= from_date)
                .order_by(Price.date)
            )
            price_rows = result.all()

    # 3. Fetch FX rate history for non-EUR currencies
    needed_currencies = {c for c in sec_currencies.values() if c != "EUR"}
    fx_history: dict[str, dict[date, float]] = {}
    if needed_currencies:
        async with async_session() as session:
            fx_result = await session.execute(
                select(FxRate.quote_currency, FxRate.date, FxRate.rate)
                .where(FxRate.base_currency == "EUR")
                .where(FxRate.quote_currency.in_(list(needed_currencies)))
                .where(FxRate.date >= from_date)
                .order_by(FxRate.date)
            )
            for row in fx_result.all():
                fx_history.setdefault(row.quote_currency, {})[row.date] = float(row.rate)

    # 4. Reconstruct daily cash balance from transactions
    # Get current total cash across all accounts (in EUR)
    fx_rates = await _get_fx_rates()
    total_cash_now = 0
    async with async_session() as session:
        acct_result = await session.execute(
            select(Account).where(Account.is_active.is_(True))
        )
        for acct in acct_result.scalars().all():
            if acct.cash_currency == "EUR":
                total_cash_now += acct.cash_balance_cents
            else:
                fx = fx_rates.get(acct.cash_currency, Decimal("1"))
                total_cash_now += int(acct.cash_balance_cents / float(fx))

    # Get all cash-affecting transactions to build historical cash deltas
    # Positive to cash: sell proceeds, dividends, deposits, interest
    # Negative from cash: buy cost, withdrawals, fees
    async with async_session() as session:
        tx_result = await session.execute(
            select(
                Transaction.trade_date,
                Transaction.type,
                Transaction.total_cents,
                Transaction.fee_cents,
                Transaction.currency,
            )
            .where(Transaction.trade_date >= from_date)
            .where(Transaction.type.in_([
                "buy", "sell", "dividend", "deposit", "withdrawal",
                "fee", "interest",
            ]))
            .order_by(Transaction.trade_date)
        )
        cash_txns = tx_result.all()

    # Build daily cash deltas (in EUR) from today backwards
    daily_cash_delta: dict[date, int] = defaultdict(int)
    for tx in cash_txns:
        amount = tx.total_cents or 0
        fee = tx.fee_cents or 0
        fx = float(fx_rates.get(tx.currency, Decimal("1"))) if tx.currency != "EUR" else 1.0

        if tx.type in ("sell", "dividend", "deposit", "interest"):
            # These added cash — so going backwards, subtract them
            delta = int((amount - fee) / fx)
            daily_cash_delta[tx.trade_date] -= delta
        elif tx.type == "buy":
            # Buys removed cash — going backwards, add them back
            delta = int((amount + fee) / fx)
            daily_cash_delta[tx.trade_date] += delta
        elif tx.type == "withdrawal":
            # Withdrawals removed cash — going backwards, add them back
            delta = int(amount / fx)
            daily_cash_delta[tx.trade_date] += delta
        elif tx.type == "fee":
            # Fees removed cash — going backwards, add them back
            delta = int(amount / fx)
            daily_cash_delta[tx.trade_date] += delta

    # 5. Build daily value series
    daily_prices: dict[int, dict[date, tuple[int, str]]] = defaultdict(dict)
    for row in price_rows:
        daily_prices[row.security_id][row.date] = (row.close_cents, row.currency)

    all_dates = sorted({row.date for row in price_rows})
    if not all_dates:
        return {"data": []}

    # Build cash balance for each date by working backwards from today
    # Start with current cash and subtract deltas going back in time
    cash_by_date: dict[date, int] = {}
    running_cash = total_cash_now
    for d in reversed(all_dates):
        cash_by_date[d] = running_cash
        # Apply reverse delta for this date (already computed as reverse)
        running_cash += daily_cash_delta.get(d, 0)

    # Forward-fill prices and FX rates
    last_price: dict[int, tuple[int, str]] = {}
    last_fx: dict[str, float] = {}
    series = []

    for d in all_dates:
        total_eur_cents = 0
        has_data = False

        for sid, qty in positions.items():
            if d in daily_prices[sid]:
                last_price[sid] = daily_prices[sid][d]
            if sid not in last_price:
                continue

            close_cents, currency = last_price[sid]
            value_cents = close_cents * qty

            if currency == "EUR":
                total_eur_cents += value_cents
            else:
                if d in fx_history.get(currency, {}):
                    last_fx[currency] = fx_history[currency][d]
                fx = last_fx.get(currency)
                if fx:
                    total_eur_cents += value_cents / fx
                else:
                    total_eur_cents += value_cents  # fallback

            has_data = True

        if has_data:
            cash_eur = cash_by_date.get(d, total_cash_now)
            series.append({
                "date": d.isoformat(),
                "valueCents": int(total_eur_cents) + cash_eur,
                "holdingsCents": int(total_eur_cents),
                "cashCents": cash_eur,
            })

    return {"data": series}


@router.post("/snapshot")
async def take_snapshot():
    """Take a snapshot of current holdings for attribution analysis."""
    from fastapi.responses import JSONResponse

    # Get current holdings (pass account_id=None explicitly)
    holdings_resp = await get_holdings(account_id=None)
    holdings_data = holdings_resp.get("data", [])
    if not holdings_data:
        return JSONResponse(status_code=400, content={"detail": "No holdings to snapshot"})

    today = date.today()
    total_value = sum(h.get("marketValueEurCents") or 0 for h in holdings_data)
    rows_created = 0

    async with async_session() as session:
        # Delete existing snapshot for today (upsert)
        from sqlalchemy import delete
        await session.execute(
            delete(HoldingsSnapshot).where(HoldingsSnapshot.snapshot_date == today)
        )

        for h in holdings_data:
            if not h.get("securityId"):
                continue
            mv = h.get("marketValueEurCents") or 0
            weight = (mv / total_value * 100) if total_value > 0 else 0

            snapshot = HoldingsSnapshot(
                snapshot_date=today,
                account_id=h["accountId"],
                security_id=h["securityId"],
                quantity=Decimal(str(h.get("quantity", 0))),
                cost_basis_cents=h.get("costBasisEurCents") or 0,
                cost_basis_currency="EUR",
                market_price_cents=h.get("lastPriceCents") or 0,
                market_price_currency=h.get("currency") or "EUR",
                market_value_eur_cents=mv,
                unrealized_pnl_eur_cents=h.get("unrealizedPnlEurCents") or 0,
                fx_rate=None,
                weight_pct=Decimal(str(round(weight, 4))),
            )
            session.add(snapshot)
            rows_created += 1

        await session.commit()

    logger.info("holdings_snapshot_taken", date=today.isoformat(), rows=rows_created)
    return {
        "data": {"date": today.isoformat(), "rows": rows_created},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


class SellRequest(BaseModel):
    account_id: int
    security_id: int
    quantity: str
    price_cents: int
    total_cents: int  # gross proceeds
    fee_cents: int = 0
    currency: str = "EUR"
    trade_date: date
    notes: Optional[str] = None


@router.post("/sell")
async def sell_holding(body: SellRequest):
    """Sell a holding: create sell transaction and add net proceeds to cash balance."""
    qty = Decimal(body.quantity)
    if qty <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")

    # Verify the holding exists with enough quantity
    async with async_session() as session:
        # Check account exists
        account = await session.get(Account, body.account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        # Check security exists
        security = await session.get(Security, body.security_id)
        if not security:
            raise HTTPException(status_code=404, detail="Security not found")

        # Check current position quantity
        qty_case = case(
            (Transaction.type.in_(["buy", "transfer_in"]), Transaction.quantity),
            (Transaction.type.in_(["sell", "transfer_out"]), -Transaction.quantity),
            else_=literal_column("0"),
        )
        result = await session.execute(
            select(func.sum(qty_case).label("net_qty"))
            .where(
                Transaction.account_id == body.account_id,
                Transaction.security_id == body.security_id,
                Transaction.type.in_(["buy", "sell", "transfer_in", "transfer_out"]),
            )
        )
        current_qty = result.scalar_one() or Decimal("0")

        if qty > current_qty:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot sell {qty} — only {current_qty} held",
            )

        # Create sell transaction
        tx = Transaction(
            account_id=body.account_id,
            security_id=body.security_id,
            type="sell",
            trade_date=body.trade_date,
            quantity=qty,
            price_cents=body.price_cents,
            price_currency=body.currency,
            total_cents=body.total_cents,
            fee_cents=body.fee_cents,
            fee_currency=body.currency,
            currency=body.currency,
            notes=body.notes,
        )
        session.add(tx)

        # Add net proceeds (total - fees) to account cash balance
        net_proceeds = body.total_cents - body.fee_cents
        account.cash_balance_cents += net_proceeds

        await session.commit()
        await session.refresh(tx)

    logger.info(
        "holding_sold",
        account_id=body.account_id,
        security=security.ticker,
        quantity=str(qty),
        proceeds=body.total_cents,
        fee=body.fee_cents,
        net_proceeds=net_proceeds,
    )

    return {
        "data": {
            "transactionId": tx.id,
            "ticker": security.ticker,
            "name": security.name,
            "quantity": str(qty),
            "proceedsCents": body.total_cents,
            "feeCents": body.fee_cents,
            "netProceedsCents": net_proceeds,
            "newCashBalanceCents": account.cash_balance_cents,
            "currency": body.currency,
        },
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/sold-holdings")
async def get_sold_holdings():
    """Return securities that were fully sold (net quantity = 0 or less).

    Includes historical cost basis, total proceeds, realized P&L, and dates.
    """
    async with async_session() as session:
        qty_case = case(
            (Transaction.type.in_(["buy", "transfer_in"]), Transaction.quantity),
            (Transaction.type.in_(["sell", "transfer_out"]), -Transaction.quantity),
            else_=literal_column("0"),
        )
        bought_qty = case(
            (Transaction.type.in_(["buy", "transfer_in"]), Transaction.quantity),
            else_=literal_column("0"),
        )
        sold_qty = case(
            (Transaction.type.in_(["sell", "transfer_out"]), Transaction.quantity),
            else_=literal_column("0"),
        )
        cost_case = case(
            (Transaction.type.in_(["buy", "transfer_in"]), Transaction.total_cents),
            else_=literal_column("0"),
        )
        proceeds_case = case(
            (Transaction.type.in_(["sell", "transfer_out"]), Transaction.total_cents),
            else_=literal_column("0"),
        )
        fees_case = case(
            (Transaction.type.in_(["sell", "transfer_out"]), Transaction.fee_cents),
            else_=literal_column("0"),
        )
        first_buy = case(
            (Transaction.type.in_(["buy", "transfer_in"]), Transaction.trade_date),
            else_=None,
        )
        last_sell = case(
            (Transaction.type.in_(["sell", "transfer_out"]), Transaction.trade_date),
            else_=None,
        )

        result = await session.execute(
            select(
                Transaction.account_id,
                Transaction.security_id,
                func.sum(qty_case).label("net_qty"),
                func.sum(bought_qty).label("total_bought"),
                func.sum(sold_qty).label("total_sold"),
                func.sum(cost_case).label("total_cost_cents"),
                func.sum(proceeds_case).label("total_proceeds_cents"),
                func.sum(fees_case).label("total_sell_fees_cents"),
                func.min(first_buy).label("first_buy_date"),
                func.max(last_sell).label("last_sell_date"),
            )
            .where(
                Transaction.security_id.isnot(None),
                Transaction.type.in_(["buy", "sell", "transfer_in", "transfer_out"]),
            )
            .group_by(Transaction.account_id, Transaction.security_id)
            .having(func.sum(qty_case) <= 0)
        )
        rows = result.all()

    if not rows:
        return {
            "data": [],
            "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
        }

    # Load securities and accounts
    security_ids = {r.security_id for r in rows}
    account_ids = {r.account_id for r in rows}

    async with async_session() as session:
        sec_result = await session.execute(
            select(Security).where(Security.id.in_(security_ids))
        )
        securities = {s.id: s for s in sec_result.scalars().all()}

        acct_result = await session.execute(
            select(Account).where(Account.id.in_(account_ids))
        )
        accounts = {a.id: a for a in acct_result.scalars().all()}

    data = []
    for r in rows:
        sec = securities.get(r.security_id)
        acct = accounts.get(r.account_id)
        if not sec:
            continue

        cost = int(r.total_cost_cents or 0)
        proceeds = int(r.total_proceeds_cents or 0)
        fees = int(r.total_sell_fees_cents or 0)
        realized_pnl = proceeds - cost - fees

        data.append({
            "accountId": r.account_id,
            "accountName": acct.name if acct else None,
            "securityId": r.security_id,
            "ticker": sec.ticker,
            "name": sec.name,
            "assetClass": sec.asset_class,
            "totalBought": str(r.total_bought or 0),
            "totalSold": str(r.total_sold or 0),
            "totalCostCents": cost,
            "totalProceedsCents": proceeds,
            "totalFeesCents": fees,
            "realizedPnlCents": realized_pnl,
            "currency": sec.currency,
            "firstBuyDate": r.first_buy_date.isoformat() if r.first_buy_date else None,
            "lastSellDate": r.last_sell_date.isoformat() if r.last_sell_date else None,
        })

    return {
        "data": data,
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }
