# F12 — Transaction Log & Reporting

Complete transaction history management and performance reporting module. Provides a full audit trail of all portfolio activity, performance analytics (TWR, MWWR, Brinson attribution), annual tax report generation for Vero.fi, and data export capabilities. This module serves as the system of record for all portfolio events and the primary reporting interface.

**Status: DRAFT**

## Dependencies

- [Data Model](../01-system/data-model.md) — `transactions` table, `tax_lots`, `holdings_snapshot`, `securities`, `accounts`, `dividends`
- [API Overview](../01-system/api-overview.md) — `/transactions`, `/reports` endpoint groups
- [Spec Conventions](../00-meta/spec-conventions.md) — monetary format (cents), date/time, naming rules
- [F05 — Tax Module] — tax lot tracking, Finnish tax rules, deemed cost of acquisition
- F01 — Portfolio Dashboard (portfolio valuation for performance calculation)

## Data Requirements

### Transaction Data

All transactions stored in the `transactions` table with the following types (from `transactions_type_enum`):

| Type | Description | Requires Security | Affects Tax Lots |
|------|-------------|-------------------|-----------------|
| `buy` | Purchase of a security | Yes | Creates new lot |
| `sell` | Sale of a security | Yes | Closes lot(s) |
| `dividend` | Dividend payment received | Yes | No |
| `transfer_in` | Securities transferred into an account | Yes | Creates new lot |
| `transfer_out` | Securities transferred out of an account | Yes | Closes lot(s) |
| `fee` | Account-level fee (not trade-specific) | Optional | No |
| `interest` | Interest received or paid | No | No |
| `corporate_action` | Result of a corporate action | Yes | Adjusts lots |
| `deposit` | Cash deposit into account | No | No |
| `withdrawal` | Cash withdrawal from account | No | No |

### Performance Calculation Data

- **Time-Weighted Return (TWR)**: requires daily portfolio valuations from `holdings_snapshot` and cash flow dates/amounts from `transactions`
- **Money-Weighted Return (MWWR/XIRR)**: requires all cash flows (deposits, withdrawals, buys, sells, dividends) with dates and amounts
- **Brinson Attribution**: requires asset class allocation at start and end of period, plus benchmark allocation and returns

### Tax Report Data

Finnish annual tax report (Vero.fi) requires:
- All realized capital gains and losses for the tax year
- Dividend income (gross, withholding tax, net) by security and country
- Deemed cost of acquisition calculations where applicable
- Osakesaastotili summary (deposits, current value, gains portion) — reported separately
- Carry-forward losses from prior years (if any)

## API Endpoints

### Transactions

| Method | Path | Description |
|--------|------|-------------|
| GET | `/transactions` | List transactions; supports pagination, filters: `accountId`, `securityId`, `type`, `fromDate`, `toDate`, `sortBy`, `sortOrder` |
| POST | `/transactions` | Create a new transaction |
| PUT | `/transactions/{id}` | Update a transaction (triggers tax lot recalculation) |
| DELETE | `/transactions/{id}` | Delete a transaction (cascades to tax lot recalculation) |
| GET | `/transactions/{id}` | Get a single transaction detail |

### Reports

| Method | Path | Description |
|--------|------|-------------|
| GET | `/reports/performance` | Performance metrics (TWR, MWWR) for configurable period and grouping |
| GET | `/reports/performance/attribution` | Brinson-style performance attribution |
| GET | `/reports/tax/{year}` | Annual tax report for Vero.fi |
| GET | `/reports/transactions/export` | Export transactions as CSV or Excel |
| GET | `/reports/performance/export` | Export performance report as CSV or Excel |
| GET | `/reports/tax/{year}/export` | Export tax report as PDF or structured CSV |

### Query Parameters

