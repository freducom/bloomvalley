"""Tax-aware rebalancing suggestions engine.

Computes portfolio drift from glidepath targets and generates trade
suggestions with Finnish capital gains tax impact calculations.

All monetary values are integers in cents (EUR) — no floats for money.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import Account
from app.db.models.holdings_snapshot import HoldingsSnapshot
from app.db.models.prices import FxRate, Price
from app.db.models.securities import Security
from app.db.models.tax_lots import TaxLot
from app.db.models.transactions import Transaction
from app.services.optimizer import (
    ASSET_CLASS_MAP,
    GLIDEPATH,
    MIN_DRIFT_CENTS,
    MIN_TRADE_CENTS,
    TAX_HIGH_THRESHOLD_CENTS,
    TAX_RATE_HIGH,
    TAX_RATE_STANDARD,
)

logger = structlog.get_logger()

# Minimum trade size in EUR cents for the rebalancing endpoint (100 EUR)
MIN_TRADE_EUR_CENTS = 10_000

# Birth year for age calculation
BIRTH_YEAR = 1981


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TaxImpact:
    realized_gain_cents: int
    estimated_tax_cents: int
    tax_rate: float
    used_deemed_cost: bool
    is_osakesaastotili: bool


@dataclass
class SuggestedTrade:
    action: str  # "buy" or "sell"
    security_id: int
    security_name: str
    ticker: str
    account_id: int
    account_name: str
    quantity: Decimal
    estimated_proceeds_cents: int
    estimated_proceeds_currency: str
    estimated_proceeds_eur_cents: int
    tax_impact: TaxImpact | None


@dataclass
class AllocationEntry:
    actual: float
    target: float
    drift: float


@dataclass
class RebalancingSummary:
    total_sells_eur_cents: int
    total_buys_eur_cents: int
    net_cash_flow_eur_cents: int
    total_estimated_tax_eur_cents: int


@dataclass
class RebalancingResult:
    current_allocation: dict[str, AllocationEntry]
    suggested_trades: list[SuggestedTrade]
    summary: RebalancingSummary
    mode: str
    message: str | None = None


# ---------------------------------------------------------------------------
# Holding representation used internally
# ---------------------------------------------------------------------------


@dataclass
class HoldingPosition:
    security_id: int
    security_name: str
    ticker: str
    asset_class: str  # glidepath category: equity, fixed_income, crypto, cash
    account_id: int
    account_name: str
    account_type: str  # regular, osakesaastotili, etc.
    quantity: Decimal
    market_value_eur_cents: int
    cost_basis_eur_cents: int
    unrealized_pnl_eur_cents: int
    price_currency: str
    current_price_cents: int  # in native currency
    fx_rate: Decimal  # EUR/native (e.g. EUR/USD)
    acquired_date: date | None = None


@dataclass
class TaxLotInfo:
    lot_id: int
    account_id: int
    account_type: str
    security_id: int
    remaining_quantity: Decimal
    cost_basis_cents: int  # total cost for remaining qty
    cost_per_unit_cents: int
    acquired_date: date
    holding_years: float


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _current_age() -> int:
    """Compute current age from birth year."""
    today = date.today()
    return today.year - BIRTH_YEAR


def _interpolate_glidepath(age: int) -> dict[str, float]:
    """Interpolate glidepath targets for a given age.

    Uses linear interpolation between defined glidepath ages.
    """
    ages = sorted(GLIDEPATH.keys())

    if age <= ages[0]:
        return dict(GLIDEPATH[ages[0]])
    if age >= ages[-1]:
        return dict(GLIDEPATH[ages[-1]])

    # Find surrounding ages
    for i in range(len(ages) - 1):
        if ages[i] <= age <= ages[i + 1]:
            lower_age = ages[i]
            upper_age = ages[i + 1]
            break
    else:
        return dict(GLIDEPATH[ages[0]])

    fraction = (age - lower_age) / (upper_age - lower_age)
    lower_targets = GLIDEPATH[lower_age]
    upper_targets = GLIDEPATH[upper_age]

    result = {}
    for key in lower_targets:
        result[key] = lower_targets[key] + fraction * (
            upper_targets[key] - lower_targets[key]
        )
    return result


def _map_asset_class(asset_class: str, sector: str | None) -> str:
    """Map a security's asset_class to a glidepath category."""
    if asset_class == "etf" and sector and "fixed income" in sector.lower():
        return "fixed_income"
    if asset_class == "fund":
        # Equity funds → equity; everything else (bond, money market, mixed) → fixed_income
        if sector and "equity" in sector.lower():
            return "equity"
        return "fixed_income"
    return ASSET_CLASS_MAP.get(asset_class, "equity")


