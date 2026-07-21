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

For a security with position at end of period, the period-attributed unrealized change is:

```
V_end   = shares_end   × price_end    (EUR-converted)
V_start = shares_start × price_start  (EUR-converted)
flows   = buy_cash_in_period − sell_cash_in_period   (EUR at txn date)

unrealized_change = V_end − V_start − flows
```

Where:
- `shares_end` = shares held at period end (from live holdings if period end = today, else back-computed).
- `shares_start` = `shares_end − net_shares_added_in_period` (buys and transfers-in minus sells and transfers-out during period).
- `price_start` = last daily close on or before period start; `price_end` = last daily close on or before period end.
- If a security was entered mid-period (shares_start = 0), `V_start = 0` — the unrealized change reflects only the movement since the first buy.
- If a security was fully sold mid-period (shares_end = 0), it contributes nothing to unrealized (its P&L is captured in the realized bucket).

**Sign for the gain/loss split**: bucket by whether `unrealized_change` for the security is positive or negative — i.e., what happened during the period, not what happened against original cost basis.

## 3. Currency

All aggregates are EUR. FX-conversion helpers already exist in `backend/app/services/tax_lots.py`:
- `_lookup_fx_table_rate(session, currency, on_date)` — quote-per-EUR rate.
- `_to_eur_cents(cents, currency, txn_fx_rate, table_rate)` — cents in native → cents in EUR.

Realized P&L and dividends are stored pre-normalized in EUR cents, so no conversion is needed for those buckets. Unrealized computation converts spot prices and transaction cash-flows to EUR using FxRate on the relevant date.

## 4. API

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
        "valueStartEurCents": 195000
      }
    ]
  },
  "meta": {"timestamp": "...", "fromDate": "...", "toDate": "..."}
}
```

Rows in `bySecurity` include every security that contributed to any bucket in the period (had a closed lot, a paid dividend, or non-zero unrealized change). Sorted by `abs(netCents)` desc so the biggest movers surface first.

## 5. Frontend

Route: `/performance`. Sidebar link under **Portfolio** labeled "Performance" (ChartLine icon).

- **Period picker** at top: MTD / YTD (default) / 1M / 3M / 1Y / All-time / Custom (date-range inputs). Reusable component `PeriodPicker` exported for reuse.
- **Six headline cards** in one row: Realized gains, Realized losses, Dividends, Unrealized gains, Unrealized losses, Net.
- **Per-security table**: ticker, name, realized, dividends, unrealized change, net, sortable, sticky header. Rows link to security detail page.
- **InfoTip** tooltips on each bucket (what's counted, when it moves buckets) and on the unrealized math.
- Empty-state: if all buckets are zero for the period, show "No P&L activity in this period".

Additionally, a compact **5-card strip** on the portfolio dashboard (`/portfolio`) shows YTD numbers with a link to `/performance`. Uses the same endpoint, hard-coded YTD range.

## 6. Non-goals (deferred)

- Per-account breakdown (currently aggregated across all accounts).
- Withholding-tax breakdown per country (already visible on the tax page).
- Cumulative equity curve chart.
- Currency-of-purchase view (values are always presented in EUR).
- Excluded transaction types: fees, interest, deposits, withdrawals — these are cash-management flows, not investment P&L.