| Endpoint | Parameter | Type | Description |
|----------|-----------|------|-------------|
| `/reports/performance` | `fromDate` | date | Period start (default: account inception) |
| `/reports/performance` | `toDate` | date | Period end (default: today) |
| `/reports/performance` | `groupBy` | enum | `total`, `account`, `assetClass`, `security` |
| `/reports/performance` | `benchmark` | string | Benchmark ticker for comparison (e.g., `^STOXX50E`) |
| `/reports/performance/attribution` | `year` | integer | Year for attribution analysis |
| `/reports/transactions/export` | `format` | enum | `csv`, `xlsx` |
| `/reports/tax/{year}/export` | `format` | enum | `pdf`, `csv` |

### Request: `POST /transactions`

```json
{
  "accountId": 1,
  "securityId": 42,
  "type": "buy",
  "tradeDate": "2026-03-18",
  "settlementDate": "2026-03-20",
  "quantity": 10,
  "priceCents": 15234,
  "priceCurrency": "USD",
  "totalCents": 140570,
  "feeCents": 999,
  "feeCurrency": "EUR",
  "fxRate": 1.085000,
  "currency": "EUR",
  "notes": "Adding to AAPL position on dip",
  "externalRef": "NORDNET-2026031800123"
}
```

### Response: `GET /reports/performance`

```json
{
  "data": {
    "period": {
      "fromDate": "2025-01-01",
      "toDate": "2025-12-31"
    },
    "total": {
      "twr": 12.45,
      "mwwr": 11.82,
      "startValue": { "amount": 25000000, "currency": "EUR" },
      "endValue": { "amount": 28112500, "currency": "EUR" },
      "netCashFlows": { "amount": 1500000, "currency": "EUR" },
      "totalReturn": { "amount": 3112500, "currency": "EUR" },
      "dividendIncome": { "amount": 375000, "currency": "EUR" },
      "realizedGains": { "amount": 125000, "currency": "EUR" },
      "unrealizedGains": { "amount": 2612500, "currency": "EUR" }
    },
    "benchmark": {
      "ticker": "^STOXX50E",
      "name": "EURO STOXX 50",
      "twr": 9.87,
      "alpha": 2.58
    },
    "byAssetClass": [
      {
        "assetClass": "stock",
        "twr": 14.23,
        "mwwr": 13.65,
        "startWeight": 42.5,
        "endWeight": 44.1,
        "contribution": 6.05
      },
      {
        "assetClass": "etf",
        "twr": 11.87,
        "mwwr": 11.45,
        "startWeight": 35.0,
        "endWeight": 34.2,
        "contribution": 4.16
      }
    ]
  }
}
```

### Response: `GET /reports/tax/{year}`

```json
{
  "data": {
    "year": 2025,
    "capitalGains": {
      "totalRealizedGains": { "amount": 850000, "currency": "EUR" },
      "totalRealizedLosses": { "amount": -125000, "currency": "EUR" },
      "netCapitalGain": { "amount": 725000, "currency": "EUR" },
      "taxAt30Pct": { "amount": 217500, "currency": "EUR" },
      "taxAt34Pct": { "amount": 0, "currency": "EUR" },
      "totalEstimatedTax": { "amount": 217500, "currency": "EUR" },
      "deemedCostUsed": 2,
      "transactions": [
        {
          "tradeDate": "2025-04-10",
          "security": "AAPL",
          "type": "sell",
          "quantity": 15,
          "proceeds": { "amount": 228510, "currency": "EUR" },
          "actualCostBasis": { "amount": 175000, "currency": "EUR" },
          "deemedCost20Pct": { "amount": 45702, "currency": "EUR" },
          "deemedCost40Pct": null,
          "costBasisUsed": { "amount": 175000, "currency": "EUR" },
          "costMethod": "actual",
          "realizedGain": { "amount": 53510, "currency": "EUR" },
          "holdingPeriodDays": 892,
          "accountType": "regular"
        }
      ]
    },
    "dividendIncome": {
      "totalGross": { "amount": 425000, "currency": "EUR" },
      "totalWithholdingTax": { "amount": 63750, "currency": "EUR" },
      "totalNet": { "amount": 361250, "currency": "EUR" },
      "byCountry": [
        {
          "country": "US",
          "gross": { "amount": 280000, "currency": "EUR" },
          "withholdingRate": 15.0,
          "withholdingTax": { "amount": 42000, "currency": "EUR" },
          "net": { "amount": 238000, "currency": "EUR" }
        },
        {
          "country": "FI",
          "gross": { "amount": 145000, "currency": "EUR" },
          "withholdingRate": 0.0,
          "withholdingTax": { "amount": 0, "currency": "EUR" },
          "net": { "amount": 145000, "currency": "EUR" }
        }
      ]
    },
    "osakesaastotili": {
      "deposits": { "amount": 4500000, "currency": "EUR" },
      "currentValue": { "amount": 5250000, "currency": "EUR" },
      "gainsPortion": { "amount": 750000, "currency": "EUR" },
      "noWithdrawals": true
    },
    "lossCarryForward": {
      "fromPriorYears": { "amount": 0, "currency": "EUR" },
      "usedThisYear": { "amount": 0, "currency": "EUR" },
      "carryForwardToNextYear": { "amount": 0, "currency": "EUR" }
    }
  }
}
```

