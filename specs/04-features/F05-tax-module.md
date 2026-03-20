# F05 — Tax Module

**Status: DRAFT**

Finnish tax management — THE critical correctness feature of the terminal. A wrong tax calculation is worse than no calculation at all. This module tracks every tax lot with its cost basis and holding period, computes realized and unrealized gains under Finnish tax law (including the deemed cost of acquisition rule), monitors the osakesaastotili equity savings account, identifies loss harvesting opportunities, and generates annual tax reports compatible with Vero.fi. It answers: "What is my tax liability, how can I minimize it, and is my tax report ready?"

## Dependencies

- Specs: [data-model](../01-system/data-model.md), [api-overview](../01-system/api-overview.md), [architecture](../01-system/architecture.md), [spec-conventions](../00-meta/spec-conventions.md), [tax-finnish](../03-calculations/tax-finnish.md), [tax-lot-tracking](../03-calculations/tax-lot-tracking.md), [design-system](../05-ui/design-system.md)
- Data: Yahoo Finance daily prices pipeline (for unrealized gain calculation), ECB FX rates pipeline (for multi-currency cost basis and proceeds)
- API: `GET /tax/lots`, `GET /tax/gains`, `GET /tax/gains/annual`, `GET /tax/harvesting`, `GET /tax/osakesaastotili`, `GET /reports/tax/{year}`

## Data Requirements

### Tables Read

| Table | Purpose |
|-------|---------|
| `tax_lots` | Core data: all open and closed lots with cost basis, quantity, dates, realized P&L |
| `transactions` | Transaction details for lot creation/closing events, fees, FX rates |
| `accounts` | Account types (critical: `osakesaastotili` has different tax treatment) |
| `securities` | Security metadata for display, currency, asset class |
| `prices` | Latest prices for unrealized gain calculation |
| `fx_rates` | EUR conversion for multi-currency lots |
| `dividends` | Dividend income and withholding tax for annual tax totals |

### Tables Written

None. Tax lots are created and closed by the transaction processing logic (see [tax-lot-tracking](../03-calculations/tax-lot-tracking.md)), not by this UI feature.

### Calculations Invoked

- [tax-finnish](../03-calculations/tax-finnish.md): Finnish capital gains tax rates (30% / 34%), deemed cost of acquisition (20% / 40%), osakesaastotili withdrawal taxation, capital income threshold calculation
- [tax-lot-tracking](../03-calculations/tax-lot-tracking.md): specific identification lot matching, cost basis allocation, partial close handling

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/tax/lots` | List all tax lots. Supports `?state` (open/partially_closed/closed), `?accountId`, `?securityId`, `?fromDate`, `?toDate`, `?sortBy`, `?sortOrder`. Paginated |
| GET | `/tax/gains` | Realized + unrealized gains summary. Supports `?year`, `?accountId`. Returns totals by tax bracket |
| GET | `/tax/gains/annual` | Annual tax summary formatted for Vero.fi filing. Supports `?year` |
| GET | `/tax/harvesting` | Loss harvesting candidates: open lots with unrealized losses that could offset realized gains in the current tax year |
| GET | `/tax/osakesaastotili` | OST account status: deposits, current value, cost basis, gains portion, projected tax on withdrawal at current values |
| GET | `/reports/tax/{year}` | Generate downloadable annual tax report (Vero.fi compatible format) |

See [api-overview](../01-system/api-overview.md) for full request/response schemas.

## UI Views

### Page Layout (`/tax`)

Top: sub-tab bar — **Tax Lots** | **Gains** | **OST Tracker** | **Harvesting** | **Report**

### Sub-tab: Tax Lots (default)

Full-width table of all tax lots (DataTable with virtual scrolling for potentially hundreds of lots).

**Columns:**

| Column | Type | Sortable | Description |
|--------|------|----------|-------------|
| Security | ticker + name | Yes | Security identification |
| Account | badge | Yes | Account name with type indicator |
| State | badge | Yes | `open` (green), `partially_closed` (yellow), `closed` (gray) |
| Acquired | date | Yes | Lot acquisition date |
| Closed | date | Yes | Lot close date (blank if open) |
| Quantity (Original) | number | Yes | Original lot quantity |
| Quantity (Remaining) | number | Yes | Current open quantity |
| Cost Basis | currency | Yes | Total cost basis in EUR (includes fees) |
| Cost Per Unit | currency | No | Cost basis / original quantity |
| Market Value | currency | Yes | Current market value (open lots only) |
| Unrealized P&L | currency + % | Yes | Market value - cost basis (open lots only) |
| Realized P&L | currency | Yes | Proceeds - cost basis (closed lots only) |
| Holding Period | text | Yes | e.g., "2y 3m", "6m", "15d" |
| Deemed Cost | currency | No | 20% or 40% of current price (for comparison) |
| Better Method | badge | No | "Actual" or "Deemed" — which produces lower tax |

**Filter bar:**
- State: Open / Partially Closed / Closed / All
- Account: dropdown
- Security: text search
- Date range: acquired date from/to
- Year: quick filter for closed lots by closing year

**Interactions:**
- Click a row to expand detail panel: full transaction details (buy and sell), FX rates used, fee breakdown, deemed cost comparison calculation
- Closed lots show the sell transaction details and the tax impact
- Sort by any sortable column

### Sub-tab: Gains

**Top section — Year selector:** Dropdown for tax year (current year default, previous years available).

**Hero metrics row (4 MetricCards):**

| Metric | Format | Description |
|--------|--------|-------------|
| Realized Gains (YTD) | `€45,678.90` | Sum of positive realized P&L for the year |
| Realized Losses (YTD) | `-€12,345.67` | Sum of negative realized P&L for the year |
| Net Realized P&L | `€33,333.23` | Gains - losses |
| Estimated Tax | `€10,000 — €11,333` | Range showing tax at 30% and blended rate if above 30k threshold |

**Tax bracket visualization:**

A horizontal progress bar showing how much of the 30,000 EUR capital income threshold has been used:

```
[===========30% rate (€30,000)============|===34% rate===]
                                    ^€33,333 (current)