def _compute_finnish_tax(
    gain_cents: int,
    proceeds_cents: int,
    holding_years: float,
    ytd_realized_gains_cents: int,
    is_ost: bool,
) -> TaxImpact:
    """Compute Finnish capital gains tax for a single sell.

    Rules:
    - OST: no tax
    - Deemed cost of acquisition: 20% of proceeds, or 40% if held >10 years
    - If deemed cost > actual cost basis, use deemed cost
    - 30% on gains <= 30,000 EUR/year, 34% above
    """
    if is_ost:
        return TaxImpact(
            realized_gain_cents=0,
            estimated_tax_cents=0,
            tax_rate=0.0,
            used_deemed_cost=False,
            is_osakesaastotili=True,
        )

    # Deemed cost of acquisition
    deemed_pct = 0.40 if holding_years >= 10 else 0.20
    deemed_cost_cents = int(proceeds_cents * deemed_pct)
    deemed_gain_cents = proceeds_cents - deemed_cost_cents

    used_deemed = False
    if deemed_gain_cents < gain_cents and deemed_gain_cents >= 0:
        # Deemed cost is more favorable (lower gain)
        effective_gain = deemed_gain_cents
        used_deemed = True
    else:
        effective_gain = gain_cents

    if effective_gain <= 0:
        return TaxImpact(
            realized_gain_cents=effective_gain,
            estimated_tax_cents=0,
            tax_rate=0.0,
            used_deemed_cost=used_deemed,
            is_osakesaastotili=False,
        )

    # Determine marginal rate based on YTD gains + this gain
    total_gains = ytd_realized_gains_cents + effective_gain

    if total_gains <= TAX_HIGH_THRESHOLD_CENTS:
        # All at 30%
        tax = int(effective_gain * TAX_RATE_STANDARD)
        rate = TAX_RATE_STANDARD * 100
    elif ytd_realized_gains_cents >= TAX_HIGH_THRESHOLD_CENTS:
        # All at 34%
        tax = int(effective_gain * TAX_RATE_HIGH)
        rate = TAX_RATE_HIGH * 100
    else:
        # Split: portion at 30%, remainder at 34%
        portion_at_30 = TAX_HIGH_THRESHOLD_CENTS - ytd_realized_gains_cents
        portion_at_34 = effective_gain - portion_at_30
        tax = int(portion_at_30 * TAX_RATE_STANDARD) + int(
            portion_at_34 * TAX_RATE_HIGH
        )
        # Blended rate
        rate = round((tax / effective_gain) * 100, 1) if effective_gain > 0 else 0.0

    return TaxImpact(
        realized_gain_cents=effective_gain,
        estimated_tax_cents=tax,
        tax_rate=rate,
        used_deemed_cost=used_deemed,
        is_osakesaastotili=False,
    )


# ---------------------------------------------------------------------------
# Database queries
# ---------------------------------------------------------------------------