## UI Views

### Sub-tab: Transactions

- **Transaction table** (full-width, dense layout):
  - Columns: Date, Type (icon + label), Security (ticker + name), Account, Quantity, Price, Fees, Total, Notes
  - Type icons: green arrow up (buy), red arrow down (sell), dollar sign (dividend), transfer icons, etc.
  - Sortable by any column; default sort: date descending
  - Filterable: date range picker, account dropdown, security search, type multi-select
  - Pagination: 50 rows per page, showing "1-50 of 347"
- **Add transaction button** (top right): opens a transaction form modal
  - Form fields: account (dropdown), type (dropdown), security (search), trade date, settlement date, quantity, price, fees, FX rate (auto-filled from `fx_rates` if available), notes, external reference
  - Validation: all required fields per transaction type, positive quantities, non-negative fees
  - On submit: creates the transaction and triggers tax lot creation/adjustment
- **Edit/Delete**: row actions via icon buttons
  - Edit opens the same form pre-populated; on save, triggers tax lot recalculation for all lots affected by this transaction and all subsequent transactions for the same security/account
  - Delete requires confirmation dialog ("Deleting this transaction will recalculate all tax lots. Continue?")
- **Bulk import**: "Import CSV" button for batch transaction upload (future enhancement placeholder)

### Sub-tab: Performance

- **Period selector**: preset buttons (YTD, 1Y, 3Y, 5Y, All) and custom date range picker
- **Performance summary cards** (top row):
  - TWR (time-weighted return), MWWR (money-weighted return), Total Return (EUR), Dividend Income, Realized Gains, Unrealized Gains
  - Each with period value and annualized equivalent
  - See component: `MetricCard`
- **Performance chart** (Recharts area chart):
  - Portfolio value over time (line), with benchmark overlay (dashed line) if selected
  - Cash flows marked as vertical annotations on the timeline
  - Toggle between: cumulative return (%), absolute value (EUR)
- **Benchmark comparison**: dropdown to select benchmark (EURO STOXX 50, OMXH25, MSCI World, S&P 500)
  - Alpha displayed as a card: portfolio TWR minus benchmark TWR
- **Breakdown views** (toggle group):
  - By account: table showing TWR, MWWR, contribution per account
  - By asset class: table showing TWR, MWWR, contribution per asset class
  - By security: table showing TWR, MWWR, contribution per security (paginated for large portfolios)
- **Brinson attribution** (expandable section):
  - Table: Asset Class, Portfolio Weight, Benchmark Weight, Portfolio Return, Benchmark Return, Allocation Effect, Selection Effect, Interaction Effect, Total Effect
  - Bar chart showing attribution effects by asset class
  - Requires a benchmark to be selected

### Sub-tab: Tax Report

