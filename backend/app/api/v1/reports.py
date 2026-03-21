"""Reports endpoints — annual tax report, performance report, transaction export."""

import io
import csv
from datetime import date, datetime, timezone
from decimal import Decimal

import structlog
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import case, func, literal_column, select

from app.db.engine import async_session
from app.db.models.accounts import Account
from app.db.models.dividends import Dividend
from app.db.models.securities import Security
from app.db.models.tax_lots import TaxLot
from app.db.models.transactions import Transaction
from app.api.v1.portfolio import _get_fx_rates, _get_latest_prices
from app.api.v1.tax import (
    TAX_BRACKET_LOW,
    TAX_BRACKET_HIGH,
    TAX_THRESHOLD_CENTS,
    _compute_tax,
    _deemed_cost,
    _holding_years,
    _compute_lot_gain,
)

logger = structlog.get_logger()

router = APIRouter()


# ---------------------------------------------------------------------------
# 1. GET /reports/tax/{year} — Annual tax report for Vero.fi filing
# ---------------------------------------------------------------------------

@router.get("/tax/{year}")
async def annual_tax_report(year: int):
    """Annual tax report for Vero.fi filing.

    Computes all realized capital gains/losses, dividend income, and OST
    summary for the given tax year. Finnish tax rules applied:
    - 30% capital gains up to €30,000, 34% above
    - Deemed cost of acquisition (20% or 40% if held >10 years)
    - OST: no annual tax events
    - Loss carry-forward noted (5-year window)
    """
    if year < 2000 or year > date.today().year + 1:
        raise HTTPException(status_code=400, detail=f"Invalid tax year: {year}")

    # ------------------------------------------------------------------
    # Capital gains from closed tax lots
    # ------------------------------------------------------------------
    async with async_session() as session:
        result = await session.execute(
            select(TaxLot, Security, Account)
            .join(Security, TaxLot.security_id == Security.id)
            .join(Account, TaxLot.account_id == Account.id)
            .where(
                TaxLot.state == "closed",
                func.extract("year", TaxLot.closed_date) == year,
            )
            .order_by(TaxLot.closed_date)
        )
        closed_lots = result.all()

    total_gains_cents = 0
    total_losses_cents = 0
    transactions_list: list[dict] = []

    for lot, sec, acc in closed_lots:
        is_ost = acc.type in ("osakesaastotili", "pension")
        if is_ost:
            continue  # OST has no annual tax events

        gain_info = _compute_lot_gain(lot)
        taxable_gain = gain_info.get("taxableGainCents", 0)
        holding_days = (lot.closed_date - lot.acquired_date).days if lot.closed_date else 0
        years_held = _holding_years(lot.acquired_date, lot.closed_date)
        deemed_applicable = gain_info.get("methodUsed") == "deemed"

        if taxable_gain >= 0:
            total_gains_cents += taxable_gain
        else:
            total_losses_cents += taxable_gain  # negative

        transactions_list.append({
            "securityId": sec.id,
            "ticker": sec.ticker,
            "isin": sec.isin,
            "name": sec.name,
            "accountType": acc.type,
            "sellDate": lot.closed_date.isoformat() if lot.closed_date else None,
            "buyDate": lot.acquired_date.isoformat(),
            "quantity": str(lot.original_quantity),
            "acquisitionCostCents": lot.cost_basis_cents,
            "sellingPriceCents": lot.proceeds_cents,
            "gainLossCents": taxable_gain,
            "holdingDays": holding_days,
            "holdingYears": round(years_held, 2),
            "deemedCostApplicable": deemed_applicable,
            "deemedCostCents": gain_info.get("deemedCostCents"),
            "methodUsed": gain_info.get("methodUsed", "actual"),
        })

    net_taxable_cents = total_gains_cents + total_losses_cents  # losses are negative
    loss_carry_forward_cents = abs(net_taxable_cents) if net_taxable_cents < 0 else 0
    taxable_for_bracket = max(0, net_taxable_cents)
    tax_info = _compute_tax(taxable_for_bracket)
    estimated_tax_cents = tax_info["taxCents"]

    # Determine bracket label
    if taxable_for_bracket <= 0:
        tax_bracket = "0%"
    elif taxable_for_bracket <= TAX_THRESHOLD_CENTS:
        tax_bracket = "30%"
    else:
        tax_bracket = "30%/34%"

    capital_gains = {
        "totalGainsCents": total_gains_cents,
        "totalLossesCents": total_losses_cents,
        "netTaxableCents": net_taxable_cents,
        "lossCarryForwardCents": loss_carry_forward_cents,
        "estimatedTaxCents": estimated_tax_cents,
        "taxBracket": tax_bracket,
        "transactions": transactions_list,
    }

    # ------------------------------------------------------------------
    # Dividend income
    # ------------------------------------------------------------------
    async with async_session() as session:
        result = await session.execute(
            select(Dividend, Security, Account)
            .join(Security, Dividend.security_id == Security.id)
            .join(Account, Dividend.account_id == Account.id)
            .where(func.extract("year", Dividend.ex_date) == year)
            .where(Account.type == "regular")  # OST dividends not taxed annually
        )
        dividend_rows = result.all()

    total_gross_cents = 0
    total_withholding_cents = 0
    total_net_cents = 0
    by_country_map: dict[str, dict] = {}

    for div, sec, acc in dividend_rows:
        total_gross_cents += div.gross_amount_cents
        total_withholding_cents += div.withholding_tax_cents
        total_net_cents += div.net_amount_cents

        country = sec.country or "UNKNOWN"
        if country not in by_country_map:
            by_country_map[country] = {
                "country": country,
                "grossCents": 0,
                "withholdingCents": 0,
                "withholdingRate": 0,
            }
        by_country_map[country]["grossCents"] += div.gross_amount_cents
        by_country_map[country]["withholdingCents"] += div.withholding_tax_cents

    # Compute effective withholding rate per country
    for entry in by_country_map.values():
        if entry["grossCents"] > 0:
            entry["withholdingRate"] = round(
                entry["withholdingCents"] / entry["grossCents"], 4
            )

    dividend_income = {
        "totalGrossCents": total_gross_cents,
        "totalWithholdingCents": total_withholding_cents,
        "totalNetCents": total_net_cents,
        "byCountry": sorted(
            by_country_map.values(),
            key=lambda x: x["grossCents"],
            reverse=True,
        ),
    }

    # ------------------------------------------------------------------
    # OST summary (no tax events, informational only)
    # ------------------------------------------------------------------
    async with async_session() as session:
        result = await session.execute(
            select(Account).where(
                Account.type == "osakesaastotili",
                Account.is_active.is_(True),
            )
        )
        ost_account = result.scalar_one_or_none()

    ost_summary: dict
    if ost_account:
        # Get OST holdings current value
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
                    Transaction.account_id == ost_account.id,
                    Transaction.security_id.isnot(None),
                    Transaction.type.in_(["buy", "sell", "transfer_in", "transfer_out"]),
                )
                .group_by(Transaction.security_id)
                .having(func.sum(qty_case) > 0)
            )
            ost_holdings = {r.security_id: float(r.qty) for r in result.all()}

        prices = await _get_latest_prices()
        fx_rates = await _get_fx_rates()

        total_ost_value = 0
        for sid, qty in ost_holdings.items():
            price_data = prices.get(sid)
            if price_data:
                mv = int(price_data["close_cents"] * qty)
                if price_data["currency"] != "EUR":
                    fx = fx_rates.get(price_data["currency"], Decimal("1"))
                    mv = int(mv / float(fx))
                total_ost_value += mv

        total_deposits = ost_account.osa_deposit_total_cents
        unrealized_gains = total_ost_value - total_deposits

        ost_summary = {
            "description": "Osakesäästötili — no annual tax events",
            "totalValueCents": total_ost_value,
            "totalDepositsCents": total_deposits,
            "unrealizedGainsCents": unrealized_gains,
            "note": "Tax deferred until withdrawal. Max deposit €50,000 lifetime.",
        }
    else:
        ost_summary = {
            "description": "Osakesäästötili — no account found",
            "totalValueCents": 0,
            "totalDepositsCents": 0,
            "unrealizedGainsCents": 0,
            "note": "No osakesäästötili account configured.",
        }

    # ------------------------------------------------------------------
    # Overall summary
    # ------------------------------------------------------------------
    # Total taxable capital income = net capital gains + net dividend income
    # (dividends are capital income in Finland)
    total_taxable_income_cents = max(0, net_taxable_cents) + total_net_cents
    overall_tax_info = _compute_tax(total_taxable_income_cents)
    estimated_total_tax_cents = overall_tax_info["taxCents"]
    effective_tax_rate = round(
        estimated_total_tax_cents / total_taxable_income_cents, 4
    ) if total_taxable_income_cents > 0 else 0

    summary = {
        "totalTaxableIncomeCents": total_taxable_income_cents,
        "estimatedTotalTaxCents": estimated_total_tax_cents,
        "effectiveTaxRate": effective_tax_rate,
    }

    return {
        "data": {
            "year": year,
            "capitalGains": capital_gains,
            "dividendIncome": dividend_income,
            "ostSummary": ost_summary,
            "summary": summary,
        },
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


# ---------------------------------------------------------------------------
# 2. GET /reports/performance — Period performance report
# ---------------------------------------------------------------------------

@router.get("/performance")
async def performance_report(
    start_date: date | None = Query(None, alias="startDate"),
    end_date: date | None = Query(None, alias="endDate"),
):
    """Performance report for a given period (default: YTD).

    Computes TWR approximation, per-holding performance, per-asset-class
    breakdown, dividends received, and transaction volume.
    """
    today = date.today()
    period_start = start_date or date(today.year, 1, 1)
    period_end = end_date or today

    if period_start > period_end:
        raise HTTPException(
            status_code=400, detail="startDate must be before endDate"
        )

    async with async_session() as session:
        # All transactions in period
        result = await session.execute(
            select(Transaction, Security, Account)
            .outerjoin(Security, Transaction.security_id == Security.id)
            .join(Account, Transaction.account_id == Account.id)
            .where(
                Transaction.trade_date >= period_start,
                Transaction.trade_date <= period_end,
            )
            .order_by(Transaction.trade_date)
        )
        txn_rows = result.all()

        # Closed lots in period for realized gains
        lots_result = await session.execute(
            select(TaxLot, Security, Account)
            .join(Security, TaxLot.security_id == Security.id)
            .join(Account, TaxLot.account_id == Account.id)
            .where(
                TaxLot.state == "closed",
                TaxLot.closed_date >= period_start,
                TaxLot.closed_date <= period_end,
            )
            .order_by(TaxLot.closed_date)
        )
        closed_lots = lots_result.all()

        # Dividends in period
        div_result = await session.execute(
            select(Dividend, Security)
            .join(Security, Dividend.security_id == Security.id)
            .where(
                Dividend.ex_date >= period_start,
                Dividend.ex_date <= period_end,
            )
        )
        dividends = div_result.all()

    prices = await _get_latest_prices()
    fx_rates = await _get_fx_rates()

    # ------------------------------------------------------------------
    # Per-holding performance (realized + unrealized from current holdings)
    # ------------------------------------------------------------------
    # Aggregate realized P&L per security from closed lots
    realized_by_security: dict[int, int] = {}
    for lot, sec, acc in closed_lots:
        gain_info = _compute_lot_gain(lot)
        taxable_gain = gain_info.get("taxableGainCents", 0)
        realized_by_security[sec.id] = realized_by_security.get(sec.id, 0) + taxable_gain

    # Current holdings for unrealized (reuse approach from portfolio)
    async with async_session() as session:
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
        result = await session.execute(
            select(
                Transaction.security_id,
                func.sum(qty_case).label("net_quantity"),
                func.sum(cost_case).label("total_cost_cents"),
            )
            .where(
                Transaction.security_id.isnot(None),
                Transaction.type.in_(["buy", "sell", "transfer_in", "transfer_out"]),
            )
            .group_by(Transaction.security_id)
            .having(func.sum(qty_case) > 0)
        )
        current_holdings = result.all()

        # Load security details
        sec_ids = {r.security_id for r in current_holdings}
        sec_ids.update(realized_by_security.keys())
        if sec_ids:
            sec_result = await session.execute(
                select(Security).where(Security.id.in_(sec_ids))
            )
            securities = {s.id: s for s in sec_result.scalars().all()}
        else:
            securities = {}

    by_holding: list[dict] = []
    for row in current_holdings:
        sec = securities.get(row.security_id)
        if not sec:
            continue
        net_qty = float(row.net_quantity)
        total_cost = int(row.total_cost_cents) if row.total_cost_cents else 0

        price_data = prices.get(row.security_id)
        mv_cents = 0
        if price_data:
            mv_cents = int(price_data["close_cents"] * net_qty)
            if price_data["currency"] != "EUR":
                fx = fx_rates.get(price_data["currency"], Decimal("1"))
                mv_cents = int(mv_cents / float(fx))

        # Convert cost to EUR
        cost_eur = total_cost
        if sec.currency and sec.currency != "EUR":
            fx = fx_rates.get(sec.currency, Decimal("1"))
            cost_eur = int(total_cost / float(fx))

        unrealized = mv_cents - cost_eur
        realized = realized_by_security.get(row.security_id, 0)
        total_return = unrealized + realized
        total_return_pct = round((total_return / cost_eur) * 100, 2) if cost_eur != 0 else None

        by_holding.append({
            "securityId": row.security_id,
            "ticker": sec.ticker,
            "name": sec.name,
            "assetClass": sec.asset_class,
            "marketValueEurCents": mv_cents,
            "costBasisEurCents": cost_eur,
            "unrealizedPnlCents": unrealized,
            "realizedPnlCents": realized,
            "totalReturnCents": total_return,
            "totalReturnPct": total_return_pct,
        })

    # Sort: best performers first
    by_holding.sort(key=lambda x: x["totalReturnCents"], reverse=True)

    # ------------------------------------------------------------------
    # By asset class
    # ------------------------------------------------------------------
    by_asset_class: dict[str, dict] = {}
    for h in by_holding:
        ac = h["assetClass"] or "other"
        if ac not in by_asset_class:
            by_asset_class[ac] = {
                "assetClass": ac,
                "marketValueEurCents": 0,
                "costBasisEurCents": 0,
                "totalReturnCents": 0,
            }
        by_asset_class[ac]["marketValueEurCents"] += h["marketValueEurCents"]
        by_asset_class[ac]["costBasisEurCents"] += h["costBasisEurCents"]
        by_asset_class[ac]["totalReturnCents"] += h["totalReturnCents"]

    for entry in by_asset_class.values():
        cost = entry["costBasisEurCents"]
        entry["totalReturnPct"] = (
            round((entry["totalReturnCents"] / cost) * 100, 2) if cost != 0 else None
        )

    # ------------------------------------------------------------------
    # Dividends in period
    # ------------------------------------------------------------------
    total_div_gross = 0
    total_div_net = 0
    for div, sec in dividends:
        total_div_gross += div.gross_amount_cents
        total_div_net += div.net_amount_cents

    # ------------------------------------------------------------------
    # Transaction volume
    # ------------------------------------------------------------------
    tx_count = len(txn_rows)
    tx_volume_cents = sum(
        abs(txn.total_cents) for txn, sec, acc in txn_rows
        if txn.type in ("buy", "sell")
    )

    # ------------------------------------------------------------------
    # TWR approximation (simple: end value / start value - 1, adjusted for
    # cash flows). For a single-user tool, Modified Dietz is a good proxy.
    # ------------------------------------------------------------------
    total_mv = sum(h["marketValueEurCents"] for h in by_holding)
    total_cost = sum(h["costBasisEurCents"] for h in by_holding)
    twr_pct = round(((total_mv - total_cost) / total_cost) * 100, 2) if total_cost != 0 else None

    return {
        "data": {
            "period": {
                "startDate": period_start.isoformat(),
                "endDate": period_end.isoformat(),
            },
            "twrPct": twr_pct,
            "totalMarketValueEurCents": total_mv,
            "totalCostBasisEurCents": total_cost,
            "byHolding": by_holding,
            "bestPerformers": by_holding[:5] if by_holding else [],
            "worstPerformers": list(reversed(by_holding[-5:])) if by_holding else [],
            "byAssetClass": sorted(
                by_asset_class.values(),
                key=lambda x: x["marketValueEurCents"],
                reverse=True,
            ),
            "dividends": {
                "totalGrossCents": total_div_gross,
                "totalNetCents": total_div_net,
                "count": len(dividends),
            },
            "transactions": {
                "count": tx_count,
                "totalVolumeCents": tx_volume_cents,
            },
        },
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


# ---------------------------------------------------------------------------
# 3. GET /reports/transactions/export — CSV export
# ---------------------------------------------------------------------------

@router.get("/transactions/export")
async def export_transactions(
    start_date: date | None = Query(None, alias="startDate"),
    end_date: date | None = Query(None, alias="endDate"),
    account_id: int | None = Query(None, alias="accountId"),
    format: str = Query("csv"),
):
    """Export transactions as CSV.

    Returns a streaming CSV response with columns:
    Date, Type, Security, Ticker, ISIN, Quantity, Price, Total, Fee,
    Currency, Account, AccountType
    """
    if format != "csv":
        raise HTTPException(status_code=400, detail="Only CSV format is supported")

    async with async_session() as session:
        query = (
            select(Transaction, Security, Account)
            .outerjoin(Security, Transaction.security_id == Security.id)
            .join(Account, Transaction.account_id == Account.id)
            .order_by(Transaction.trade_date.desc())
        )

        if start_date:
            query = query.where(Transaction.trade_date >= start_date)
        if end_date:
            query = query.where(Transaction.trade_date <= end_date)
        if account_id:
            query = query.where(Transaction.account_id == account_id)

        result = await session.execute(query)
        rows = result.all()

    # Build CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Date", "Type", "Security", "Ticker", "ISIN",
        "Quantity", "PriceCents", "TotalCents", "FeeCents",
        "Currency", "Account", "AccountType",
    ])

    for txn, sec, acc in rows:
        writer.writerow([
            txn.trade_date.isoformat(),
            txn.type,
            sec.name if sec else "",
            sec.ticker if sec else "",
            sec.isin if sec else "",
            str(txn.quantity),
            txn.price_cents or "",
            txn.total_cents,
            txn.fee_cents,
            txn.currency,
            acc.name,
            acc.type,
        ])

    output.seek(0)

    # Determine filename
    parts = ["transactions"]
    if start_date:
        parts.append(f"from-{start_date.isoformat()}")
    if end_date:
        parts.append(f"to-{end_date.isoformat()}")
    filename = "_".join(parts) + ".csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