async def _fetch_latest_holdings(
    session: AsyncSession,
) -> list[HoldingPosition]:
    """Fetch the latest holdings snapshot with security and account info."""
    # Find the latest snapshot date
    latest_date_q = select(func.max(HoldingsSnapshot.snapshot_date))
    latest_date = (await session.execute(latest_date_q)).scalar_one_or_none()

    if latest_date is None:
        return []

    # Fetch all holdings for that date, joined with security and account
    q = (
        select(HoldingsSnapshot, Security, Account)
        .join(Security, HoldingsSnapshot.security_id == Security.id)
        .join(Account, HoldingsSnapshot.account_id == Account.id)
        .where(HoldingsSnapshot.snapshot_date == latest_date)
    )
    result = await session.execute(q)
    rows = result.all()

    holdings: list[HoldingPosition] = []
    for hs, sec, acct in rows:
        gp_class = _map_asset_class(sec.asset_class, sec.sector)
        fx = hs.fx_rate if hs.fx_rate else Decimal("1.0")

        holdings.append(
            HoldingPosition(
                security_id=sec.id,
                security_name=sec.name,
                ticker=sec.ticker,
                asset_class=gp_class,
                account_id=acct.id,
                account_name=acct.name,
                account_type=acct.type,
                quantity=hs.quantity,
                market_value_eur_cents=hs.market_value_eur_cents,
                cost_basis_eur_cents=hs.cost_basis_cents,
                unrealized_pnl_eur_cents=hs.unrealized_pnl_eur_cents,
                price_currency=hs.market_price_currency,
                current_price_cents=hs.market_price_cents,
                fx_rate=fx,
            )
        )

    return holdings


async def _fetch_tax_lots(
    session: AsyncSession,
    security_ids: set[int],
) -> dict[tuple[int, int], list[TaxLotInfo]]:
    """Fetch open/partially-closed tax lots for given securities.

    Returns dict keyed by (account_id, security_id) -> list of TaxLotInfo.
    """
    if not security_ids:
        return {}

    q = (
        select(TaxLot, Account)
        .join(Account, TaxLot.account_id == Account.id)
        .where(
            TaxLot.security_id.in_(security_ids),
            TaxLot.state.in_(["open", "partially_closed"]),
            TaxLot.remaining_quantity > 0,
        )
        .order_by(TaxLot.acquired_date.asc())
    )
    result = await session.execute(q)
    rows = result.all()

    today = date.today()
    lots_map: dict[tuple[int, int], list[TaxLotInfo]] = {}

    for lot, acct in rows:
        key = (lot.account_id, lot.security_id)
        if key not in lots_map:
            lots_map[key] = []

        days_held = (today - lot.acquired_date).days
        holding_years = days_held / 365.25

        # Cost per unit in cents (cost_basis_cents is total for remaining)
        remaining = lot.remaining_quantity
        original = lot.original_quantity
        if original > 0 and remaining > 0:
            # Pro-rate cost basis for remaining quantity
            total_cost = lot.cost_basis_cents
            cost_for_remaining = int(
                total_cost * (remaining / original)
            ) if remaining != original else total_cost
            cost_per_unit = int(cost_for_remaining / int(remaining)) if int(remaining) > 0 else 0
        else:
            cost_for_remaining = 0
            cost_per_unit = 0

        lots_map[key].append(
            TaxLotInfo(
                lot_id=lot.id,
                account_id=lot.account_id,
                account_type=acct.type,
                security_id=lot.security_id,
                remaining_quantity=remaining,
                cost_basis_cents=cost_for_remaining,
                cost_per_unit_cents=cost_per_unit,
                acquired_date=lot.acquired_date,
                holding_years=holding_years,
            )
        )

    return lots_map


async def _fetch_ytd_realized_gains(session: AsyncSession) -> int:
    """Sum of realized gains from closed tax lots this year (EUR cents)."""
    year_start = date(date.today().year, 1, 1)
    q = select(func.coalesce(func.sum(TaxLot.realized_pnl_cents), 0)).where(
        TaxLot.state == "closed",
        TaxLot.closed_date >= year_start,
        TaxLot.realized_pnl_cents > 0,
    )
    result = (await session.execute(q)).scalar_one()
    return int(result)


