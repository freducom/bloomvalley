"""Tax-lot maintenance.

Hooks into every buy/sell transaction insert to keep `tax_lots` in sync,
so `/api/v1/tax/gains` reflects realized P&L without manual regeneration.

Partial closes split the parent lot: a new fully-closed lot is created
with proportional cost + proceeds, and the parent's
original_quantity/remaining_quantity/cost_basis are reduced. Without the
split, partial sells would leave realized P&L unrecorded (the closed
slice has no row of its own to attach proceeds to).

Cost basis and proceeds are normalized to EUR at lot creation/close time
using the FX rate from the transaction (if set) or the FxRate table
(nearest rate at-or-before trade_date). Finnish capital-gains reporting
is in EUR; storing native-currency cost against EUR proceeds (or vice
versa) produces garbage realized P&L. All lot rows therefore have
`cost_basis_currency = 'EUR'`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.prices import FxRate
from app.db.models.tax_lots import TaxLot
from app.db.models.transactions import Transaction

logger = structlog.get_logger()


async def _lookup_fx_table_rate(
    session: AsyncSession, currency: str, on_date: date
) -> Decimal | None:
    """Look up `quote_per_eur` from `fx_rates` (e.g., SEK per 1 EUR = 10.891).
    Picks the most recent rate at-or-before `on_date`; falls back to the
    latest available; returns None if the currency is unknown."""
    result = await session.execute(
        select(FxRate.rate)
        .where(
            FxRate.base_currency == "EUR",
            FxRate.quote_currency == currency,
            FxRate.date <= on_date,
        )
        .order_by(FxRate.date.desc())
        .limit(1)
    )
    rate = result.scalar_one_or_none()
    if rate is None:
        result = await session.execute(
            select(FxRate.rate)
            .where(
                FxRate.base_currency == "EUR",
                FxRate.quote_currency == currency,
            )
            .order_by(FxRate.date.desc())
            .limit(1)
        )
        rate = result.scalar_one_or_none()
    return Decimal(rate) if rate and rate > 0 else None


def _to_eur_cents(
    native_cents: int,
    currency: str | None,
    txn_fx_rate: Decimal | None,
    table_rate_quote_per_eur: Decimal | None,
) -> int:
    """Convert `native_cents` (in `currency`) to EUR cents.

    Conventions:
    - `txn_fx_rate` (from `transactions.fx_rate`) is **EUR per 1 unit of
      `currency`** — multiply: `eur = native * txn_fx_rate`.
    - `table_rate_quote_per_eur` (from `fx_rates.rate` with base=EUR) is
      **`currency` per 1 EUR** — divide: `eur = native / table_rate`.

    Prefers `txn_fx_rate` (close to the actual fill rate). Falls back to
    the table rate, then to native (logged as missing FX)."""
    if not native_cents or not currency or currency == "EUR":
        return int(native_cents or 0)

    if txn_fx_rate and txn_fx_rate > 0:
        return int(Decimal(native_cents) * Decimal(txn_fx_rate))

    if table_rate_quote_per_eur and table_rate_quote_per_eur > 0:
        return int(Decimal(native_cents) / table_rate_quote_per_eur)

    logger.warning("tax_lot_fx_missing", currency=currency, native_cents=native_cents)
    return int(native_cents)


async def _txn_total_eur_cents(session: AsyncSession, txn: Transaction) -> tuple[int, int, Decimal | None]:
    """Convert a transaction's `total_cents` (in `currency`) and `fee_cents`
    (in `fee_currency`) to EUR cents. Returns (total_eur, fee_eur, fx_used)
    where fx_used is the EUR-per-native rate for `currency` if known."""
    txn_fx = Decimal(txn.fx_rate) if txn.fx_rate else None
    table_rate = (
        await _lookup_fx_table_rate(session, txn.currency, txn.trade_date)
        if txn.currency and txn.currency != "EUR"
        else None
    )
    total_eur = _to_eur_cents(txn.total_cents or 0, txn.currency, txn_fx, table_rate)

    fee_currency = txn.fee_currency or txn.currency
    if fee_currency == txn.currency:
        fee_table_rate = table_rate
        fee_txn_fx = txn_fx
    else:
        fee_table_rate = (
            await _lookup_fx_table_rate(session, fee_currency, txn.trade_date)
            if fee_currency and fee_currency != "EUR"
            else None
        )
        fee_txn_fx = None
    fee_eur = _to_eur_cents(txn.fee_cents or 0, fee_currency, fee_txn_fx, fee_table_rate)

    # Normalized fx record: EUR per native. Prefer the transaction's own rate.
    fx_for_record: Decimal | None
    if txn_fx and txn_fx > 0:
        fx_for_record = txn_fx
    elif table_rate and table_rate > 0:
        fx_for_record = Decimal(1) / table_rate
    else:
        fx_for_record = None

    return total_eur, fee_eur, fx_for_record


async def apply_buy(session: AsyncSession, txn: Transaction) -> bool:
    """Create an open lot for a buy/transfer_in, with cost basis in EUR.
    Idempotent on `open_transaction_id`. Returns True if a lot was
    created."""
    result = await session.execute(
        select(TaxLot.id).where(TaxLot.open_transaction_id == txn.id).limit(1)
    )
    if result.scalar_one_or_none() is not None:
        return False

    total_eur, fee_eur, fx_for_record = await _txn_total_eur_cents(session, txn)
    cost_eur = total_eur + fee_eur

    lot = TaxLot(
        account_id=txn.account_id,
        security_id=txn.security_id,
        open_transaction_id=txn.id,
        state="open",
        acquired_date=txn.trade_date,
        original_quantity=txn.quantity,
        remaining_quantity=txn.quantity,
        cost_basis_cents=cost_eur,
        cost_basis_currency="EUR",
        fx_rate_at_open=fx_for_record,
    )
    session.add(lot)
    return True


async def apply_sell(session: AsyncSession, txn: Transaction) -> int:
    """FIFO-match a sell/transfer_out against open lots. Partial closes
    split the parent lot. Idempotent on `close_transaction_id`. Returns
    the number of lots closed by this sell."""
    result = await session.execute(
        select(TaxLot.id).where(TaxLot.close_transaction_id == txn.id).limit(1)
    )
    if result.scalar_one_or_none() is not None:
        return 0

    if txn.quantity is None or txn.quantity <= 0:
        return 0

    remaining = txn.quantity
    total_eur, fee_eur, fx_for_record = await _txn_total_eur_cents(session, txn)
    sell_net_cents = total_eur - fee_eur
    sell_qty = txn.quantity
    closed_count = 0

    while remaining > 0:
        lot_q = await session.execute(
            select(TaxLot)
            .where(
                TaxLot.account_id == txn.account_id,
                TaxLot.security_id == txn.security_id,
                TaxLot.state.in_(["open", "partially_closed"]),
                TaxLot.remaining_quantity > 0,
            )
            .order_by(TaxLot.acquired_date, TaxLot.id)
            .limit(1)
        )
        lot = lot_q.scalar_one_or_none()
        if lot is None:
            logger.warning(
                "tax_lot_sell_unmatched",
                txn_id=txn.id,
                security_id=txn.security_id,
                remaining=str(remaining),
            )
            break

        if lot.remaining_quantity <= remaining:
            qty_closed = lot.remaining_quantity
            cost_prop = Decimal(qty_closed) / Decimal(lot.original_quantity)
            cost = int(Decimal(lot.cost_basis_cents) * cost_prop)
            proceeds_prop = Decimal(qty_closed) / Decimal(sell_qty)
            proceeds = int(Decimal(sell_net_cents) * proceeds_prop)

            lot.remaining_quantity = Decimal("0")
            lot.state = "closed"
            lot.closed_date = txn.trade_date
            lot.close_transaction_id = txn.id
            lot.proceeds_cents = proceeds
            lot.realized_pnl_cents = proceeds - cost
            lot.fx_rate_at_close = fx_for_record

            remaining -= qty_closed
            closed_count += 1
        else:
            qty_closed = remaining
            cost_prop = Decimal(qty_closed) / Decimal(lot.original_quantity)
            cost_closed = int(Decimal(lot.cost_basis_cents) * cost_prop)
            proceeds_prop = Decimal(qty_closed) / Decimal(sell_qty)
            proceeds = int(Decimal(sell_net_cents) * proceeds_prop)

            split = TaxLot(
                account_id=lot.account_id,
                security_id=lot.security_id,
                open_transaction_id=lot.open_transaction_id,
                close_transaction_id=txn.id,
                state="closed",
                acquired_date=lot.acquired_date,
                closed_date=txn.trade_date,
                original_quantity=qty_closed,
                remaining_quantity=Decimal("0"),
                cost_basis_cents=cost_closed,
                cost_basis_currency="EUR",
                proceeds_cents=proceeds,
                realized_pnl_cents=proceeds - cost_closed,
                fx_rate_at_open=lot.fx_rate_at_open,
                fx_rate_at_close=fx_for_record,
            )
            session.add(split)

            lot.original_quantity = lot.original_quantity - qty_closed
            lot.remaining_quantity = lot.remaining_quantity - qty_closed
            lot.cost_basis_cents = lot.cost_basis_cents - cost_closed

            remaining = Decimal("0")
            closed_count += 1

    return closed_count


async def apply_transaction(session: AsyncSession, txn: Transaction) -> None:
    """Update lots based on transaction type. No-op for non-trade types or
    transactions without a security."""
    if not txn.security_id or txn.quantity is None or txn.quantity <= 0:
        return

    if txn.type in ("buy", "transfer_in"):
        await apply_buy(session, txn)
    elif txn.type in ("sell", "transfer_out"):
        await apply_sell(session, txn)
