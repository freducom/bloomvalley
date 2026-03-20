# F10 — Alerts & Rebalancing

Alert engine and rebalancing suggestion module. Provides the Portfolio Manager and Compliance Officer with configurable alerts for price movements, allocation drift, glidepath compliance, dividend events, and data staleness. The rebalancing module computes suggested trades to bring the portfolio back to target allocation with tax-aware optimization.

**Status: DRAFT**

## Dependencies

- [Data Model](../01-system/data-model.md) — `alerts` table, `holdings_snapshot`, `tax_lots`, `dividends`, `pipeline_runs`, `securities`, `prices`
- [API Overview](../01-system/api-overview.md) — `/alerts` endpoint group
- [Spec Conventions](../00-meta/spec-conventions.md) — monetary format, date/time, naming rules
- [F01 — Portfolio Dashboard] — target allocation and glidepath data
- [F05 — Tax Module] — tax lot data for tax impact estimation
- [F07 — Macro Dashboard](./F07-macro-dashboard.md) — regime transition alerts

## Data Requirements

### Alert Types

Stored in the `alerts` table using the `alerts_type_enum`. The enum is extended to support the full set:

| Alert Type | `alerts_type_enum` Value | Scope | Threshold Meaning |
|-----------|------------------------|-------|-------------------|
| Price Above | `price_above` | Per security | Price in cents |
| Price Below | `price_below` | Per security | Price in cents |
| Drift Threshold | `drift_threshold` | Portfolio-level | Drift percentage (default 5.0) |
| Glidepath Behind | `glidepath_behind` | Portfolio-level | Deviation percentage from glidepath target |
| Dividend Announced | `dividend_announced` | Per security | N/A (triggered on ex-date announcement) |
| Data Staleness | `staleness` | Per data source | Hours since last successful pipeline run |
| Custom | `custom` | Flexible | User-defined |

### Alert Evaluation

- **Price alerts**: evaluated on every price update (during market hours, every 15 minutes for stocks/ETFs, every 5 minutes for crypto)
- **Drift alerts**: evaluated nightly after `holdings_snapshot` rebuild
- **Glidepath alerts**: evaluated nightly, comparing current allocation to the glidepath target for the current age
- **Dividend alerts**: evaluated when dividend data pipeline detects new ex-dates for held securities
- **Staleness alerts**: evaluated every 30 minutes, checking `pipeline_runs` for each source

### Rebalancing Data

The rebalancing module requires:
- Current allocation from `holdings_snapshot` (latest snapshot date)
- Target allocation from glidepath configuration (by asset class: equities, fixed income, crypto, cash)
- Current holdings with market values and quantities
- Tax lots for each holding (to estimate tax impact of sells)
- Current prices for trade amount calculation
- FX rates for multi-currency positions

## API Endpoints

### Alert Management

| Method | Path | Description |
|--------|------|-------------|
| GET | `/alerts` | List all alerts; supports filters: `status` (active, triggered, dismissed, expired), `type`, `securityId` |
| POST | `/alerts` | Create a new alert |
| PUT | `/alerts/{id}` | Update an alert (edit threshold, enable/disable) |
| DELETE | `/alerts/{id}` | Delete an alert |
| POST | `/alerts/{id}/dismiss` | Dismiss a triggered alert |
| GET | `/alerts/history` | Paginated list of triggered and dismissed alerts; supports `fromDate`, `toDate` |

### Rebalancing

| Method | Path | Description |
|--------|------|-------------|
| GET | `/alerts/rebalancing` | Current rebalancing suggestions with tax impact estimates |
| GET | `/alerts/rebalancing?mode=minimize_tax` | Rebalancing with tax-minimization priority |
| GET | `/alerts/rebalancing?mode=exact_target` | Rebalancing to hit exact target weights |

### Request: `POST /alerts`

```json
{
  "type": "price_below",
  "securityId": 42,
  "thresholdValue": 14000,
  "thresholdCurrency": "USD",
  "message": "AAPL dropped below $140 — consider adding to position",
  "expiresAt": "2026-06-19T00:00:00Z"
}
```

### Response: `GET /alerts/rebalancing`