- **Year selector**: dropdown for available years (all years with transaction activity)
- **Capital gains summary**:
  - Total realized gains, total realized losses, net capital gain
  - Tax bracket breakdown: amount taxed at 30%, amount taxed at 34%
  - Total estimated tax
  - Number of transactions where deemed cost was more favorable
- **Realized transactions table**:
  - Columns: Date, Security, Quantity, Proceeds, Cost Basis (actual), Deemed Cost (20%/40%), Cost Method Used, Gain/Loss, Holding Period
  - "Cost Method Used" shows "actual" or "deemed 20%" or "deemed 40%" with a tooltip explaining the rule
  - Color: green for gains, red for losses
  - Sortable, filterable by security and gain/loss direction
- **Dividend income table**:
  - Grouped by country of origin
  - Columns: Security, Country, Gross Amount, Withholding Rate, Withholding Tax, Net Amount
  - Subtotals per country, grand total at bottom
- **Osakesaastotili summary card**:
  - Lifetime deposits, current market value, gains portion
  - Note: "No tax events during the year" (if no withdrawals)
  - If withdrawals occurred: taxable amount calculation shown
- **Loss carry-forward section**:
  - Prior year losses available, losses used this year, remaining carry-forward
  - Note: losses can be carried forward for 5 years in Finland

### Sub-tab: Export

- **Export options** (card-based layout):
  - **Transactions CSV/Excel**: export all transactions or filtered subset
    - Column selection checkboxes
    - Date range filter
    - Account filter
    - Format: CSV or XLSX
  - **Performance Report CSV/Excel**: export performance metrics
    - Period selection
    - Grouping (total, by account, by asset class, by security)
    - Format: CSV or XLSX
  - **Tax Report PDF**: annual tax report formatted for Vero.fi filing
    - Year selector
    - Includes: capital gains schedule, dividend income summary, osakesaastotili status, loss carry-forward
    - PDF layout matching Vero.fi appendix format as closely as possible
  - **Tax Report CSV**: structured CSV with the same data for manual verification
- **Download button** per export option; generates the file and triggers browser download

## Business Rules

1. **Transaction immutability principle**: while transactions can be edited and deleted, every modification triggers a full recalculation of tax lots from the modified transaction date forward for the affected security and account. This ensures tax lot integrity.

2. **TWR calculation**: time-weighted return is computed using the modified Dietz method between cash flow dates, then geometrically linked across sub-periods. Cash flows include deposits, withdrawals, and net buy/sell activity.

3. **MWWR calculation**: money-weighted return uses the XIRR (extended internal rate of return) algorithm on all external cash flows (deposits, withdrawals). Internal trades (buys/sells) are not counted as external cash flows.

4. **Brinson attribution methodology**:
   - Allocation effect: contribution from differing weights vs benchmark
   - Selection effect: contribution from differing returns within each asset class
   - Interaction effect: combined allocation and selection impact
   - Benchmark must provide asset class weights and returns

5. **Tax report deemed cost rule**: for each realized sale, the system computes both:
   - Actual cost basis (from tax lots)
   - Deemed cost: 20% of proceeds (or 40% if held > 10 years based on `tax_lots.acquired_date`)
   - The report uses whichever method results in higher cost basis (lower taxable gain)
   - Deemed cost does NOT apply to osakesaastotili transactions

6. **Tax bracket application**: the 30% rate applies to the first 30,000 EUR of capital income (realized gains + dividends combined). The 34% rate applies to the excess. The tax report computes the split and reports both amounts.

7. **Foreign dividend withholding**: withholding tax paid on foreign dividends is reported separately. Finland allows a credit for foreign withholding tax up to the Finnish tax rate, but the tax report does not compute the credit — it provides the data for the user to claim.

8. **Loss carry-forward**: realized losses offset gains in the same year. Net losses after offsetting can be carried forward for 5 years. The tax report tracks the carry-forward balance.

9. **CSV export encoding**: CSV files use UTF-8 encoding with BOM (byte order mark) for Excel compatibility. Column headers use English labels. Dates use ISO 8601 format. Monetary values are exported as decimal numbers (EUR, 2 decimal places), not cents.

