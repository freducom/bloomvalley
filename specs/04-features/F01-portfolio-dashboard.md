# F01 — Portfolio Dashboard

**Status: DRAFT**

The home screen of the Bloomvalley terminal. It answers the central investor question: "How is my portfolio doing right now, and am I on track?" The dashboard aggregates all accounts into a single view showing total portfolio value as a hero metric, a holdings table with per-position detail, current-versus-target allocation with a glidepath chart, and P&L summaries broken down by account type. Four sub-tabs — Overview, Holdings, Performance, and Accounts — let the user drill from high-level summary to granular position data without leaving the page.

## Dependencies

- Specs: [data-model](../01-system/data-model.md), [api-overview](../01-system/api-overview.md), [architecture](../01-system/architecture.md), [spec-conventions](../00-meta/spec-conventions.md), [portfolio-math](../03-calculations/portfolio-math.md), [glidepath](../03-calculations/glidepath.md), [design-system](../05-ui/design-system.md)
- Data: Yahoo Finance daily prices pipeline, ECB FX rates pipeline, holdings snapshot nightly rebuild
- API: `GET /portfolio/summary`, `GET /portfolio/holdings`, `GET /portfolio/allocation`, `GET /portfolio/glidepath`, `GET /portfolio/performance`, `GET /prices/current`, `GET /accounts`

## Data Requirements

### Tables Read

| Table | Purpose |
|-------|---------|
| `holdings_snapshot` | Current positions with market values, cost basis, weights |
| `accounts` | Account names, types, osakesaastotili deposit totals |
| `securities` | Security names, tickers, asset classes, sectors |
| `prices` | Latest close prices for market value calculation |
| `fx_rates` | EUR conversion for multi-currency positions |
| `tax_lots` | Open lots for unrealized P&L; closed lots for realized P&L |
| `transactions` | Realized P&L aggregation, dividend income |
| `dividends` | Dividend income totals for P&L summary |

### Tables Written

None. The dashboard is read-only; `holdings_snapshot` is rebuilt by the nightly pipeline, not by this feature.

### Calculations Invoked