```json
{
  "data": {
    "mode": "minimize_tax",
    "currentAllocation": {
      "equities": { "actual": 78.2, "target": 75.0, "drift": 3.2 },
      "fixedIncome": { "actual": 12.5, "target": 15.0, "drift": -2.5 },
      "crypto": { "actual": 6.8, "target": 7.0, "drift": -0.2 },
      "cash": { "actual": 2.5, "target": 3.0, "drift": -0.5 }
    },
    "suggestedTrades": [
      {
        "action": "sell",
        "securityId": 42,
        "ticker": "AAPL",
        "name": "Apple Inc.",
        "accountId": 1,
        "accountName": "Nordnet Regular",
        "quantity": 5,
        "estimatedProceeds": { "amount": 76250, "currency": "USD" },
        "estimatedProceedsEur": { "amount": 70370, "currency": "EUR" },
        "taxImpact": {
          "realizedGain": { "amount": 23500, "currency": "EUR" },
          "estimatedTax": { "amount": 7050, "currency": "EUR" },
          "taxRate": 30.0,
          "lotDetails": [
            {
              "taxLotId": 15,
              "acquiredDate": "2023-05-12",
              "quantity": 5,
              "costBasis": { "amount": 46870, "currency": "EUR" },
              "heldOverTenYears": false,
              "deemedCostApplicable": false
            }
          ]
        }
      },
      {
        "action": "buy",
        "securityId": 210,
        "ticker": "VAGF",
        "name": "Vanguard EUR Govt Bond ETF",
        "accountId": 1,
        "accountName": "Nordnet Regular",
        "quantity": 15,
        "estimatedCost": { "amount": 70125, "currency": "EUR" },
        "taxImpact": null
      }
    ],
    "summary": {
      "totalSells": { "amount": 70370, "currency": "EUR" },
      "totalBuys": { "amount": 70125, "currency": "EUR" },
      "netCashFlow": { "amount": 245, "currency": "EUR" },
      "totalEstimatedTax": { "amount": 7050, "currency": "EUR" },
      "postRebalanceAllocation": {
        "equities": 75.1,
        "fixedIncome": 14.9,
        "crypto": 6.8,
        "cash": 3.2
      }
    }
  }
}
```

## UI Views

### Sub-tab: Active Alerts

- **Alert creation form** (accessible via "+ New Alert" button):
  - Alert type selector (dropdown)
  - Security search (for price and dividend alerts; hidden for portfolio-level types)
  - Threshold value input (contextual: price for price alerts, percentage for drift alerts)
  - Message (free text, optional custom message; auto-generated default based on type)
  - Expiration date picker (optional)
  - Enable/disable toggle
- **Active alerts table**:
  - Columns: Type (icon + label), Security/Scope, Threshold, Message, Created, Expires, Status toggle
  - Sortable by type, security, creation date
  - Row actions: Edit (pencil icon), Delete (trash icon), Enable/Disable (toggle switch)
  - Color-coded type icons: price (blue), drift (yellow), glidepath (orange), dividend (green), staleness (red)
- **Quick alert creation**: from any security view in the terminal, a "Set Alert" shortcut creates a price alert pre-populated with the security

### Sub-tab: History

- **Triggered alerts feed** (reverse chronological):
  - Each entry shows: type icon, message, triggered timestamp, security (if applicable), threshold that was breached, current value at trigger time
  - Dismiss button per alert (moves to dismissed state)
  - Bulk dismiss: "Dismiss All" for a selected date range
- **Filters**: date range picker, type filter, status filter (triggered / dismissed)
- **Statistics card**: alerts triggered this week/month/year, most common alert type, securities with most triggers

### Sub-tab: Rebalancing

- **Current vs Target allocation table**:
  - Columns: Asset Class, Current Weight (%), Target Weight (%), Drift (%), Status (on-target / overweight / underweight)
  - Visual bar showing current vs target as overlapping horizontal bars
  - Drift cells colored: green if within tolerance (<=2%), yellow if 2-5%, red if >5%
- **Optimization mode toggle**: "Minimize Tax" (default) | "Exact Target"
  - Minimize Tax: reduces sells of appreciated positions, prefers selling lots with losses or minimal gains, may leave small residual drift
  - Exact Target: hits exact target weights regardless of tax consequences
- **Suggested trades table**:
  - Columns: Action (Buy/Sell badge), Security, Account, Quantity, Estimated Value, Tax Impact
  - Tax impact column shows estimated realized gain/loss and tax amount; highlighted red for high-tax trades
  - Expandable row detail shows specific tax lots being consumed with acquisition dates and cost basis
  - "Use osakesaastotili" note if a sell can be executed inside the tax-advantaged account (no tax event)
- **Summary panel** (bottom of tab):
  - Total sells, total buys, net cash flow, total estimated tax
  - Post-rebalance allocation preview
  - "Apply" button: does NOT auto-execute trades; generates a rebalancing report that can be exported or used as a checklist for manual execution

## Business Rules

1. **Drift threshold**: the default drift trigger is 5% absolute deviation from target for any asset class. This is configurable per alert.

2. **Glidepath evaluation**: the glidepath alert compares current allocation to the interpolated target for the user's exact current age (linear interpolation between the age milestones in the glidepath schedule).