async def _fetch_cash_balances(session: AsyncSession) -> int:
    """Sum of cash balances across all active accounts (EUR cents)."""
    q = select(func.coalesce(func.sum(Account.cash_balance_cents), 0)).where(
        Account.is_active.is_(True)
    )
    result = (await session.execute(q)).scalar_one()
    return int(result)


# ---------------------------------------------------------------------------
# Trade generation
# ---------------------------------------------------------------------------


def _sell_sort_key_minimize_tax(
    pos: HoldingPosition,
) -> tuple[int, int, int]:
    """Sort key for sell order in minimize_tax mode.

    Priority (lower = sell first):
    1. OST positions (tax-free)
    2. Loss positions (tax-deductible)
    3. Smallest gains
    """
    is_ost = 0 if pos.account_type == "osakesaastotili" else 1
    is_loss = 0 if pos.unrealized_pnl_eur_cents < 0 else 1
    return (is_ost, is_loss, pos.unrealized_pnl_eur_cents)


def _lot_sort_key_minimize_tax(lot: TaxLotInfo) -> tuple[int, int, int, float]:
    """Sort key for lot selection in minimize_tax mode.

    Priority (lower = sell first):
    1. OST lots (tax-free)
    2. Loss lots
    3. Lots held >10 years (40% deemed cost)
    4. Highest cost basis (smallest gain)
    """
    is_ost = 0 if lot.account_type == "osakesaastotili" else 1
    # Approximate gain: negative cost_per_unit means we don't know, treat as neutral
    is_loss = 0  # We'll use cost_per_unit as proxy
    has_10yr = 0 if lot.holding_years >= 10 else 1
    # Higher cost = smaller gain = sell first (negate for ascending sort)
    return (is_ost, is_loss, has_10yr, -lot.cost_per_unit_cents)


