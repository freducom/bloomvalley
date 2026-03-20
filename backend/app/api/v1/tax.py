"""Tax endpoints — lots, gains, OST tracker, harvesting, annual report."""

from datetime import date, datetime, timezone
from decimal import Decimal

import structlog
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import case, func, literal_column, select

from app.db.engine import async_session
from app.db.models.accounts import Account
from app.db.models.securities import Security
from app.db.models.tax_lots import TaxLot
from app.db.models.transactions import Transaction
from app.api.v1.portfolio import _get_fx_rates, _get_latest_prices

logger = structlog.get_logger()

router = APIRouter()

# Finnish capital gains tax brackets
TAX_BRACKET_LOW = Decimal("0.30")  # 30% up to €30,000
TAX_BRACKET_HIGH = Decimal("0.34")  # 34% above €30,000
TAX_THRESHOLD_CENTS = 3_000_000  # €30,000 in cents


def _compute_tax(capital_income_cents: int) -> dict:
    """Compute Finnish capital income tax with bracket breakdown."""
    if capital_income_cents <= 0:
        return {"taxCents": 0, "effectiveRate": 0, "bracket30kCents": 0, "bracketAboveCents": 0}

    if capital_income_cents <= TAX_THRESHOLD_CENTS:
        tax = int(capital_income_cents * TAX_BRACKET_LOW)
        return {
            "taxCents": tax,
            "effectiveRate": round(float(TAX_BRACKET_LOW) * 100, 2),
            "bracket30kCents": capital_income_cents,
            "bracketAboveCents": 0,
        }

    tax_low = int(TAX_THRESHOLD_CENTS * TAX_BRACKET_LOW)
    above = capital_income_cents - TAX_THRESHOLD_CENTS
    tax_high = int(above * TAX_BRACKET_HIGH)
    total_tax = tax_low + tax_high
    effective = round((total_tax / capital_income_cents) * 100, 2)

    return {
        "taxCents": total_tax,
        "effectiveRate": effective,
        "bracket30kCents": TAX_THRESHOLD_CENTS,
        "bracketAboveCents": above,
    }


def _deemed_cost(gross_proceeds_cents: int, holding_years: float) -> int:
    """Finnish deemed cost of acquisition (hankintameno-olettama)."""
    if holding_years >= 10:
        return int(gross_proceeds_cents * Decimal("0.40"))
    return int(gross_proceeds_cents * Decimal("0.20"))


def _holding_years(acquired: date, closed: date | None = None) -> float:
    """Years between acquired and closed (or today)."""
    end = closed or date.today()
    return (end - acquired).days / 365.25


def _compute_lot_gain(lot: TaxLot) -> dict:
    """Compute gain with deemed cost comparison for a closed lot."""
    if lot.proceeds_cents is None:
        return {}

    actual_gain = lot.proceeds_cents - lot.cost_basis_cents
    years = _holding_years(lot.acquired_date, lot.closed_date)
    deemed = _deemed_cost(lot.proceeds_cents, years)
    deemed_gain = lot.proceeds_cents - deemed

    # Deemed cost can only be used for gains (not to create or increase a loss)
    if actual_gain <= 0:
        taxable_gain = actual_gain
        method = "actual"
    elif deemed_gain < actual_gain:
        taxable_gain = deemed_gain
        method = "deemed"
    else:
        taxable_gain = actual_gain
        method = "actual"

    return {
        "actualGainCents": actual_gain,
        "deemedCostCents": deemed,
        "deemedGainCents": deemed_gain,
        "taxableGainCents": taxable_gain,
        "methodUsed": method,
        "holdingYears": round(years, 2),
    }