3. **Tax impact calculation**:
   - For sells: identify which tax lots would be consumed (default: highest cost basis first to minimize gain, in "minimize tax" mode; FIFO in "exact target" mode)
   - Compute realized gain: `proceeds - cost_basis`
   - Apply Finnish deemed cost of acquisition rule: if 20% of proceeds (or 40% if held > 10 years) exceeds actual cost basis, use the deemed cost instead
   - Apply Finnish capital gains tax rate: 30% on gains up to 30,000 EUR/year cumulative, 34% above
   - Track year-to-date realized gains to determine correct marginal rate
   - Osakesaastotili trades: tax impact = 0 (no taxable event on internal trades)

4. **Minimize tax mode priorities** (in order):
   a. Sell positions inside osakesaastotili (no tax)
   b. Sell loss-making positions (generates tax-deductible losses)
   c. Sell positions with smallest gains
   d. Sell positions held >10 years (eligible for 40% deemed cost)
   e. Sell positions with largest gains (last resort)

5. **Alert deduplication**: a price alert that triggers does not re-trigger until the price has moved back across the threshold in the opposite direction and then crossed again. This prevents alert spam during price oscillation around the threshold.

6. **Staleness alert thresholds**: default thresholds per pipeline source:
   - Yahoo Finance prices: 2 hours during market hours, 18 hours outside
   - FRED macro data: 48 hours
   - ECB FX rates: 48 hours
   - CoinGecko crypto: 30 minutes
   - ESG scores: 45 days

7. **Dividend alert timing**: dividend alerts fire when a new ex-date is detected for a held security, giving the user time to decide whether to hold through the ex-date or sell before.

8. **Rebalancing minimum trade size**: suggested trades below 100 EUR are suppressed to avoid impractical micro-trades. Residual drift from suppressed trades is noted in the summary.

## Edge Cases

1. **No drift detected**: if all asset classes are within the drift threshold, the Rebalancing tab shows a "Portfolio is balanced" message with the current allocation table. No trades are suggested.
2. **Insufficient cash for buys**: if the suggested rebalancing requires buying but there is insufficient cash (and sells do not fully cover buys), the module adjusts suggested quantities downward and notes "Partial rebalancing: insufficient cash for full target."
3. **All positions in osakesaastotili**: if all overweight positions are inside the osakesaastotili, the "minimize tax" mode reduces to "exact target" since no tax is owed regardless.
4. **Year-end tax optimization**: near year-end (December), the tax impact calculation should factor in the year-to-date realized gains to determine whether the 30% or 34% rate applies to suggested sells.
5. **Alert on delisted security**: if a security is delisted (`is_active = FALSE`), any active price alerts on it are automatically set to `expired` status with a note "Security delisted."
6. **Multiple alerts for same condition**: a user may create multiple price alerts at different thresholds for the same security. Each triggers independently.
7. **Glidepath alert during market crash**: if a sudden market drop pushes equity allocation below target (the opposite of the usual drift), the glidepath alert still fires but with a "Below target — consider buying equities" message rather than a sell suggestion.
8. **Rebalancing with pending corporate action**: if a corporate action is pending (`is_processed = FALSE`) for a held security, that security is excluded from rebalancing suggestions with a note "Pending corporate action — excluded from rebalancing."
9. **Crypto rebalancing tax complexity**: since every crypto trade is a taxable event in Finland, the tax impact for crypto sells must account for the specific lot identification method and potentially high short-term gains. The "minimize tax" mode may suggest underweight tolerance for crypto to avoid triggering taxable events.
10. **Empty alerts table**: if no alerts exist, the Active Alerts tab shows an onboarding prompt explaining alert types with a "Create your first alert" call to action.

## Acceptance Criteria

1. User can create, edit, delete, enable, and disable alerts for all five alert types (price, drift, glidepath, dividend, staleness).
2. Price alerts trigger correctly when the price crosses the threshold, with deduplication preventing repeat triggers during oscillation.
3. Drift alerts fire nightly when any asset class deviates >5% (or custom threshold) from target allocation.
4. Alert history displays all triggered and dismissed alerts with timestamps and trigger values.
5. Rebalancing module shows current vs target allocation with drift percentages and visual bars.
6. Suggested trades include tax impact estimates using the correct Finnish tax rules (30%/34% brackets, deemed cost, osakesaastotili exemption).
7. "Minimize tax" mode prioritizes osakesaastotili sells, then losses, then smallest gains.
8. "Exact target" mode produces trades that bring allocation within 0.5% of targets regardless of tax impact.
9. Rebalancing summary shows total sells, buys, net cash flow, and total estimated tax.
10. Minimum trade size of 100 EUR is enforced; smaller trades are suppressed with a note.
11. All monetary values use the standard cents format with EUR display per spec conventions.

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