def _generate_sells(
    overweight_positions: list[HoldingPosition],
    sell_amounts_by_class: dict[str, int],
    lots_map: dict[tuple[int, int], list[TaxLotInfo]],
    ytd_gains_cents: int,
    mode: str,
) -> tuple[list[SuggestedTrade], int]:
    """Generate sell trades to reduce overweight asset classes.

    Returns (trades, running_ytd_gains).
    """
    trades: list[SuggestedTrade] = []
    running_ytd = ytd_gains_cents

    # Group positions by asset class
    positions_by_class: dict[str, list[HoldingPosition]] = {}
    for pos in overweight_positions:
        ac = pos.asset_class
        if ac not in positions_by_class:
            positions_by_class[ac] = []
        positions_by_class[ac].append(pos)

    for asset_class, sell_amount_cents in sell_amounts_by_class.items():
        if sell_amount_cents <= 0:
            continue

        positions = positions_by_class.get(asset_class, [])
        if not positions:
            continue

        # Sort positions by sell priority
        if mode == "minimize_tax":
            positions.sort(key=_sell_sort_key_minimize_tax)

        remaining = sell_amount_cents
        for pos in positions:
            if remaining < MIN_TRADE_EUR_CENTS:
                break

            # How much can we sell from this position?
            sellable = min(pos.market_value_eur_cents, remaining)
            if sellable < MIN_TRADE_EUR_CENTS:
                continue

            # Get tax lots for this position
            lots = lots_map.get((pos.account_id, pos.security_id), [])

            if mode == "minimize_tax" and lots:
                lots.sort(key=_lot_sort_key_minimize_tax)
            # exact_target mode: FIFO (lots already sorted by acquired_date)

            # Calculate how many units to sell
            if pos.current_price_cents > 0 and pos.fx_rate > 0:
                price_eur_cents = int(
                    pos.current_price_cents / float(pos.fx_rate)
                ) if pos.price_currency != "EUR" else pos.current_price_cents
                if price_eur_cents > 0:
                    units_to_sell = Decimal(str(sellable)) / Decimal(str(price_eur_cents))
                else:
                    units_to_sell = Decimal("0")
            else:
                units_to_sell = Decimal("0")

            # Cap at available quantity
            if units_to_sell > pos.quantity:
                units_to_sell = pos.quantity
                sellable = pos.market_value_eur_cents

            if units_to_sell <= 0:
                continue

            # Calculate tax impact from lots
            is_ost = pos.account_type == "osakesaastotili"

            if is_ost:
                tax_impact = TaxImpact(
                    realized_gain_cents=0,
                    estimated_tax_cents=0,
                    tax_rate=0.0,
                    used_deemed_cost=False,
                    is_osakesaastotili=True,
                )
            elif lots:
                # Compute gain from the lots we'd sell
                units_remaining = units_to_sell
                total_cost = 0
                total_proceeds = 0
                max_holding_years = 0.0

                for lot in lots:
                    if units_remaining <= 0:
                        break
                    lot_units = min(lot.remaining_quantity, units_remaining)
                    lot_cost = int(lot.cost_per_unit_cents * int(lot_units))
                    lot_proceeds_eur = int(
                        float(lot_units) * (
                            pos.current_price_cents / float(pos.fx_rate)
                            if pos.price_currency != "EUR"
                            else pos.current_price_cents
                        )
                    )
                    total_cost += lot_cost
                    total_proceeds += lot_proceeds_eur
                    max_holding_years = max(max_holding_years, lot.holding_years)
                    units_remaining -= lot_units

                gain = total_proceeds - total_cost
                tax_impact = _compute_finnish_tax(
                    gain_cents=gain,
                    proceeds_cents=total_proceeds,
                    holding_years=max_holding_years,
                    ytd_realized_gains_cents=running_ytd,
                    is_ost=False,
                )
                if gain > 0:
                    running_ytd += tax_impact.realized_gain_cents
            else:
                # No tax lots available, estimate from snapshot data
                proportion = sellable / pos.market_value_eur_cents if pos.market_value_eur_cents > 0 else 0
                gain = int(pos.unrealized_pnl_eur_cents * proportion)
                tax_impact = _compute_finnish_tax(
                    gain_cents=gain,
                    proceeds_cents=sellable,
                    holding_years=0,
                    ytd_realized_gains_cents=running_ytd,
                    is_ost=False,
                )
                if gain > 0:
                    running_ytd += tax_impact.realized_gain_cents

            # Determine proceeds in native currency
            if pos.price_currency != "EUR":
                native_proceeds = int(float(units_to_sell) * pos.current_price_cents)
            else:
                native_proceeds = sellable

            trades.append(
                SuggestedTrade(
                    action="sell",
                    security_id=pos.security_id,
                    security_name=pos.security_name,
                    ticker=pos.ticker,
                    account_id=pos.account_id,
                    account_name=pos.account_name,
                    quantity=units_to_sell,
                    estimated_proceeds_cents=native_proceeds,
                    estimated_proceeds_currency=pos.price_currency,
                    estimated_proceeds_eur_cents=sellable,
                    tax_impact=tax_impact,
                )
            )

            remaining -= sellable

    return trades, running_ytd


