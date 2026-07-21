"""Period-scoped portfolio performance (F24).

Breaks P&L over a user-picked date range into five buckets:
- realized gains / losses (from closed tax lots)
- dividends (from paid dividends)
- unrealized gains / losses (period-attributed price change on held shares)

All aggregates are in EUR cents. Realized and dividend rows are already
EUR-normalized in the DB; unrealized computation converts native-currency
prices and transaction cash-flows to EUR via `_lookup_fx_table_rate` from
tax_lots service.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import async_session
from app.db.models.dividends import Dividend
from app.db.models.prices import FxRate, Price
from app.db.models.securities import Security
from app.db.models.tax_lots import TaxLot
from app.db.models.transactions import Transaction
from app.services.tax_lots import _lookup_fx_table_rate, _to_eur_cents

logger = structlog.get_logger()

# Only these transaction types affect the share count for a security.
_SHARE_TXN_TYPES = ("buy", "sell", "transfer_in", "transfer_out")
_BUY_LIKE = ("buy", "transfer_in")
_SELL_LIKE = ("sell", "transfer_out")


async def _price_on_or_before(
    session: AsyncSession, security_id: int, on_date: date
) -> Optional[tuple[int, str, date]]:
    """Return (close_cents, currency, date) for the most recent bar at or before
    `on_date`. None if there is no price history for the security."""
    result = await session.execute(
        select(Price.close_cents, Price.currency, Price.date)
        .where(Price.security_id == security_id, Price.date <= on_date)
        .order_by(Price.date.desc())
        .limit(1)
    )
    row = result.first()
    return (row[0], row[1], row[2]) if row else None


async def compute_performance(from_date: date, to_date: date) -> dict:
    """Compute the 5-bucket P&L breakdown for the given period."""
    if from_date > to_date:
        return {"error": "invalid_range"}

    async with async_session() as session:
        # ── 1. Realized P&L: tax lots closed inside the window ────────────
        realized_by_security: dict[int, int] = {}
        realized_rows = await session.execute(
            select(TaxLot.security_id, TaxLot.realized_pnl_cents)
            .where(
                TaxLot.closed_date.isnot(None),
                TaxLot.closed_date.between(from_date, to_date),
                TaxLot.realized_pnl_cents.isnot(None),
            )
        )
        for sid, pnl in realized_rows.all():
            realized_by_security[sid] = realized_by_security.get(sid, 0) + int(pnl or 0)

        # ── 2. Dividends: paid inside the window ──────────────────────────
        # Prefer pay_date; fall back to ex_date when pay_date is null.
        dividend_by_security: dict[int, int] = {}
        div_rows = await session.execute(
            select(Dividend.security_id, Dividend.net_amount_eur_cents)
            .where(
                or_(
                    and_(
                        Dividend.pay_date.isnot(None),
                        Dividend.pay_date.between(from_date, to_date),
                    ),
                    and_(
                        Dividend.pay_date.is_(None),
                        Dividend.ex_date.between(from_date, to_date),
                    ),
                ),
            )
        )
        for sid, amt in div_rows.all():
            dividend_by_security[sid] = dividend_by_security.get(sid, 0) + int(amt or 0)

        # ── 3. Unrealized change per security ─────────────────────────────
        # Build per-security transaction lists up to `to_date` for share/flow math.
        txn_result = await session.execute(
            select(Transaction)
            .where(
                Transaction.security_id.isnot(None),
                Transaction.trade_date <= to_date,
                Transaction.type.in_(_SHARE_TXN_TYPES),
            )
            .order_by(Transaction.security_id, Transaction.trade_date, Transaction.id)
        )
        txns_by_sid: dict[int, list[Transaction]] = {}
        for t in txn_result.scalars().all():
            txns_by_sid.setdefault(t.security_id, []).append(t)

        # Pre-load security records for names/tickers/sector
        candidate_sids = (
            set(realized_by_security.keys())
            | set(dividend_by_security.keys())
            | set(txns_by_sid.keys())
        )
        if not candidate_sids:
            return _empty_response(from_date, to_date)

        sec_result = await session.execute(
            select(Security).where(Security.id.in_(candidate_sids))
        )
        sec_by_id: dict[int, Security] = {s.id: s for s in sec_result.scalars().all()}

        period_start_price_date = from_date - timedelta(days=1)

        by_security_rows: list[dict] = []
        totals = {
            "realizedGainCents": 0,
            "realizedLossCents": 0,
            "dividendCents": 0,
            "unrealizedGainCents": 0,
            "unrealizedLossCents": 0,
            "netCents": 0,
        }

        for sid in candidate_sids:
            sec = sec_by_id.get(sid)
            if sec is None:
                continue
            txns = txns_by_sid.get(sid, [])

            # Walk transactions to compute share balances and period-only cash flows.
            shares_end = Decimal(0)
            shares_start = Decimal(0)
            shares_bought_in_period = Decimal(0)  # gross buy shares in period (for avg-cost calc)
            buys_in_period_eur = 0  # gross cash paid for buys in period

            for t in txns:
                q = Decimal(t.quantity or 0)
                sign = 1 if t.type in _BUY_LIKE else -1
                shares_end += sign * q
                if t.trade_date < from_date:
                    shares_start += sign * q
                elif t.trade_date <= to_date:
                    if t.type in _BUY_LIKE:
                        shares_bought_in_period += q
                        buys_in_period_eur += await _txn_total_to_eur_cents(session, t)

            # Skip securities with no exposure and no realized/dividend activity.
            if (
                shares_end == 0
                and shares_start == 0
                and sid not in realized_by_security
                and sid not in dividend_by_security
            ):
                continue

            # Price anchors (only fetched when needed).
            price_end_cents: Optional[int] = None
            price_start_cents: Optional[int] = None
            price_end_eur_per_share: Optional[Decimal] = None
            price_start_eur_per_share: Optional[Decimal] = None
            v_end_eur = 0

            if shares_end != 0:
                p_end = await _price_on_or_before(session, sid, to_date)
                if p_end:
                    close_cents, cur, _ = p_end
                    price_end_cents = close_cents
                    price_end_eur_per_share = await _price_to_eur_per_share(
                        session, close_cents, cur, to_date
                    )
                    v_end_eur = int(
                        (Decimal(shares_end) * price_end_eur_per_share).to_integral_value()
                    )

            if shares_start != 0:
                p_start = await _price_on_or_before(session, sid, period_start_price_date)
                if p_start:
                    close_cents, cur, _ = p_start
                    price_start_cents = close_cents
                    price_start_eur_per_share = await _price_to_eur_per_share(
                        session, close_cents, cur, period_start_price_date
                    )

            # Unrealized bucket: only price movement on shares STILL HELD at period end.
            # Splits into "held throughout" (period-start → period-end price change) and
            # "bought during period, still held" (avg-buy → period-end price change).
            unrealized_change = 0

            shares_kept_from_before = min(max(shares_start, Decimal(0)), max(shares_end, Decimal(0)))
            shares_new_still_held = max(Decimal(0), shares_end - shares_kept_from_before)

            if shares_kept_from_before > 0 and price_end_eur_per_share is not None and price_start_eur_per_share is not None:
                unrealized_change += int(
                    (shares_kept_from_before * (price_end_eur_per_share - price_start_eur_per_share)).to_integral_value()
                )

            if shares_new_still_held > 0 and shares_bought_in_period > 0 and price_end_eur_per_share is not None:
                avg_buy_per_share_eur = Decimal(buys_in_period_eur) / shares_bought_in_period
                unrealized_change += int(
                    (shares_new_still_held * (price_end_eur_per_share - avg_buy_per_share_eur)).to_integral_value()
                )

            v_start_eur = int(
                (shares_start * price_start_eur_per_share).to_integral_value()
            ) if (shares_start != 0 and price_start_eur_per_share is not None) else 0

            realized_cents = realized_by_security.get(sid, 0)
            dividend_cents = dividend_by_security.get(sid, 0)
            net_cents = realized_cents + dividend_cents + unrealized_change

            if realized_cents > 0:
                totals["realizedGainCents"] += realized_cents
            elif realized_cents < 0:
                totals["realizedLossCents"] += realized_cents
            totals["dividendCents"] += dividend_cents
            if unrealized_change > 0:
                totals["unrealizedGainCents"] += unrealized_change
            elif unrealized_change < 0:
                totals["unrealizedLossCents"] += unrealized_change

            by_security_rows.append(
                {
                    "securityId": sec.id,
                    "ticker": sec.ticker,
                    "name": sec.name,
                    "assetClass": sec.asset_class,
                    "sector": sec.sector,
                    "realizedCents": realized_cents,
                    "dividendCents": dividend_cents,
                    "unrealizedChangeCents": unrealized_change,
                    "netCents": net_cents,
                    "sharesEnd": str(shares_end.normalize()) if shares_end != 0 else "0",
                    "sharesStart": str(shares_start.normalize()) if shares_start != 0 else "0",
                    "priceStartCents": price_start_cents,
                    "priceEndCents": price_end_cents,
                    "valueEndEurCents": v_end_eur,
                    "valueStartEurCents": v_start_eur,
                }
            )

        totals["netCents"] = (
            totals["realizedGainCents"]
            + totals["realizedLossCents"]
            + totals["dividendCents"]
            + totals["unrealizedGainCents"]
            + totals["unrealizedLossCents"]
        )

        by_security_rows.sort(key=lambda r: -abs(r["netCents"]))

        logger.info(
            "performance.compute",
            from_date=from_date.isoformat(),
            to_date=to_date.isoformat(),
            rows=len(by_security_rows),
            net_cents=totals["netCents"],
        )

        return {
            "period": {"from": from_date.isoformat(), "to": to_date.isoformat()},
            "currency": "EUR",
            "totals": totals,
            "bySecurity": by_security_rows,
        }


async def _txn_total_to_eur_cents(session: AsyncSession, txn: Transaction) -> int:
    """Convert a transaction's total_cents (native) to EUR cents using the
    transaction's own fx_rate if present, otherwise the FxRate table on trade_date."""
    if not txn.total_cents:
        return 0
    if not txn.currency or txn.currency == "EUR":
        return int(txn.total_cents)
    txn_fx = Decimal(txn.fx_rate) if txn.fx_rate else None
    table_rate = await _lookup_fx_table_rate(session, txn.currency, txn.trade_date)
    return _to_eur_cents(int(txn.total_cents), txn.currency, txn_fx, table_rate)


async def _price_to_eur_per_share(
    session: AsyncSession,
    price_cents: int,
    price_currency: str,
    on_date: date,
) -> Decimal:
    """Convert one share's price (native cents) to EUR cents per share.
    Uses FxRate on `on_date`; returns Decimal for downstream arithmetic."""
    if not price_currency or price_currency == "EUR":
        return Decimal(price_cents)
    table_rate = await _lookup_fx_table_rate(session, price_currency, on_date)
    if table_rate and table_rate > 0:
        return Decimal(price_cents) / Decimal(table_rate)
    return Decimal(price_cents)


def _empty_response(from_date: date, to_date: date) -> dict:
    return {
        "period": {"from": from_date.isoformat(), "to": to_date.isoformat()},
        "currency": "EUR",
        "totals": {
            "realizedGainCents": 0,
            "realizedLossCents": 0,
            "dividendCents": 0,
            "unrealizedGainCents": 0,
            "unrealizedLossCents": 0,
            "netCents": 0,
        },
        "bySecurity": [],
    }