10. **Transaction validation**: on creation or edit, the following validations apply:
    - `trade_date` cannot be in the future
    - `quantity` must be positive for buy/transfer_in, negative for sell/transfer_out
    - `sell` quantity cannot exceed current position quantity at the trade date
    - `fee_cents` must be >= 0
    - `security_id` required for buy, sell, dividend, transfer_in, transfer_out, corporate_action
    - `account_id` is always required

## Edge Cases

1. **Empty transaction history**: all views show appropriate empty states. Performance tab shows "No transactions recorded. Add your first transaction to begin tracking performance."
2. **Single transaction**: performance calculations require at least two valuation points. With a single buy and no subsequent price data, TWR is reported as 0% with a note "Insufficient data for performance calculation."
3. **Transaction edit cascading**: editing a buy transaction from 2 years ago that created a tax lot subsequently used in a sell triggers recalculation of: the original lot, the sell, the realized gain, and any subsequent lots. A progress indicator shows during recalculation.
4. **Deleting a buy with subsequent sell**: if the user tries to delete a buy transaction whose tax lot has been partially or fully closed by a sell, the system warns: "This transaction's tax lot has been used in subsequent sells. Deleting will recalculate those sells." Proceeds on confirmation.
5. **Performance across zero-value periods**: if the portfolio drops to zero value (all positions sold) and then has new deposits/buys, the TWR chain breaks. The system starts a new TWR chain from the next deposit, with a note "TWR chain restarted on {date} after zero-value period."
6. **Multi-currency performance**: all performance metrics are computed in EUR. Returns from USD-denominated securities include the FX effect. A currency attribution breakdown is a future enhancement.
7. **Tax report for years with no activity**: if a year has no realized transactions but has dividend income, the tax report still generates with the dividend section populated and the capital gains section showing zeros.
8. **Osakesaastotili withdrawal in tax report**: if a withdrawal occurred from the osakesaastotili during the year, the tax report computes the taxable portion as `withdrawal_amount * (gains / total_value)` per Finnish rules.
9. **Large CSV export**: for portfolios with thousands of transactions, CSV export is generated server-side and streamed to the client. A progress indicator shows for exports taking more than 2 seconds.
10. **Duplicate external reference**: if a transaction is created with an `external_ref` that already exists, the system returns a `CONFLICT` error to prevent accidental duplicate imports.
11. **Deemed cost edge case — short holds**: for positions held less than 1 day (bought and sold same day), the deemed cost rule still applies (20% of proceeds). This is relevant for crypto day-trading in taxable accounts.
12. **Corporate action transaction type**: transactions with `type = 'corporate_action'` are system-generated from corporate action processing. They cannot be manually created, edited, or deleted. They are displayed in the transaction log with a "System" badge.

## Acceptance Criteria

1. Transaction table displays all transactions with correct sorting, filtering, and pagination.
2. Add, edit, and delete transaction operations work correctly with proper validation and tax lot recalculation.
3. TWR and MWWR are computed correctly for configurable periods with at least 0.01% precision versus manual calculation.
4. Performance can be viewed by total, by account, by asset class, and by security.
5. Brinson attribution produces allocation, selection, and interaction effects that sum to total active return.
6. Annual tax report correctly computes realized gains/losses with deemed cost comparison for each transaction.
7. Tax bracket split (30%/34%) is correctly applied based on cumulative capital income for the year.
8. Dividend income is grouped by country with correct withholding tax amounts.
9. Osakesaastotili summary correctly reports deposits, value, and gains portion without triggering tax events for internal trades.
10. CSV export produces correctly formatted UTF-8 files with BOM that open properly in Excel.
11. PDF tax report generates with all required sections for Vero.fi filing.
12. All monetary values in reports use EUR with standard formatting per spec conventions.
13. Transaction deletion cascade correctly recalculates all affected tax lots and displays a confirmation dialog.

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