```

Color: `info` for the 30% portion, `warning` for the 34% portion. If total capital income (gains + dividends) is below 30k, only the 30% bar is filled.

**Gains breakdown table:**

| Category | Gains | Losses | Net | Tax Impact |
|----------|-------|--------|-----|------------|
| Regular account — Stocks | €25,000 | -€5,000 | €20,000 | €6,000 |
| Regular account — ETFs | €15,000 | -€3,000 | €12,000 | €3,600 |
| Regular account — Crypto | €8,000 | -€4,000 | €4,000 | €1,200 |
| Dividends (net of WHT) | €5,000 | — | €5,000 | €1,500 |
| **Total Capital Income** | **€53,000** | **-€12,000** | **€41,000** | **€12,740** |

Tax impact calculated using the blended rate: 30% on first 30k, 34% on excess.

**Below table — Per-security realized gains list:**

Expandable list of every closed lot in the year, grouped by security. Shows: security, account, acquired date, closed date, holding period, cost basis (actual), proceeds, realized P&L, deemed cost comparison, method used (actual vs deemed).

### Sub-tab: OST Tracker

Dedicated view for osakesaastotili monitoring.

**Top section — OST summary cards (4 MetricCards):**

| Metric | Format | Description |
|--------|--------|-------------|
| Total Deposits | `€35,000 / €50,000` with progress bar | Lifetime deposits vs cap |
| Current Value | `€42,500` | Current market value of all OST positions |
| Cost Basis (Deposits) | `€35,000` | What was deposited (= tax-free portion on withdrawal) |
| Gains Portion | `€7,500 (17.6%)` | Value - deposits. This is the taxable portion on withdrawal |

**Projected withdrawal tax calculator:**

An interactive section where the user can input a hypothetical withdrawal amount:

- **Input**: withdrawal amount in EUR (slider or numeric input, max = current value)
- **Output**: breakdown showing:
  - Taxable portion: `withdrawal_amount * (gains_portion / total_value)`
  - Tax-free portion: `withdrawal_amount * (deposits / total_value)`
  - Estimated tax: taxable portion * applicable rate (30% or 34%)
  - Net proceeds: withdrawal - tax

**OST holdings table:**

Same as the main holdings table (F01) but scoped to the OST account. Shows positions, market values, and unrealized P&L. Crucially, a banner reminds the user: "Internal trades within OST are not taxable events. Tax is calculated only on withdrawal."

**Deposit history:**

A table of all deposit transactions into the OST account with dates and amounts, showing the running total approaching the 50,000 EUR cap.

### Sub-tab: Harvesting

**Top section — Harvesting opportunity summary:**

| Metric | Format | Description |
|--------|--------|-------------|
| Total Unrealized Losses | `-€8,500` | Sum of all positions with unrealized losses |
| Realized Gains YTD | `€33,333` | From the Gains tab |
| Potential Tax Savings | `€2,550 — €2,890` | If all unrealized losses were harvested (at 30%/34%) |
| Harvesting Budget | `€33,333` | Gains available to offset (cannot create a net loss for tax purposes beyond carryforward) |

**Harvesting candidates table:**

| Column | Type | Description |
|--------|------|-------------|
| Security | ticker + name | Position identification |
| Account | badge | Account (excludes OST — harvesting is irrelevant inside OST) |
| Quantity | number | Shares held |
| Cost Basis | currency | Total cost basis |
| Market Value | currency | Current market value |
| Unrealized Loss | currency | Negative P&L (always negative in this table) |
| Holding Period | text | Time held |
| Tax Saving (est.) | currency | Estimated tax saved by realizing this loss |
| Deemed Cost Flag | badge | "Deemed cost may apply" if deemed cost > actual cost (harvesting may not save tax) |

**Important warning banner:** "Loss harvesting involves selling a position to realize a loss. Consider wash sale implications and whether you want to maintain the position. Finnish tax law does not have a specific wash sale rule, but the substance-over-form doctrine applies."

**Interactions:**
- Sort by unrealized loss (largest first), tax saving, holding period
- Click a row to see detailed tax impact analysis: what the gain/loss would be under actual cost vs deemed cost, and the net tax impact if this loss is realized

### Sub-tab: Report

**Year selector:** Dropdown for the tax reporting year.

**Report preview:**

A structured preview of the annual tax report showing the data that would be filed with Vero.fi:

1. **Securities sales (Arvopaperien luovutukset):**
   - Per-sale line items: security name, ISIN, acquisition date, sale date, quantity, acquisition cost, sale proceeds, gain/loss, deemed cost comparison
   - Total gains and losses

2. **Dividend income (Osinkotuotot):**
   - Per-security dividend summary: security name, gross amount, withholding tax, net amount
   - Total dividend income

3. **Capital income summary (Paaomatulojen yhteenveto):**
   - Total capital gains (net)
   - Total dividend income (net)
   - Total capital income
   - Tax at 30% (up to 30,000 EUR)
   - Tax at 34% (excess over 30,000 EUR)
   - Total estimated tax

4. **Osakesaastotili summary:** (if applicable)
   - No taxable events during the year (or withdrawal details if any occurred)

**Actions:**
- "Download CSV" — export in a format compatible with Vero.fi electronic filing
- "Download PDF" — formatted tax report for records
- "Copy to Clipboard" — for manual entry into Vero.fi

**Data quality checks** (displayed as a checklist above the report):
- All closed lots have complete cost basis data
- All FX rates are available for multi-currency transactions
- All dividend withholding tax amounts are recorded
- No missing ISINs for reported securities

Failed checks show as red items with explanations of what needs to be fixed before filing.

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `1` | Switch to Tax Lots sub-tab |
| `2` | Switch to Gains sub-tab |
| `3` | Switch to OST Tracker sub-tab |
| `4` | Switch to Harvesting sub-tab |
| `5` | Switch to Report sub-tab |
| `y` | Cycle tax year (current -> previous -> ...) |

## Business Rules

1. **Finnish capital gains tax rates**: 30% on capital income up to 30,000 EUR/year, 34% on income exceeding 30,000 EUR. Both realized gains and dividend income count toward the 30,000 EUR threshold.

2. **Deemed cost of acquisition (hankintameno-olettama)**: When selling, the taxpayer may use 20% of the sale price as the acquisition cost, or 40% if held for more than 10 years, instead of the actual cost — whichever results in lower tax. The system always computes both and displays the comparison. This rule does NOT apply inside osakesaastotili.

3. **Osakesaastotili taxation**: No tax events on internal trades. Tax is computed only on withdrawal: `taxable_portion = withdrawal_amount * (gains / total_value)`. The gains portion is `total_value - total_deposits`. Tax rate is 30%/34% capital income rate on the taxable portion.

4. **Osakesaastotili deposit cap**: Lifetime deposit maximum of 50,000 EUR enforced by the `accounts.osa_deposit_total_cents` constraint. The OST Tracker prominently displays remaining capacity.

5. **Loss harvesting constraints**: Losses can offset gains within the same tax year. Net capital losses can be carried forward for 5 years in Finland. The harvesting tab shows only positions in regular accounts (not OST or pension) since losses inside those accounts have no immediate tax benefit.

6. **Crypto taxation**: Each crypto-to-crypto swap is a taxable event. The tax module treats crypto disposals identically to stock sales for tax calculation purposes. The holding period for deemed cost applies to crypto as well.

7. **Multi-currency cost basis**: Cost basis is stored in the account's currency (EUR). For securities purchased in foreign currency, the cost basis includes the EUR-converted amount at the acquisition FX rate. Gains/losses include FX impact.

8. **Tax lot specific identification**: The user (or system) chooses which lots to close when selling. The tax module displays all options and their tax impact. By default, the system suggests the lot that minimizes current-year tax (considering deemed cost).

9. **Dividend withholding tax**: Foreign dividends have withholding tax at source (e.g., 15% US treaty rate). This is reported separately in the tax report. Finnish tax credit for foreign withholding tax is noted but the calculation of the credit itself is outside this module's scope (it depends on the full tax return).

10. **Report accuracy disclaimer**: The generated report is an aid for tax filing, not a substitute for professional tax advice. A disclaimer is displayed: "This report is generated for informational purposes. Verify all figures before filing with Vero.fi."

## Edge Cases

1. **No realized gains in the year**: Gains tab shows zero values. Tax bracket bar is empty. Harvesting tab shows "No realized gains to offset. Harvesting would create a net capital loss (carryforward eligible)."

2. **Deemed cost more favorable than actual cost**: The Tax Lots table highlights these lots with a "Deemed" badge in the Better Method column. The per-sale detail in the Report tab shows both calculations side by side.

3. **Holding period exactly 10 years**: The 40% deemed cost applies to securities held "more than 10 years." A lot acquired on 2016-03-19 and sold on 2026-03-19 has been held exactly 10 years — the 40% rule does NOT apply (must be MORE than 10 years). Sold on 2026-03-20 — it applies. The system uses `sold_date - acquired_date > 3652 days` (accounting for leap years).

4. **Partial lot close**: When a sell closes only part of a lot, the cost basis is allocated proportionally. Example: lot of 100 shares at €10,000 cost basis; selling 60 shares allocates €6,000 cost basis to the closed portion and leaves €4,000 on the remaining 40 shares.

5. **OST deposit at cap**: If `osa_deposit_total_cents = 5,000,000` (50,000 EUR), the deposit progress bar shows 100% with a message: "Maximum deposit limit reached. No further deposits can be made to this account."

6. **Corporate action affecting tax lots**: Splits adjust lot quantities and per-unit cost basis without triggering a taxable event. The Tax Lots table shows the adjusted values with a "Split adjusted" note and a link to the corporate action record.

7. **Missing cost basis (transferred-in securities)**: Securities transferred in from another broker may lack original cost basis. The lot shows cost basis as `€0` with a red warning: "Cost basis unknown. Enter the original acquisition cost to ensure accurate tax reporting." The user must manually provide this via transaction editing.

8. **Capital income exceeds 30,000 EUR threshold mid-year**: The Gains tab dynamically shows which sales pushed total capital income over 30,000 EUR and the marginal tax rate (34%) on the excess. The tax bracket bar visually marks the threshold crossing.

9. **Crypto-to-crypto swap**: Treated as two events: sale of source crypto (taxable) and purchase of target crypto (new lot). Both appear in the Tax Lots table. The Gains tab includes the realized gain/loss from the source crypto sale.

10. **No osakesaastotili account**: The OST Tracker tab shows: "No osakesaastotili account found. Create one in Account settings to track equity savings account activity."

11. **Report data quality failure**: If any check fails (missing cost basis, missing FX rate, missing ISIN), the "Download" buttons are disabled. A red banner lists the issues that must be resolved first.

12. **Loss in OST (current value < deposits)**: The OST Tracker correctly shows a negative gains portion. Projected withdrawal shows the full amount as tax-free (you cannot have negative taxable gains on withdrawal — the loss simply means no tax).

## Acceptance Criteria

1. The Tax Lots table displays all lots with correct state, dates, quantities, cost basis, market value, unrealized/realized P&L, holding period, and deemed cost comparison.
2. Filtering and sorting work correctly on all supported columns and filter dimensions.
3. The Gains tab correctly computes realized gains/losses for the selected year, including the 30k/34% threshold visualization.
4. The tax bracket progress bar accurately shows where total capital income sits relative to the 30,000 EUR threshold.
5. The estimated tax calculation is correct for both under-30k and over-30k scenarios, considering both gains and dividend income.
6. The OST Tracker shows correct deposit totals, current value, gains portion, and remaining deposit capacity.
7. The OST withdrawal calculator correctly computes the taxable portion, tax-free portion, and estimated tax for any withdrawal amount.
8. Loss harvesting candidates are correctly identified (positions with unrealized losses in regular accounts only, not OST).
9. The estimated tax saving for each harvesting candidate is correct.
10. The deemed cost comparison is computed correctly, including the 10-year threshold for the 40% rate.
11. The annual tax report contains all required sections (securities sales, dividends, capital income summary) with correct figures.
12. Data quality checks identify and flag missing cost basis, FX rates, ISINs, and withholding tax data.
13. The CSV export is formatted compatibly with Vero.fi electronic filing requirements.
14. The report disclaimer is displayed prominently.
15. All monetary values use integer cents arithmetic internally with correct EUR display formatting.
16. The holding period calculation correctly determines whether the 40% deemed cost threshold is met (strictly more than 10 years).
17. Corporate actions (splits) are reflected correctly in tax lot quantities and per-unit cost basis.

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