- [portfolio-math](../03-calculations/portfolio-math.md): total portfolio value, per-position market value, unrealized/realized P&L, weight percentages, day change, TWR, MWWR (XIRR)
- [glidepath](../03-calculations/glidepath.md): target allocation at current age, drift from target, glidepath curve projection

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/portfolio/summary` | Total value, total unrealized P&L, total realized P&L YTD, allocation vs target, drift percentage |
| GET | `/portfolio/holdings` | All current positions: security detail, quantity, avg cost, current price, market value, unrealized P&L, weight, day change. Supports `?accountId`, `?assetClass`, `?sortBy`, `?sortOrder` |
| GET | `/portfolio/allocation` | Current allocation by asset class/sector vs glidepath target. Returns both percentage and absolute values |
| GET | `/portfolio/glidepath` | Historical and projected glidepath: actual allocation by age vs target schedule from AGENTS.md |
| GET | `/portfolio/performance` | TWR and MWWR over configurable periods (1D, 1W, 1M, 3M, 6M, YTD, 1Y, 3Y, 5Y, ALL) |
| GET | `/accounts` | List all accounts with summary (total value, number of positions) |
| GET | `/prices/current` | Current prices for all held securities (used for real-time value refresh) |

See [api-overview](../01-system/api-overview.md) for full request/response schemas.

## UI Views

### Sub-tab: Overview (default)

The landing view. Dense summary answering "how am I doing?"

**Top row — Hero metrics (4 MetricCard components, full width):**

| Metric | Format | Source |
|--------|--------|--------|
| Total Portfolio Value | `€1,234,567.89` in `text-2xl font-bold` | `/portfolio/summary` |
| Day Change | `+€2,345.67 (+0.19%)` with gain/loss coloring | `/portfolio/summary` |
| Unrealized P&L (Total) | `+€123,456.78 (+12.34%)` with gain/loss coloring | `/portfolio/summary` |
| Realized P&L (YTD) | `€45,678.90` with gain/loss coloring | `/portfolio/summary` |

**Middle row — Two-column layout:**

- Left column (60%): **Allocation ring chart** — nested donut showing current allocation (inner ring) vs target allocation (outer ring) by asset class. Uses `asset-*` colors from design system. Below the chart: a small table listing each asset class with current %, target %, and drift (colored `warning` if |drift| > 5%).
- Right column (40%): **Glidepath chart** — area chart showing equity/fixed-income/crypto/cash allocation from age 45 to 60. A vertical "now" line marks current age. Actual allocation overlaid as dots. Uses Recharts AreaChart.

**Bottom row — Account summary cards:**

One card per account (horizontal scroll if many). Each card shows: account name, type badge (`regular`, `OST`, `crypto`, `pension`), total value, number of positions, and a mini sparkline of value over the last 30 days.

### Sub-tab: Holdings

Full-width holdings table (TanStack Table with virtual scrolling).

**Columns:**

| Column | Type | Sortable | Default Sort |
|--------|------|----------|--------------|
| Security (ticker + name) | text + subtitle | Yes | — |
| Account | badge | Yes | — |
| Asset Class | badge | Yes | — |
| Quantity | number | Yes | — |
| Avg Cost | currency | Yes | — |
| Current Price | currency | Yes | — |
| Market Value | currency | Yes | desc (default) |
| Unrealized P&L | currency + % | Yes | — |
| Weight | percentage | Yes | — |
| Day Change | currency + % | Yes | — |

**Interactions:**
- Click column header to sort (asc/desc toggle)
- Filter bar above table: account dropdown, asset class multi-select, text search on security name/ticker
- Click a row to expand an inline detail panel showing: tax lots for this position, sector, exchange, last dividend, 30-day price sparkline
- Right-click context menu: "View in Research", "Add to Watchlist", "View Chart"

### Sub-tab: Performance

**Top section:** Period selector buttons (1D, 1W, 1M, 3M, 6M, YTD, 1Y, 3Y, 5Y, ALL).

**Main chart:** Portfolio value line chart over the selected period. TWR and MWWR displayed as separate lines (toggleable). Benchmark overlay (e.g., MSCI World) if benchmark is configured.

**Below chart:** Performance attribution table — return contribution by asset class and by individual holding for the selected period. Columns: security, weight (avg), return, contribution.

### Sub-tab: Accounts

**One panel per account**, stacked vertically. Each panel contains:
- Account header: name, type, institution, currency
- For osakesaastotili: deposit progress bar (`osa_deposit_total_cents / 5,000,000`) with remaining capacity
- Mini holdings table scoped to that account (same columns as Holdings tab but without the Account column)
- Account-level totals: total value, unrealized P&L, realized P&L YTD

**Components used:** MetricCard, DataTable (TanStack Table), ChartCard (Recharts), AllocationRing, StatusBadge, SparklineChart, ProgressBar (for OST deposits), TabBar

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `1` | Switch to Overview sub-tab |
| `2` | Switch to Holdings sub-tab |
| `3` | Switch to Performance sub-tab |
| `4` | Switch to Accounts sub-tab |
| `/` | Focus the holdings search/filter bar |
| `r` | Refresh data (re-fetch all endpoints) |
| `Enter` (on selected row) | Expand/collapse row detail |

## Business Rules

1. **Portfolio value calculation**: Sum of `market_value_eur_cents` across all open positions in all active accounts. Cash balances are excluded until the `cash_balances` table is implemented (see data model open question #2).

2. **Day change**: Computed as `current_price - previous_close` for each position, converted to EUR, summed across portfolio. Previous close is the most recent `prices.close_cents` before today.

3. **Weight calculation**: `position_market_value_eur / total_portfolio_value * 100`. Recalculated on every price update.

4. **Average cost**: Weighted average cost basis across all open tax lots for the position: `SUM(cost_basis_cents) / SUM(remaining_quantity)`.

5. **Realized P&L YTD**: Sum of `tax_lots.realized_pnl_cents` where `closed_date` is within the current calendar year, plus net dividend income from `dividends` for the year.

6. **Allocation vs target**: Current allocation percentages compared against the glidepath schedule for the user's current age (45). Drift = |current% - target%| per asset class.

7. **Multi-currency aggregation**: All values converted to EUR using the latest `fx_rates` entry for each currency pair. If an FX rate is missing, the position is displayed with a warning badge and excluded from aggregated totals (see api-overview edge case #3).

8. **Osakesaastotili display**: The OST deposit progress bar shows lifetime deposits vs the 50,000 EUR cap. Internal trades within OST are not flagged as taxable events in the P&L summary.

## Edge Cases

1. **Empty portfolio (no transactions)**: Show the dashboard shell with zero values in all hero metrics. Holdings table shows an empty state message: "No holdings yet. Record your first transaction to get started." Allocation chart shows an empty ring. Glidepath chart shows only the target line.

2. **Stale price data**: If `meta.stale = true` on the `/prices/current` response, display a yellow staleness badge on the Total Portfolio Value metric card showing "Prices as of {last_update_time}". Individual holdings with stale prices show a clock icon next to their current price.

3. **Missing FX rate**: Positions in currencies without a current FX rate display market value as `—` (em dash) with a warning tooltip: "FX rate unavailable for {currency}." The position is excluded from portfolio totals and weight calculations. A warning banner appears at the top of the page if any position is excluded.

4. **Single account**: If the user has only one account, the Accounts sub-tab still shows but with a single panel. No account filter appears in the Holdings tab.

5. **New position (bought today)**: Appears immediately in Holdings after the transaction is recorded. Day change may show as `—` if there is no previous close price. Average cost equals the purchase price.

6. **Price unavailable for a security**: `priceAvailable: false` in the API response. Market value shows `N/A`, unrealized P&L shows `—`, weight is omitted from the total. A badge "No price data" appears on the row.

7. **Large number of holdings (>100)**: Virtual scrolling on the Holdings table ensures smooth performance. The Overview tab only shows the top 10 holdings by weight in the account summary; full list available in Holdings tab.

8. **Crypto 24/7 prices**: Crypto positions always show a "live" day change since there is no market close. The "day" boundary is UTC midnight, matching the CoinGecko daily price stored in `prices`.

9. **Glidepath deviation > 10%**: If actual allocation deviates from target by more than 10% in any asset class, the glidepath chart highlights the gap in `warning` color and a MetricCard-level alert badge appears.

## Acceptance Criteria

1. The Overview sub-tab loads within 500ms and displays total portfolio value, day change, unrealized P&L, and realized P&L YTD as hero metrics.
2. The holdings table displays all open positions across all accounts with correct values for quantity, avg cost, current price, market value, unrealized P&L, weight, and day change.
3. The allocation ring chart shows current allocation by asset class alongside the target allocation from the glidepath schedule.
4. The glidepath chart renders the target allocation curve from age 45 to 60 with actual allocation overlaid.
5. All monetary values display in EUR with correct formatting per the design system (cents-to-display conversion, comma thousands separator, 2 decimal places).
6. Sorting works on all sortable columns in the holdings table, with ascending/descending toggle.
7. The account filter in Holdings correctly scopes the table to the selected account(s).
8. The Accounts sub-tab shows one panel per active account with account-scoped totals.
9. The osakesaastotili account panel shows a deposit progress bar with correct current/max values.
10. Stale data displays a staleness badge with the timestamp of the last successful price update.
11. Positions with missing FX rates or prices display appropriate warning indicators and are excluded from aggregated totals.
12. Keyboard shortcuts (1-4 for tabs, / for search, r for refresh) work correctly.
13. The Performance sub-tab shows TWR and MWWR for all configurable periods.
14. Day change for crypto positions uses UTC midnight as the day boundary.
15. An empty portfolio displays a meaningful empty state without errors.

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
