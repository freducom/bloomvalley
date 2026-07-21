# F24: Period Performance

**Status: Implemented — 2026-07-21**
**Created: 2026-07-21**

A period-scoped P&L view that breaks the portfolio's return into five buckets — realized gains, realized losses, dividends, unrealized gains, unrealized losses — over a user-picked date range. Answers "how did I do in [period]?" without conflating cash injections/withdrawals with actual investment returns.

---

## 1. Bucket definitions

| Bucket | Source | Sign rule |
|---|---|---|
| **Realized gains** | Sum of `tax_lots.realized_pnl_cents` for lots where `close_date` in period and `realized_pnl > 0`. Already EUR-cents. | ≥ 0 |
| **Realized losses** | Same but `realized_pnl < 0`. | ≤ 0 |
| **Dividends** | Sum of `dividends.net_amount_eur_cents` where `pay_date` in period. Post-withholding. | ≥ 0 |
| **Unrealized gains** | Per-security period-attributed price change, positive rows summed. | ≥ 0 |
| **Unrealized losses** | Same, negative rows summed. | ≤ 0 |
| **Net** | Sum of all five. | any |

All values in EUR cents.

## 2. Unrealized period-attribution math

The unrealized bucket counts **only shares still held at period end**. A position that was fully closed during the period contributes exactly zero to this bucket — its entire P&L is captured by the realized bucket (and dividends). This avoids double-counting closed round-trips.

For each security still held at period end, split the still-held shares into two cohorts and sum:

```
shares_kept_from_before   = min(shares_start, shares_end)   ← held throughout the period
shares_new_still_held     = max(0, shares_end − shares_start) ← bought during period, not yet sold

unrealized_change  =
     shares_kept_from_before × (price_end − price_start)         (EUR per share)
   + shares_new_still_held  × (price_end − avg_period_buy_price) (EUR per share)
```

Where:
- `shares_end` = position at period end (from transaction walk).
- `shares_start` = position at period start (net txns dated before `fromDate`).
- `price_start` / `price_end` = last daily close on or before period-start / period-end, converted to EUR at that date's FX rate.
- `avg_period_buy_price` = total EUR paid for period buys ÷ total shares bought during the period. Approximates FIFO/specific-ID for the "still-held bought-in-period" cohort.

**Sign for the gain/loss split**: bucket by whether `unrealized_change` for the security is positive (unrealized gains) or negative (unrealized losses). Fully-closed positions have `shares_end = 0` → `unrealized_change = 0` → no contribution.

**Why not `V_end − V_start − flows`?** That formula sums to the total portfolio period return, but for positions bought and sold entirely inside the period it collapses `V_end = V_start = 0` and reports `-(buys − sells) = realized_pnl` in the unrealized bucket, double-counting the realized gain. Restricting the bucket to still-held shares removes the double-count at the cost of not summing perfectly to portfolio-level return (the difference is pre-period accrual on shares sold during the period).

## 3. Currency

All aggregates are EUR. FX-conversion helpers already exist in `backend/app/services/tax_lots.py`:
- `_lookup_fx_table_rate(session, currency, on_date)` — quote-per-EUR rate.
- `_to_eur_cents(cents, currency, txn_fx_rate, table_rate)` — cents in native → cents in EUR.

Realized P&L and dividends are stored pre-normalized in EUR cents, so no conversion is needed for those buckets. Unrealized computation converts spot prices and transaction cash-flows to EUR using FxRate on the relevant date.

## 4. Return %

Each per-security row includes a period return computed server-side:

```
baseline_eur       = |value_at_period_start_eur| + eur_spent_on_buys_during_period
return_pct         = net_cents / baseline_eur   (or null if baseline_eur == 0)
```

Rationale:
- **Uses `|value_start|` (absolute)** so short positions are treated as capital-at-risk with the same sign as longs.
- **Adds gross buys in period** — captures capital deployed inside the window even when the position was opened during the period.
- **Does not subtract sells** — sells return capital together with realized P&L, which the numerator already reflects. Subtracting them would double-count.
- **Null when `baseline_eur == 0`**: legitimate "no capital deployed" case (no shares at start, no in-period buys — e.g. a dividend-only row from a transferred-in position with missing price history).

This deliberately isn't a true TWR/MWR — those would require timestamped daily flows. Capital-at-risk baseline is a stable, defensible denominator that behaves correctly for round-trips, fresh purchases, and mixed positions.

## 5. API

### `GET /api/v1/performance`

Query:
- `fromDate` (ISO date, required)
- `toDate` (ISO date, required)

Response:

```json
{
  "data": {
    "period": {"from": "2026-01-01", "to": "2026-07-21"},
    "currency": "EUR",
    "totals": {
      "realizedGainCents": 12345,
      "realizedLossCents": -6789,
      "dividendCents": 4321,
      "unrealizedGainCents": 234567,
      "unrealizedLossCents": -12345,
      "netCents": 232099
    },
    "bySecurity": [
      {
        "securityId": 10,
        "ticker": "AAPL",
        "name": "Apple Inc.",
        "assetClass": "stock",
        "sector": "Information Technology",
        "realizedCents": 0,
        "dividendCents": 1234,
        "unrealizedChangeCents": 45678,
        "netCents": 46912,
        "sharesEnd": "12.0",
        "sharesStart": "12.0",
        "priceStartCents": 18500,
        "priceEndCents": 22300,
        "valueEndEurCents": 240000,
        "valueStartEurCents": 195000,
        "costOfBuysInPeriodEurCents": 0,
        "baselineEurCents": 195000,
        "returnPct": 0.2406
      }
    ]
  },
  "meta": {"timestamp": "...", "fromDate": "...", "toDate": "..."}
}
```

Rows in `bySecurity` include every security that contributed to any bucket in the period (had a closed lot, a paid dividend, or non-zero unrealized change). Sorted by `abs(netCents)` desc so the biggest movers surface first.

## 6. Frontend

Route: `/performance`. Sidebar link under **Portfolio** labeled "Performance" (ChartLine icon).

- **Period picker** at top: MTD / YTD (default) / 1M / 3M / 1Y / All-time / Custom (date-range inputs). Reusable component `PeriodPicker` exported for reuse.
- **Six headline cards** in one row: Realized gains, Realized losses, Dividends, Unrealized gains, Unrealized losses, Net.
- **Per-security table**: ticker, name, realized, dividends, unrealized change, net, sortable, sticky header. Rows link to security detail page.
- **InfoTip** tooltips on each bucket (what's counted, when it moves buckets) and on the unrealized math.
- Empty-state: if all buckets are zero for the period, show "No P&L activity in this period".

Additionally, a compact **5-card strip** on the portfolio dashboard (`/portfolio`) shows YTD numbers with a link to `/performance`. Uses the same endpoint, hard-coded YTD range.

## 7. Non-goals (deferred)

- Per-account breakdown (currently aggregated across all accounts).
- Withholding-tax breakdown per country (already visible on the tax page).
- Cumulative equity curve chart.
- Currency-of-purchase view (values are always presented in EUR).
- Excluded transaction types: fees, interest, deposits, withdrawals — these are cash-management flows, not investment P&L.