def _generate_buys(
    underweight_classes: dict[str, int],
    available_eur_cents: int,
    holdings: list[HoldingPosition],
) -> list[SuggestedTrade]:
    """Generate buy trades for underweight asset classes.

    For simplicity, suggest buying into existing positions within
    the underweight asset class. If no existing positions, note the class.
    """
    trades: list[SuggestedTrade] = []

    # Group existing holdings by asset class (pick the largest position per class)
    best_by_class: dict[str, HoldingPosition] = {}
    for pos in holdings:
        ac = pos.asset_class
        if ac not in best_by_class or pos.market_value_eur_cents > best_by_class[ac].market_value_eur_cents:
            best_by_class[ac] = pos

    budget = available_eur_cents

    # Sort by largest underweight first
    sorted_classes = sorted(underweight_classes.items(), key=lambda x: -x[1])

    for asset_class, buy_amount_cents in sorted_classes:
        if buy_amount_cents <= 0 or budget < MIN_TRADE_EUR_CENTS:
            continue

        actual_buy = min(buy_amount_cents, budget)
        if actual_buy < MIN_TRADE_EUR_CENTS:
            continue

        pos = best_by_class.get(asset_class)
        if not pos:
            # No existing position to buy into — skip with a note
            logger.info(
                "rebalancer_no_position_for_buy",
                asset_class=asset_class,
                amount_cents=actual_buy,
            )
            continue

        # Calculate units
        if pos.current_price_cents > 0 and pos.fx_rate > 0:
            price_eur_cents = int(
                pos.current_price_cents / float(pos.fx_rate)
            ) if pos.price_currency != "EUR" else pos.current_price_cents
            if price_eur_cents > 0:
                units_to_buy = Decimal(str(actual_buy)) / Decimal(str(price_eur_cents))
            else:
                units_to_buy = Decimal("0")
        else:
            units_to_buy = Decimal("0")

        if units_to_buy <= 0:
            continue

        # Native currency proceeds
        if pos.price_currency != "EUR":
            native_amount = int(float(units_to_buy) * pos.current_price_cents)
        else:
            native_amount = actual_buy

        trades.append(
            SuggestedTrade(
                action="buy",
                security_id=pos.security_id,
                security_name=pos.security_name,
                ticker=pos.ticker,
                account_id=pos.account_id,
                account_name=pos.account_name,
                quantity=units_to_buy,
                estimated_proceeds_cents=native_amount,
                estimated_proceeds_currency=pos.price_currency,
                estimated_proceeds_eur_cents=actual_buy,
                tax_impact=None,
            )
        )

        budget -= actual_buy

    return trades


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def compute_rebalancing(
    session: AsyncSession,
    mode: str = "minimize_tax",
) -> RebalancingResult:
    """Compute tax-aware rebalancing suggestions.

    Args:
        session: async database session.
        mode: "minimize_tax" (default) or "exact_target".

    Returns:
        RebalancingResult with allocation, trades, and summary.
    """
    # 1. Fetch current holdings
    holdings = await _fetch_latest_holdings(session)

    if not holdings:
        return RebalancingResult(
            current_allocation={},
            suggested_trades=[],
            summary=RebalancingSummary(
                total_sells_eur_cents=0,
                total_buys_eur_cents=0,
                net_cash_flow_eur_cents=0,
                total_estimated_tax_eur_cents=0,
            ),
            mode=mode,
            message="No holdings found. Import portfolio data first.",
        )

    # 2. Compute total portfolio value
    total_value_cents = sum(h.market_value_eur_cents for h in holdings)
    if total_value_cents <= 0:
        return RebalancingResult(
            current_allocation={},
            suggested_trades=[],
            summary=RebalancingSummary(
                total_sells_eur_cents=0,
                total_buys_eur_cents=0,
                net_cash_flow_eur_cents=0,
                total_estimated_tax_eur_cents=0,
            ),
            mode=mode,
            message="Portfolio value is zero.",
        )

    # 3. Compute actual allocation by glidepath category
    actual_by_class: dict[str, int] = {}
    for h in holdings:
        ac = h.asset_class
        actual_by_class[ac] = actual_by_class.get(ac, 0) + h.market_value_eur_cents

    # Add cash from accounts
    cash_cents = await _fetch_cash_balances(session)
    total_with_cash = total_value_cents + cash_cents
    actual_by_class["cash"] = actual_by_class.get("cash", 0) + cash_cents

    # 4. Get target allocation (glidepath for current age)
    age = _current_age()
    targets = _interpolate_glidepath(age)

    # 5. Compute drift
    all_classes = set(list(targets.keys()) + list(actual_by_class.keys()))
    allocation: dict[str, AllocationEntry] = {}
    sell_amounts: dict[str, int] = {}
    buy_amounts: dict[str, int] = {}

    for ac in all_classes:
        actual_cents = actual_by_class.get(ac, 0)
        actual_pct = (actual_cents / total_with_cash * 100) if total_with_cash > 0 else 0.0
        target_pct = targets.get(ac, 0.0) * 100
        drift_pct = actual_pct - target_pct

        allocation[ac] = AllocationEntry(
            actual=round(actual_pct, 1),
            target=round(target_pct, 1),
            drift=round(drift_pct, 1),
        )

        # Drift in cents
        drift_cents = actual_cents - int(targets.get(ac, 0.0) * total_with_cash)

        if drift_cents > MIN_DRIFT_CENTS:
            sell_amounts[ac] = drift_cents
        elif drift_cents < -MIN_DRIFT_CENTS:
            buy_amounts[ac] = abs(drift_cents)

    # 6. Check if balanced
    if not sell_amounts and not buy_amounts:
        return RebalancingResult(
            current_allocation=allocation,
            suggested_trades=[],
            summary=RebalancingSummary(
                total_sells_eur_cents=0,
                total_buys_eur_cents=0,
                net_cash_flow_eur_cents=0,
                total_estimated_tax_eur_cents=0,
            ),
            mode=mode,
            message="Portfolio is balanced",
        )

    # 7. Fetch tax lots for sell candidates
    sell_security_ids = {
        h.security_id
        for h in holdings
        if h.asset_class in sell_amounts
    }
    lots_map = await _fetch_tax_lots(session, sell_security_ids)

    # 8. Fetch YTD realized gains
    ytd_gains = await _fetch_ytd_realized_gains(session)

    # 9. Generate sell trades
    overweight_positions = [h for h in holdings if h.asset_class in sell_amounts]
    sell_trades, updated_ytd = _generate_sells(
        overweight_positions=overweight_positions,
        sell_amounts_by_class=sell_amounts,
        lots_map=lots_map,
        ytd_gains_cents=ytd_gains,
        mode=mode,
    )

    # 10. Generate buy trades (fund from sell proceeds + available cash)
    total_sell_proceeds = sum(t.estimated_proceeds_eur_cents for t in sell_trades)
    available_for_buys = total_sell_proceeds + cash_cents
    buy_trades = _generate_buys(buy_amounts, available_for_buys, holdings)

    # If insufficient cash for buys, trades are already adjusted downward
    total_buy_amount = sum(t.estimated_proceeds_eur_cents for t in buy_trades)

    # 11. Build summary
    total_tax = sum(
        t.tax_impact.estimated_tax_cents
        for t in sell_trades
        if t.tax_impact
    )
    net_cash = total_sell_proceeds - total_buy_amount

    summary = RebalancingSummary(
        total_sells_eur_cents=total_sell_proceeds,
        total_buys_eur_cents=total_buy_amount,
        net_cash_flow_eur_cents=net_cash,
        total_estimated_tax_eur_cents=total_tax,
    )

    all_trades = sell_trades + buy_trades

    # Filter out trades below minimum size
    all_trades = [t for t in all_trades if t.estimated_proceeds_eur_cents >= MIN_TRADE_EUR_CENTS]

    note = None
    if buy_amounts and total_buy_amount < sum(buy_amounts.values()):
        note = "Insufficient cash for full rebalancing. Buy quantities adjusted downward."

    logger.info(
        "rebalancing_computed",
        mode=mode,
        age=age,
        n_sells=len(sell_trades),
        n_buys=len(buy_trades),
        total_sell_cents=total_sell_proceeds,
        total_buy_cents=total_buy_amount,
        total_tax_cents=total_tax,
    )

    return RebalancingResult(
        current_allocation=allocation,
        suggested_trades=all_trades,
        summary=summary,
        mode=mode,
        message=note,
    )