@router.get("/lots")
async def list_tax_lots(
    state: str | None = Query(None),
    account_id: int | None = Query(None, alias="accountId"),
    security_id: int | None = Query(None, alias="securityId"),
    year: int | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List tax lots with filters."""
    async with async_session() as session:
        query = (
            select(TaxLot, Security, Account)
            .join(Security, TaxLot.security_id == Security.id)
            .join(Account, TaxLot.account_id == Account.id)
            .order_by(TaxLot.acquired_date.desc())
        )

        if state:
            query = query.where(TaxLot.state == state)
        if account_id:
            query = query.where(TaxLot.account_id == account_id)
        if security_id:
            query = query.where(TaxLot.security_id == security_id)
        if year:
            query = query.where(func.extract("year", TaxLot.acquired_date) == year)

        count_q = select(func.count()).select_from(query.subquery())
        total = (await session.execute(count_q)).scalar_one()

        result = await session.execute(query.offset(offset).limit(limit))
        rows = result.all()

    prices = await _get_latest_prices()
    fx_rates = await _get_fx_rates()

    data = []
    for lot, sec, acc in rows:
        price_data = prices.get(sec.id)
        market_value_cents = None
        unrealized_pnl = None

        if lot.state != "closed" and price_data and float(lot.remaining_quantity) > 0:
            mv = int(price_data["close_cents"] * float(lot.remaining_quantity))
            # Convert to lot currency if needed
            if price_data["currency"] != lot.cost_basis_currency:
                fx = fx_rates.get(price_data["currency"], Decimal("1"))
                target_fx = fx_rates.get(lot.cost_basis_currency, Decimal("1"))
                mv = int(mv * float(target_fx) / float(fx)) if lot.cost_basis_currency != "EUR" else int(mv / float(fx))
            market_value_cents = mv
            # Proportional cost basis for remaining qty
            remaining_cost = int(lot.cost_basis_cents * (float(lot.remaining_quantity) / float(lot.original_quantity)))
            unrealized_pnl = mv - remaining_cost

        gain_info = _compute_lot_gain(lot) if lot.state == "closed" else {}
        years = _holding_years(lot.acquired_date, lot.closed_date)

        data.append({
            "id": lot.id,
            "accountId": lot.account_id,
            "accountName": acc.name,
            "accountType": acc.type,
            "securityId": lot.security_id,
            "ticker": sec.ticker,
            "securityName": sec.name,
            "assetClass": sec.asset_class,
            "state": lot.state,
            "acquiredDate": lot.acquired_date.isoformat(),
            "closedDate": lot.closed_date.isoformat() if lot.closed_date else None,
            "originalQuantity": str(lot.original_quantity),
            "remainingQuantity": str(lot.remaining_quantity),
            "costBasisCents": lot.cost_basis_cents,
            "costBasisCurrency": lot.cost_basis_currency,
            "proceedsCents": lot.proceeds_cents,
            "realizedPnlCents": lot.realized_pnl_cents,
            "marketValueCents": market_value_cents,
            "unrealizedPnlCents": unrealized_pnl,
            "holdingYears": round(years, 2),
            **gain_info,
        })

    return {
        "data": data,
        "pagination": {"total": total, "limit": limit, "offset": offset},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/gains")
async def tax_gains(
    year: int = Query(default=None),
):
    """Realized + unrealized gains summary for a tax year."""
    tax_year = year or date.today().year

    async with async_session() as session:
        # Realized gains from closed lots in the given year
        result = await session.execute(
            select(
                TaxLot, Security, Account
            )
            .join(Security, TaxLot.security_id == Security.id)
            .join(Account, TaxLot.account_id == Account.id)
            .where(
                TaxLot.state == "closed",
                func.extract("year", TaxLot.closed_date) == tax_year,
            )
            .order_by(TaxLot.closed_date)
        )
        closed_lots = result.all()

    # Separate by account type (OST trades are tax-free internally)
    taxable_gains = 0
    taxable_losses = 0
    by_category: dict[str, dict] = {}
    per_security: list[dict] = []

    for lot, sec, acc in closed_lots:
        gain_info = _compute_lot_gain(lot)
        taxable_gain = gain_info.get("taxableGainCents", 0)

        is_tax_free = acc.type in ("osakesaastotili", "pension")

        entry = {
            "securityId": sec.id,
            "ticker": sec.ticker,
            "name": sec.name,
            "accountName": acc.name,
            "accountType": acc.type,
            "acquiredDate": lot.acquired_date.isoformat(),
            "closedDate": lot.closed_date.isoformat() if lot.closed_date else None,
            "costBasisCents": lot.cost_basis_cents,
            "proceedsCents": lot.proceeds_cents,
            "isTaxFree": is_tax_free,
            **gain_info,
        }
        per_security.append(entry)

        if is_tax_free:
            continue

        if taxable_gain >= 0:
            taxable_gains += taxable_gain
        else:
            taxable_losses += taxable_gain  # negative

        cat_key = f"{sec.asset_class or 'other'}"
        if cat_key not in by_category:
            by_category[cat_key] = {"category": cat_key, "gainsCents": 0, "lossesCents": 0}
        if taxable_gain >= 0:
            by_category[cat_key]["gainsCents"] += taxable_gain
        else:
            by_category[cat_key]["lossesCents"] += taxable_gain

    net_realized = taxable_gains + taxable_losses  # losses are negative
    tax_info = _compute_tax(max(0, net_realized))

    # Add net column to categories
    for cat in by_category.values():
        cat["netCents"] = cat["gainsCents"] + cat["lossesCents"]

    return {
        "data": {
            "year": tax_year,
            "realizedGainsCents": taxable_gains,
            "realizedLossesCents": taxable_losses,
            "netRealizedCents": net_realized,
            "estimatedTax": tax_info,
            "byCategory": sorted(by_category.values(), key=lambda x: abs(x["netCents"]), reverse=True),
            "perSecurity": per_security,
        },
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/osakesaastotili")
async def ost_tracker():
    """Osakesäästötili account status, holdings, withdrawal projections."""
    async with async_session() as session:
        # Find OST account
        result = await session.execute(
            select(Account).where(Account.type == "osakesaastotili", Account.is_active.is_(True))
        )
        ost = result.scalar_one_or_none()

    if not ost:
        return {
            "data": {"hasAccount": False},
            "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
        }

    # Get OST holdings
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
                Transaction.account_id == ost.id,
                Transaction.security_id.isnot(None),
                Transaction.type.in_(["buy", "sell", "transfer_in", "transfer_out"]),
            )
            .group_by(Transaction.security_id)
            .having(func.sum(qty_case) > 0)
        )
        holdings_raw = {r.security_id: float(r.qty) for r in result.all()}

        # Get security details
        if holdings_raw:
            sec_result = await session.execute(
                select(Security).where(Security.id.in_(list(holdings_raw.keys())))
            )
            secs = {s.id: s for s in sec_result.scalars().all()}
        else:
            secs = {}

        # Get deposit history
        dep_result = await session.execute(
            select(Transaction)
            .where(
                Transaction.account_id == ost.id,
                Transaction.type == "deposit",
            )
            .order_by(Transaction.trade_date)
        )
        deposits = dep_result.scalars().all()

    prices = await _get_latest_prices()
    fx_rates = await _get_fx_rates()

    # Compute current value
    total_value_cents = 0
    holdings = []
    for sid, qty in holdings_raw.items():
        sec = secs.get(sid)
        if not sec:
            continue
        price_data = prices.get(sid)
        mv_cents = 0
        if price_data:
            mv_cents = int(price_data["close_cents"] * qty)
            if price_data["currency"] != "EUR":
                fx = fx_rates.get(price_data["currency"], Decimal("1"))
                mv_cents = int(mv_cents / float(fx))
        total_value_cents += mv_cents
        holdings.append({
            "securityId": sid,
            "ticker": sec.ticker,
            "name": sec.name,
            "quantity": str(qty),
            "marketValueEurCents": mv_cents,
        })

    total_deposits = ost.osa_deposit_total_cents
    gains_cents = total_value_cents - total_deposits
    gains_ratio = (gains_cents / total_value_cents) if total_value_cents > 0 else 0

    deposit_history = [
        {
            "date": d.trade_date.isoformat(),
            "amountCents": d.total_cents,
            "runningTotalCents": sum(
                dep.total_cents for dep in deposits[:i + 1]
            ),
        }
        for i, d in enumerate(deposits)
    ]

    return {
        "data": {
            "hasAccount": True,
            "accountId": ost.id,
            "accountName": ost.name,
            "totalDepositsCents": total_deposits,
            "depositCapCents": 5_000_000,
            "depositCapUsedPct": round((total_deposits / 5_000_000) * 100, 1) if total_deposits > 0 else 0,
            "currentValueCents": total_value_cents,
            "gainsCents": gains_cents,
            "gainsRatio": round(gains_ratio * 100, 2),
            "holdings": sorted(holdings, key=lambda x: x["marketValueEurCents"], reverse=True),
            "depositHistory": deposit_history,
        },
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/harvesting")
async def loss_harvesting():
    """Loss harvesting candidates — open lots with unrealized losses in taxable accounts."""
    async with async_session() as session:
        # Get open lots in regular (taxable) accounts only
        result = await session.execute(
            select(TaxLot, Security, Account)
            .join(Security, TaxLot.security_id == Security.id)
            .join(Account, TaxLot.account_id == Account.id)
            .where(
                TaxLot.state.in_(["open", "partially_closed"]),
                Account.type == "regular",
            )
        )
        lots = result.all()

    if not lots:
        return {
            "data": {
                "totalUnrealizedLossCents": 0,
                "realizedGainsYtdCents": 0,
                "potentialTaxSavingsCents": 0,
                "candidates": [],
            },
            "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
        }

    prices = await _get_latest_prices()
    fx_rates = await _get_fx_rates()

    candidates = []
    total_unrealized_loss = 0

    for lot, sec, acc in lots:
        price_data = prices.get(sec.id)
        if not price_data or float(lot.remaining_quantity) <= 0:
            continue

        mv = int(price_data["close_cents"] * float(lot.remaining_quantity))
        if price_data["currency"] != lot.cost_basis_currency:
            fx = fx_rates.get(price_data["currency"], Decimal("1"))
            mv = int(mv / float(fx))

        remaining_cost = int(
            lot.cost_basis_cents * (float(lot.remaining_quantity) / float(lot.original_quantity))
        )
        unrealized = mv - remaining_cost

        if unrealized >= 0:
            continue  # Only losses

        years = _holding_years(lot.acquired_date)
        deemed = _deemed_cost(mv, years)
        # For losses, deemed cost doesn't apply (can't create a loss with deemed)

        tax_saving_low = int(abs(unrealized) * float(TAX_BRACKET_LOW))
        tax_saving_high = int(abs(unrealized) * float(TAX_BRACKET_HIGH))

        total_unrealized_loss += unrealized

        candidates.append({
            "lotId": lot.id,
            "securityId": sec.id,
            "ticker": sec.ticker,
            "name": sec.name,
            "accountName": acc.name,
            "quantity": str(lot.remaining_quantity),
            "costBasisCents": remaining_cost,
            "marketValueCents": mv,
            "unrealizedLossCents": unrealized,
            "holdingYears": round(years, 2),
            "taxSavingLowCents": tax_saving_low,
            "taxSavingHighCents": tax_saving_high,
        })

    candidates.sort(key=lambda x: x["unrealizedLossCents"])

    # Get YTD realized gains for context
    ytd_year = date.today().year
    async with async_session() as session:
        result = await session.execute(
            select(func.sum(TaxLot.realized_pnl_cents))
            .join(Account, TaxLot.account_id == Account.id)
            .where(
                TaxLot.state == "closed",
                func.extract("year", TaxLot.closed_date) == ytd_year,
                Account.type == "regular",
            )
        )
        ytd_gains = result.scalar_one() or 0

    potential_saving = _compute_tax(max(0, ytd_gains))["taxCents"] - _compute_tax(max(0, ytd_gains + total_unrealized_loss))["taxCents"]

    return {
        "data": {
            "totalUnrealizedLossCents": total_unrealized_loss,
            "realizedGainsYtdCents": ytd_gains,
            "potentialTaxSavingsCents": max(0, potential_saving),
            "candidates": candidates,
        },
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/generate-lots")
async def generate_tax_lots():
    """Generate tax lots from transactions (FIFO matching). Idempotent — skips existing."""
    async with async_session() as session:
        # Get all buy/transfer_in transactions that don't have a tax lot yet
        existing_open_ids = select(TaxLot.open_transaction_id)
        result = await session.execute(
            select(Transaction)
            .where(
                Transaction.type.in_(["buy", "transfer_in"]),
                Transaction.security_id.isnot(None),
                Transaction.quantity > 0,
                ~Transaction.id.in_(existing_open_ids),
            )
            .order_by(Transaction.trade_date)
        )
        new_buys = result.scalars().all()

        created = 0
        for txn in new_buys:
            lot = TaxLot(
                account_id=txn.account_id,
                security_id=txn.security_id,
                open_transaction_id=txn.id,
                state="open",
                acquired_date=txn.trade_date,
                original_quantity=txn.quantity,
                remaining_quantity=txn.quantity,
                cost_basis_cents=txn.total_cents + txn.fee_cents,
                cost_basis_currency=txn.currency,
                fx_rate_at_open=txn.fx_rate,
            )
            session.add(lot)
            created += 1

        await session.commit()

    # Now match sells using FIFO
    async with async_session() as session:
        sell_result = await session.execute(
            select(Transaction)
            .where(
                Transaction.type.in_(["sell", "transfer_out"]),
                Transaction.security_id.isnot(None),
                Transaction.quantity > 0,
            )
            .order_by(Transaction.trade_date)
        )
        sells = sell_result.scalars().all()

        matched = 0
        for sell in sells:
            remaining_to_sell = sell.quantity

            # Find open lots for this security+account, FIFO order
            lots_result = await session.execute(
                select(TaxLot)
                .where(
                    TaxLot.account_id == sell.account_id,
                    TaxLot.security_id == sell.security_id,
                    TaxLot.state.in_(["open", "partially_closed"]),
                    TaxLot.remaining_quantity > 0,
                )
                .order_by(TaxLot.acquired_date)
            )
            open_lots = lots_result.scalars().all()

            for lot in open_lots:
                if remaining_to_sell <= 0:
                    break

                if lot.remaining_quantity <= remaining_to_sell:
                    # Fully close this lot
                    qty_closed = lot.remaining_quantity
                    proportion = float(qty_closed) / float(lot.original_quantity)
                    cost = int(lot.cost_basis_cents * proportion)
                    proceeds_proportion = float(qty_closed) / float(sell.quantity)
                    proceeds = int((sell.total_cents - sell.fee_cents) * proceeds_proportion)

                    lot.remaining_quantity = Decimal("0")
                    lot.state = "closed"
                    lot.closed_date = sell.trade_date
                    lot.close_transaction_id = sell.id
                    lot.proceeds_cents = proceeds
                    lot.realized_pnl_cents = proceeds - cost
                    lot.fx_rate_at_close = sell.fx_rate

                    remaining_to_sell -= qty_closed
                    matched += 1
                else:
                    # Partially close
                    qty_closed = remaining_to_sell
                    lot.remaining_quantity -= qty_closed
                    lot.state = "partially_closed"
                    matched += 1
                    remaining_to_sell = Decimal("0")

        await session.commit()

    return {
        "data": {"lotsCreated": created, "lotsMatched": matched},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }
