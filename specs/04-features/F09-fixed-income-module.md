# F09 — Fixed Income Module

Bond allocation management module supporting the glidepath toward 60% fixed income by age 60. Provides the Fixed Income Analyst with bond ladder visualization, yield curve analysis with portfolio position overlay, income projection timelines for retirement planning, and duration risk analysis. This module becomes increasingly central as the 15-year retirement horizon shortens.

**Status: DRAFT**

## Dependencies

- [Data Model](../01-system/data-model.md) — `securities` table (asset_class = 'bond'), `prices` hypertable, `holdings_snapshot`, `tax_lots`, `macro_indicators` (yield curve data)
- [API Overview](../01-system/api-overview.md) — `/fixed-income` endpoint group
- [Spec Conventions](../00-meta/spec-conventions.md) — monetary format (cents), date/time
- [F07 — Macro Dashboard](./F07-macro-dashboard.md) — yield curve data shared with macro indicators
- [F01 — Portfolio Dashboard] — glidepath target allocation data
- [F10 — Alerts & Rebalancing](./F10-alerts-rebalancing.md) — glidepath drift alerts

## Data Requirements

### Bond Securities

Bond-type securities in the `securities` table include the following categories, differentiated by metadata fields:

| Bond Type | `asset_class` | Identification | Notes |
|-----------|--------------|----------------|-------|
| Finnish Government Bonds | `bond` | `country = 'FI'`, `sector = 'government'` | Primary EUR-denominated sovereign |
| EU Sovereign Bonds | `bond` | `country IN ('DE','FR','NL',...)`, `sector = 'government'` | Other eurozone government bonds |
| Corporate Investment Grade | `bond` | `sector = 'corporate'` | Requires credit rating IG (BBB- or above) |
| Inflation-Linked Bonds | `bond` | Identified by ticker convention or metadata tag | EU inflation-linked (e.g., OATi, BTPei) |
| Bond ETFs | `etf` | `sector LIKE '%bond%'` or metadata tag | iShares, Vanguard, Xtrackers bond ETFs |

### Bond-Specific Fields

The following fields are needed for bond analysis but are not currently in the `securities` table. They will be stored in a `bond_details` extension table or as JSONB metadata:

| Field | Type | Description |
|-------|------|-------------|
| `maturity_date` | DATE | Bond maturity date |
| `coupon_rate` | NUMERIC(7,4) | Annual coupon rate (percent) |
| `coupon_frequency` | INTEGER | Payments per year (1, 2, 4) |
| `face_value_cents` | BIGINT | Par value in cents |
| `credit_rating` | VARCHAR(10) | S&P/Moody's rating (e.g., 'AAA', 'BBB+') |
| `is_inflation_linked` | BOOLEAN | Whether coupon adjusts for inflation |
| `yield_to_maturity` | NUMERIC(7,4) | Current YTM (percent), refreshed daily |
| `modified_duration` | NUMERIC(7,4) | Modified duration in years |
| `convexity` | NUMERIC(10,4) | Bond convexity measure |

### Yield Curve Data

Shared with F07 Macro Dashboard. Uses `macro_indicators` hypertable entries with codes:
- `EU_YIELD_3M`, `EU_YIELD_2Y`, `EU_YIELD_5Y`, `EU_YIELD_10Y`, `EU_YIELD_30Y`

### Income Projection Inputs

- Current age: 45 (from investor profile)
- Retirement age: 60
- Bond coupon payments from held bonds (from `bond_details`)
- Bond ETF distribution yields (from fund data)
- Reinvestment assumptions (configurable)

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/fixed-income/ladder` | Bond ladder: all held bonds/bond ETFs with maturity dates, coupon rates, and face values |
| GET | `/fixed-income/yield-analysis` | Current EU yield curve with portfolio bond positions plotted by maturity and YTM |
| GET | `/fixed-income/income-projection` | Projected monthly/annual income from bonds post-retirement, with configurable assumptions |
| GET | `/fixed-income/duration` | Portfolio-level duration analysis: weighted average duration, key rate durations, convexity |
| GET | `/fixed-income/summary` | Fixed income allocation summary: total fixed income value, weight vs glidepath target, bond type breakdown |

### Query Parameters

| Endpoint | Parameter | Type | Description |
|----------|-----------|------|-------------|
| `/fixed-income/income-projection` | `retirementAge` | integer | Override default retirement age (default: 60) |
| `/fixed-income/income-projection` | `reinvestmentRate` | float | Assumed reinvestment yield for maturing bonds (default: current 5Y yield) |
| `/fixed-income/income-projection` | `inflationRate` | float | Assumed annual inflation for real income calculation (default: 2.0%) |
| `/fixed-income/yield-analysis` | `curveDate` | date | Historical yield curve date for comparison (default: today) |

### Response: `GET /fixed-income/ladder`

```json
{
  "data": {
    "bonds": [
      {
        "securityId": 101,
        "ticker": "RFGB0230",
        "name": "Finland Government Bond 2.0% 2030",
        "type": "government",
        "maturityDate": "2030-04-15",
        "couponRate": 2.0,
        "couponFrequency": 1,
        "faceValue": { "amount": 1000000, "currency": "EUR" },
        "marketValue": { "amount": 987500, "currency": "EUR" },
        "quantity": 10,
        "yieldToMaturity": 2.45,
        "modifiedDuration": 3.72,
        "creditRating": "AA+",
        "annualIncome": { "amount": 20000, "currency": "EUR" },
        "accountId": 1,
        "accountName": "Nordnet Regular"
      }
    ],
    "summary": {
      "totalFaceValue": { "amount": 5000000, "currency": "EUR" },
      "totalMarketValue": { "amount": 4875000, "currency": "EUR" },
      "totalAnnualIncome": { "amount": 95000, "currency": "EUR" },
      "weightedAvgYTM": 2.78,
      "weightedAvgDuration": 5.14,
      "bondCount": 8,
      "nextMaturity": { "securityId": 101, "date": "2028-06-15" }
    }
  }
}
```

### Response: `GET /fixed-income/duration`

```json
{
  "data": {
    "portfolioWeightedDuration": 5.14,
    "portfolioConvexity": 32.7,
    "keyRateDurations": {
      "2Y": 0.45,
      "5Y": 1.82,
      "10Y": 2.15,
      "30Y": 0.72
    },
    "durationByType": {
      "government": { "duration": 4.2, "weight": 0.55 },
      "corporate": { "duration": 3.8, "weight": 0.25 },
      "inflationLinked": { "duration": 7.1, "weight": 0.10 },
      "bondEtf": { "duration": 6.3, "weight": 0.10 }
    },
    "interestRateSensitivity": {
      "rateChangePercent": 1.0,
      "estimatedPortfolioImpact": { "amount": -250000, "currency": "EUR" },
      "estimatedImpactPercent": -5.14
    }
  }
}
```

## UI Views

### Sub-tab: Ladder

- **Bond ladder visualization** (horizontal timeline chart):
  - X-axis: time (years), from today to the latest maturity date
  - Each bond represented as a horizontal bar from purchase date to maturity date
  - Bar height proportional to face value
  - Color coded by bond type: government (blue), corporate (green), inflation-linked (orange), bond ETF (purple)
  - Hover tooltip: security name, maturity date, coupon rate, YTM, face value, market value
- **Bond table** below the chart:
  - Columns: Name, Type, Maturity, Coupon, YTM, Duration, Face Value, Market Value, Rating, Account
  - Sortable by any column
  - Row click opens security detail
- **Summary cards** above the chart:
  - Total face value, total market value, weighted average YTM, weighted average duration, next maturity date
  - See component: `MetricCard`

### Sub-tab: Yield Analysis

- **Yield curve chart** (Recharts):
  - Current EU government yield curve (line)
  - Historical comparison curves: 1M ago, 6M ago, 1Y ago (dashed lines)
  - **Portfolio position overlay**: scatter plot of each held bond at its maturity and YTM coordinates
  - Bubble size proportional to position market value
  - Color coded by bond type
  - Hover on bubble shows bond details
- **Spread analysis table**:
  - For each held corporate bond: credit spread over the corresponding government yield at the same maturity
  - Flagged if spread is historically tight (<25th percentile) or wide (>75th percentile)

### Sub-tab: Income Projection

- **Income timeline chart** (Recharts area chart):
  - X-axis: years from now to age 75 (15 years post-retirement)
  - Y-axis: annual income in EUR
  - Stacked areas: coupon income (by bond), ETF distribution income, reinvestment income
  - Vertical dashed line at retirement age (60)
  - Inflation-adjusted line overlay (real vs nominal)
- **Monthly income breakdown table** (for the first 5 years post-retirement):
  - Columns: Month, Bond Name, Coupon Payment, Cumulative Annual Income
- **Assumptions panel** (collapsible sidebar):
  - Editable fields: retirement age, reinvestment rate, inflation rate, target monthly income
  - "Target met?" indicator: green check if projected income >= target, red X if shortfall
  - Shortfall amount displayed if applicable
- **Gap analysis card**: if projected income falls short of a configurable target, shows the additional capital needed at current yields to close the gap

### Sub-tab: Duration

- **Duration dashboard**:
  - Large metric: portfolio weighted average duration (years)
  - Key rate duration bar chart: contribution at 2Y, 5Y, 10Y, 30Y buckets
  - Duration by bond type: horizontal stacked bar showing contribution from each type
- **Interest rate sensitivity table**:
  - Shows estimated portfolio value change for -200bps, -100bps, -50bps, +50bps, +100bps, +200bps rate moves
  - Both absolute EUR change and percentage change
- **Duration target indicator**: if the portfolio has a target duration range (e.g., 4-6 years for the current glidepath stage), show current vs target with a gauge visualization

## Business Rules

1. **Glidepath fixed income target**: at current age 45, the target fixed income allocation is 15%. This increases per the glidepath schedule in AGENTS.md. The module displays actual vs target fixed income weight and the gap.

2. **Ladder maturity matching**: the bond ladder should aim to have bonds maturing in each year from retirement (age 60) onward, providing a predictable income stream. The module highlights years with no maturing bonds as "coverage gaps."

3. **Duration target**: as the glidepath progresses and time to retirement shortens, the target portfolio duration should approximately match the investment horizon. At age 45 with 15 years to retirement, a duration of ~5-7 years is appropriate. This shortens as retirement approaches.

4. **Income projection reinvestment**: when a bond matures before retirement, the proceeds are assumed to be reinvested at the user-configurable reinvestment rate (default: current 5Y government yield).

5. **Bond ETF treatment**: bond ETFs do not have a maturity date. They are represented in the ladder view as an ongoing bar (no end date) and contribute to income projections via their distribution yield, not coupon payments.

6. **Credit quality requirement**: only investment grade bonds (BBB- or above) are included in the recommended allocation. Non-investment-grade bonds, if held, are flagged with a warning badge.

7. **Inflation-linked bond adjustment**: for inflation-linked bonds, the income projection applies the user-specified inflation rate to adjust coupon payments upward, reflecting the real income advantage.

## Edge Cases

1. **No bond holdings**: if the portfolio contains zero fixed income positions, all sub-tabs show an empty state with a message explaining the glidepath target and recommending the user consider fixed income allocation.
2. **Bond ETF without distribution data**: if a bond ETF has no distribution yield data available, it is excluded from income projections with a note "Distribution yield unavailable."
3. **Matured bonds still in portfolio**: if a bond's maturity date has passed but the position is still open (e.g., pending settlement or data delay), it is displayed with a "MATURED" badge and excluded from forward-looking projections.
4. **Callable bonds**: bonds with call features may be redeemed before maturity. The ladder view shows the call date as a secondary marker on the bar. Income projections use yield-to-worst (the lesser of YTM and yield-to-call).
5. **Missing credit rating**: if a bond has no credit rating in the data source, it is shown with "NR" (Not Rated) and a warning badge. It is not counted toward the investment-grade allocation metric.
6. **Negative yielding bonds**: the yield analysis chart and duration calculations must handle negative yields correctly. Negative YTM bonds display the value in red.
7. **Currency mismatch**: if a non-EUR bond is held (e.g., USD corporate bond), market value and income projections convert to EUR using current FX rates. An FX risk note appears on the income projection chart.
8. **Glidepath ahead of schedule**: if the current fixed income allocation exceeds the glidepath target for the current age, the summary displays "Ahead of schedule" in green rather than flagging a drift alert.

## Acceptance Criteria

1. Bond ladder visualization renders all held bonds and bond ETFs on a timeline with correct maturity dates and proportional sizing.
2. Yield curve chart displays current EU government curve at 5 maturities with portfolio positions overlaid as sized bubbles.
3. Income projection generates monthly/annual income streams from retirement age to age 75, with adjustable assumptions.
4. Duration analysis shows portfolio weighted average duration, key rate durations, and interest rate sensitivity table.
5. Summary cards show total fixed income value, actual vs glidepath target weight, and weighted average YTM/duration.
6. Coverage gaps in the bond ladder (years with no maturing bonds) are visually highlighted.
7. Interest rate sensitivity table correctly estimates portfolio impact for rate changes of +/- 50, 100, and 200 bps.
8. All monetary values displayed in EUR using the standard `amount_cents` / 100 formatting with euro sign prefix.
9. Bond ETFs render correctly in the ladder (no end date) and contribute to income projections via distribution yield.

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
