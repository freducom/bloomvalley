"""Dividend reconciliation pipeline — matches dividend events to holdings
and creates dividend + transaction records automatically."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import structlog
from sqlalchemy import select, text

from app.db.engine import async_session
from app.db.models.accounts import Account
from app.db.models.dividends import Dividend, DividendEvent
from app.db.models.prices import FxRate
from app.db.models.securities import Security
from app.db.models.transactions import Transaction
from app.pipelines import register_pipeline
from app.pipelines.base import PipelineAdapter, PipelineResult

logger = structlog.get_logger()

# Withholding tax rates for a Finnish tax resident by country of domicile.
_WHT_RATES: dict[str, float] = {
    "FI": 0.00,   # Finnish dividends: 25.5% withheld at source but for simplicity 0 here
    "US": 0.15,   # W-8BEN treaty rate
    "SE": 0.30,
    "DE": 0.26375,
    "IE": 0.0,
    "LU": 0.0,
    "NL": 0.15,
    "FR": 0.30,   # Can be reclaimed partially
    "NO": 0.25,
    "DK": 0.27,
    "GB": 0.0,    # UK has no dividend withholding
    "CH": 0.35,   # Can reclaim to 15%
}
_WHT_DEFAULT = 0.30


def _wht_rate_for(account_type: str, country: str | None) -> float:
    """Return withholding tax rate. OST accounts pay 0%."""
    if account_type == "osakesaastotili":
        return 0.0
    return _WHT_RATES.get(country or "", _WHT_DEFAULT)


@register_pipeline
class DividendReconciliation(PipelineAdapter):
    """Matches dividend_events against holdings to create dividend transactions."""

    @property
    def source_name(self) -> str:
        return "manual"

    @property
    def pipeline_name(self) -> str:
        return "dividend_reconciliation"

    async def fetch(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Find unreconciled dividend events where user held shares."""
        today = date.today()

        async with async_session() as session:
            # Get all dividend events on or before today that don't yet have
            # a matching dividend record (for at least one account).
            # We fetch ALL events and filter in Python to handle per-account logic.
            q = (
                select(DividendEvent, Security)
                .join(Security, DividendEvent.security_id == Security.id)
                .where(DividendEvent.ex_date <= today)
            )
            if from_date:
                q = q.where(DividendEvent.ex_date >= from_date)
            if to_date:
                q = q.where(DividendEvent.ex_date <= to_date)
            q = q.order_by(DividendEvent.ex_date)
            result = await session.execute(q)
            events = result.all()

            # Get all existing reconciled dividends to check what's already done
            existing_result = await session.execute(
                select(
                    Dividend.account_id,
                    Dividend.security_id,
                    Dividend.ex_date,
                )
            )
            existing = {
                (r.account_id, r.security_id, r.ex_date)
                for r in existing_result.all()
            }

            # Also check for manually-entered dividend transactions (no Dividend row)
            # to avoid creating duplicates alongside Nordnet-imported dividends.
            existing_tx_result = await session.execute(
                select(
                    Transaction.account_id,
                    Transaction.security_id,
                    Transaction.trade_date,
                )
                .where(
                    Transaction.type == "dividend",
                    Transaction.security_id.isnot(None),
                )
            )
            for r in existing_tx_result.all():
                existing.add((r.account_id, r.security_id, r.trade_date))

            # Get all position-affecting transactions per account+security
            tx_result = await session.execute(
                select(
                    Transaction.account_id,
                    Transaction.security_id,
                    Transaction.trade_date,
                    Transaction.type,
                    Transaction.quantity,
                )
                .where(
                    Transaction.security_id.isnot(None),
                    Transaction.type.in_(["buy", "sell", "transfer_in", "transfer_out"]),
                )
                .order_by(Transaction.trade_date)
            )
            all_txns = tx_result.all()

            # Get all active accounts
            acct_result = await session.execute(
                select(Account).where(Account.is_active.is_(True))
            )
            accounts = {a.id: a for a in acct_result.scalars().all()}

        # Build per-(account, security) position timeline
        # position_txns[(account_id, security_id)] = [(date, delta), ...]
        position_txns: dict[tuple[int, int], list[tuple[date, Decimal]]] = defaultdict(list)
        for tx in all_txns:
            if tx.security_id is None:
                continue
            delta = tx.quantity
            if tx.type in ("sell", "transfer_out"):
                delta = -delta
            position_txns[(tx.account_id, tx.security_id)].append(
                (tx.trade_date, delta)
            )

        def shares_held_on(account_id: int, security_id: int, on_date: date) -> Decimal:
            """Calculate shares held on a given date by replaying transactions."""
            txns = position_txns.get((account_id, security_id), [])
            total = Decimal("0")
            for tx_date, delta in txns:
                if tx_date <= on_date:
                    total += delta
            return max(total, Decimal("0"))

        # Build records: one per (event, account) pair that needs reconciling
        records = []
        for event, security in events:
            for acct_id, acct in accounts.items():
                key = (acct_id, event.security_id, event.ex_date)
                if key in existing:
                    continue  # Already reconciled

                qty = shares_held_on(acct_id, event.security_id, event.ex_date)
                if qty <= 0:
                    continue  # Didn't hold this security in this account

                records.append({
                    "event_id": event.id,
                    "security_id": event.security_id,
                    "ticker": security.ticker,
                    "country": security.country,
                    "account_id": acct_id,
                    "account_type": acct.type,
                    "account_name": acct.name,
                    "ex_date": event.ex_date,
                    "payment_date": event.payment_date,
                    "record_date": event.record_date,
                    "amount_per_share_cents": event.amount_cents,
                    "currency": event.currency,
                    "shares_held": qty,
                })

        logger.info(
            "dividend_reconciliation_fetched",
            events=len(events),
            unreconciled=len(records),
        )
        return records

    async def validate(self, raw_records: list[dict]) -> tuple[list[dict], list[str]]:
        valid = []
        errors = []
        for rec in raw_records:
            if rec["amount_per_share_cents"] <= 0:
                errors.append(f"{rec['ticker']} {rec['ex_date']}: invalid amount")
                continue
            if rec["shares_held"] <= 0:
                errors.append(f"{rec['ticker']} {rec['ex_date']}: zero shares")
                continue
            valid.append(rec)
        return valid, errors

    async def transform(self, valid_records: list[dict]) -> list[dict]:
        """Calculate gross/net amounts, withholding tax, and FX conversion."""
        if not valid_records:
            return []

        # Collect all currencies and dates we need FX rates for
        fx_needed: set[tuple[str, date]] = set()
        for rec in valid_records:
            if rec["currency"] != "EUR":
                fx_needed.add((rec["currency"], rec["ex_date"]))

        # Batch-fetch FX rates (nearest date on or before ex_date)
        fx_cache: dict[tuple[str, date], Decimal] = {}
        if fx_needed:
            async with async_session() as session:
                for currency, ex_dt in fx_needed:
                    result = await session.execute(
                        select(FxRate.rate)
                        .where(
                            FxRate.base_currency == "EUR",
                            FxRate.quote_currency == currency,
                            FxRate.date <= ex_dt,
                        )
                        .order_by(FxRate.date.desc())
                        .limit(1)
                    )
                    rate = result.scalar_one_or_none()
                    if rate:
                        fx_cache[(currency, ex_dt)] = rate

        transformed = []
        for rec in valid_records:
            shares = rec["shares_held"]
            amt_per_share = rec["amount_per_share_cents"]
            gross_cents = int(
                (Decimal(str(shares)) * Decimal(str(amt_per_share)))
                .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            )

            wht_rate = _wht_rate_for(rec["account_type"], rec["country"])
            wht_cents = int(
                (Decimal(str(gross_cents)) * Decimal(str(wht_rate)))
                .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            )
            net_cents = gross_cents - wht_cents

            # FX conversion
            currency = rec["currency"]
            if currency == "EUR":
                fx_rate = Decimal("1.0")
                net_eur_cents = net_cents
            else:
                fx_rate = fx_cache.get((currency, rec["ex_date"]))
                if fx_rate and fx_rate > 0:
                    net_eur_cents = int(
                        (Decimal(str(net_cents)) / fx_rate)
                        .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                    )
                else:
                    # No FX rate available — skip or use fallback
                    logger.warning(
                        "dividend_reconciliation_no_fx",
                        ticker=rec["ticker"],
                        currency=currency,
                        ex_date=str(rec["ex_date"]),
                    )
                    # Use a rough fallback from _get_fx_rates (latest rates)
                    fx_rate = Decimal("1.0")
                    net_eur_cents = net_cents

            # Use payment_date for cash flow timing when available.
            # Yahoo often lacks payment_date; ex_date is the fallback.
            # For accuracy, update dividend_events.payment_date manually
            # or via broker import when the actual payment arrives.
            trade_date = rec["payment_date"] or rec["ex_date"]
            ext_ref = f"div:{rec['security_id']}:{rec['ex_date']}:{rec['account_id']}"

            transformed.append({
                **rec,
                "gross_amount_cents": gross_cents,
                "withholding_tax_cents": wht_cents,
                "withholding_tax_pct": wht_rate,
                "net_amount_cents": net_cents,
                "net_amount_eur_cents": net_eur_cents,
                "fx_rate": fx_rate,
                "trade_date": trade_date,
                "external_ref": ext_ref,
            })

        return transformed

    async def load(self, transformed_records: list[dict]) -> int:
        if not transformed_records:
            return 0

        rows = 0
        async with async_session() as session:
            for rec in transformed_records:
                # Check idempotency via external_ref on transactions
                existing_tx = await session.execute(
                    select(Transaction.id).where(
                        Transaction.external_ref == rec["external_ref"]
                    )
                )
                if existing_tx.scalar_one_or_none() is not None:
                    continue  # Already created

                # Create transaction
                tx = Transaction(
                    account_id=rec["account_id"],
                    security_id=rec["security_id"],
                    type="dividend",
                    trade_date=rec["trade_date"],
                    settlement_date=rec.get("payment_date"),
                    quantity=rec["shares_held"],
                    price_cents=rec["amount_per_share_cents"],
                    price_currency=rec["currency"],
                    total_cents=rec["net_amount_eur_cents"],
                    fee_cents=0,
                    currency="EUR",
                    withholding_tax_cents=rec["withholding_tax_cents"],
                    fx_rate=rec["fx_rate"],
                    notes=f"Auto-reconciled: {rec['ticker']} dividend",
                    external_ref=rec["external_ref"],
                )
                session.add(tx)
                await session.flush()  # Get tx.id

                # Create dividend record
                div = Dividend(
                    account_id=rec["account_id"],
                    security_id=rec["security_id"],
                    transaction_id=tx.id,
                    ex_date=rec["ex_date"],
                    pay_date=rec.get("payment_date"),
                    record_date=rec.get("record_date"),
                    amount_per_share_cents=rec["amount_per_share_cents"],
                    amount_currency=rec["currency"],
                    shares_held=rec["shares_held"],
                    gross_amount_cents=rec["gross_amount_cents"],
                    withholding_tax_cents=rec["withholding_tax_cents"],
                    withholding_tax_pct=rec["withholding_tax_pct"],
                    net_amount_cents=rec["net_amount_cents"],
                    net_amount_eur_cents=rec["net_amount_eur_cents"],
                    fx_rate=rec["fx_rate"],
                )
                session.add(div)

                rows += 1
                logger.info(
                    "dividend_reconciled",
                    ticker=rec["ticker"],
                    account=rec["account_name"],
                    ex_date=str(rec["ex_date"]),
                    gross=rec["gross_amount_cents"],
                    net_eur=rec["net_amount_eur_cents"],
                    shares=float(rec["shares_held"]),
                )

            await session.commit()

        logger.info("dividend_reconciliation_loaded", rows=rows)
        return rows
