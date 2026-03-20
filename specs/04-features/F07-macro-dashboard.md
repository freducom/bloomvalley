# F07 — Macro Dashboard

Macroeconomic overview and news analysis module providing the Macro Strategist with a unified view of key economic indicators, yield curve dynamics, economic cycle regime assessment, and global news with portfolio impact analysis. This dashboard surfaces the data needed to map macro conditions to asset class positioning and to identify risks or opportunities for the portfolio.

**Status: DRAFT**

## Dependencies

- [Data Model](../01-system/data-model.md) — `macro_indicators` hypertable, `pipeline_runs` table
- [API Overview](../01-system/api-overview.md) — `/macro` endpoint group
- [Architecture](../01-system/architecture.md) — FRED and ECB pipeline adapters
- [Spec Conventions](../00-meta/spec-conventions.md) — date/time, naming rules

## Data Requirements

### Indicator Catalog

The following indicators are tracked in the `macro_indicators` hypertable:

| Indicator Code | Name | Source | Frequency | Unit |
|---------------|------|--------|-----------|------|
| `ECBMRO` | ECB Main Refinancing Rate | ECB | On decision | percent |
| `EZ_HICP` | Eurozone HICP Inflation (YoY) | ECB / FRED | Monthly | percent |
| `FI_GDP` | Finland GDP Growth (YoY) | Statistics Finland / FRED | Quarterly | percent |
| `EZ_PMI_COMP` | Eurozone Composite PMI | FRED | Monthly | index |
| `EZ_PMI_MFG` | Eurozone Manufacturing PMI | FRED | Monthly | index |
| `FI_UNEMPLOYMENT` | Finland Unemployment Rate | Statistics Finland / FRED | Monthly | percent |
| `EU_YIELD_3M` | EU 3-Month Government Bond Yield | ECB | Daily | percent |
| `EU_YIELD_2Y` | EU 2-Year Government Bond Yield | ECB | Daily | percent |
| `EU_YIELD_5Y` | EU 5-Year Government Bond Yield | ECB | Daily | percent |
| `EU_YIELD_10Y` | EU 10-Year Government Bond Yield | ECB | Daily | percent |
| `EU_YIELD_30Y` | EU 30-Year Government Bond Yield | ECB | Daily | percent |
| `EURUSD` | EUR/USD Exchange Rate | ECB | Daily | rate |
| `EZ_CREDIT_SPREAD` | Eurozone Investment Grade Credit Spread | FRED | Daily | basis_points |
| `VIX` | CBOE Volatility Index | FRED | Daily | index |

### Data Freshness

- Daily indicators (yields, FX, VIX): refreshed every market day via FRED/ECB pipelines
- Monthly indicators (HICP, PMI, unemployment): refreshed daily, new data appears on publication schedule
- Quarterly indicators (GDP): refreshed daily, new data appears on publication schedule
- Staleness threshold: 2x the expected publication interval per indicator

### News Data

News items are fetched from Google News RSS feeds and Finnhub, filtered for macroeconomic relevance. Each news item includes:

- Headline, source, publication timestamp, URL
- Impact tags: affected asset classes, affected sectors, sentiment (positive/negative/neutral)
- Relevance score (0-100) computed by keyword matching against portfolio holdings and watchlist

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/macro/indicators` | List all tracked indicators with latest value, previous value, change, and trend direction |
| GET | `/macro/indicators/{code}` | Historical time-series for a single indicator; supports `fromDate`, `toDate` query params |
| GET | `/macro/yield-curve` | Current yield curve data points (3M, 2Y, 5Y, 10Y, 30Y) plus historical curves for comparison (1M ago, 6M ago, 1Y ago) |
| GET | `/macro/regime` | Current economic regime assessment with supporting indicator values |
| GET | `/macro/news` | Paginated global news feed with impact tags; supports `fromDate`, `toDate`, `sentiment`, `assetClass` filters |

### Response: `GET /macro/regime`

```json
{
  "data": {
    "regime": "expansion",
    "confidence": "high",
    "since": "2025-09-01",
    "signals": {
      "pmi": { "value": 53.2, "signal": "expansion", "weight": 0.3 },
      "yieldCurveSlope": { "value": 1.45, "signal": "expansion", "weight": 0.25 },
      "creditSpread": { "value": 95, "signal": "expansion", "weight": 0.2 },
      "unemployment": { "value": 6.8, "signal": "neutral", "weight": 0.15 },
      "inflation": { "value": 2.3, "signal": "neutral", "weight": 0.1 }
    },
    "implication": "Favor equities over bonds. Maintain current glidepath allocation. Monitor PMI for early slowdown signals."
  }
}
```

## UI Views

### Sub-tab: Indicators

- **Key indicator cards** (grid layout, 2-3 per row):
  - Each card shows: indicator name, current value, previous value, change (absolute + percentage), trend arrow, sparkline (last 12 data points), last updated timestamp
  - Cards for: ECB rate, eurozone HICP, Finland GDP, composite PMI, Finland unemployment
  - Color coding: green if improving (relative to economic health), red if deteriorating, neutral gray if unchanged
  - See component: `MetricCard`
- **Indicator detail**: clicking a card opens a full time-series chart (Recharts line chart) with configurable date range

### Sub-tab: Yield Curve

- **Yield curve chart** (Recharts):
  - X-axis: maturity (3M, 2Y, 5Y, 10Y, 30Y)
  - Y-axis: yield (percent)
  - Lines: current curve (solid), 1M ago (dashed), 6M ago (dotted), 1Y ago (light dotted)
  - Hover tooltip shows exact yield at each maturity for all displayed curves
- **Yield curve slope indicator**: 10Y minus 2Y spread, with inversion warning badge
- **Historical slope chart**: time-series of the 10Y-2Y spread over configurable period

### Sub-tab: Regime

- **Regime indicator** (large central display):
  - Four-phase cycle diagram: Expansion, Slowdown, Recession, Recovery
  - Current phase highlighted with confidence level (High / Medium / Low)
  - Date since current regime began
- **Signal breakdown table**: each input signal with current value, threshold, and contribution to the regime assessment
- **Asset class implications card**: text summary of what the current regime suggests for equities, bonds, crypto, and cash positioning
- **Historical regime timeline**: horizontal bar chart showing regime phases over the last 5 years

### Sub-tab: Global News

- **News feed** (reverse chronological):
  - Each item shows: headline (linked to source), source name, publication time (relative, e.g., "2h ago"), impact tags (colored badges for asset classes affected), sentiment badge
  - Filter bar: date range picker, sentiment filter, asset class filter, free-text search
  - Pagination: infinite scroll or "Load more" button
- **Impact analysis panel** (right sidebar or expandable section):
  - When a news item is selected, shows: full summary, affected portfolio holdings (by name, with estimated directional impact), affected watchlist items

## Business Rules

1. **Regime classification** uses a weighted composite of PMI, yield curve slope, credit spreads, unemployment rate, and inflation. The algorithm:
   - PMI > 50 AND rising = expansion signal; PMI > 50 AND falling = slowdown signal; PMI < 50 AND falling = recession signal; PMI < 50 AND rising = recovery signal
   - Inverted yield curve (10Y < 2Y) = recession warning
   - Widening credit spreads (>200 bps) = stress signal
   - Rising unemployment (3-month trend > +0.5pp) = recession signal
   - Regime is assigned by majority of weighted signals; confidence is "high" if >70% of signal weight agrees, "medium" if 50-70%, "low" if <50%

2. **Indicator change calculation**: change is computed versus the previous observation at the same frequency (e.g., monthly HICP compared to prior month release, not the prior day).

3. **News relevance scoring**: keyword matching against security tickers, company names, sector labels, and macro terms (ECB, inflation, GDP, etc.). Items scoring below 20 are excluded from the default feed.

4. **News deduplication**: if the same headline appears from multiple sources within 4 hours, only the first source is shown; duplicates are collapsed with a "also reported by" note.

5. **Yield curve data**: sourced from ECB Statistical Data Warehouse (EU government bond yields). When a specific maturity is unavailable (e.g., no 30Y Finnish government bond), the nearest eurozone aggregate is used.

## Edge Cases

1. **Missing indicator data**: if a scheduled indicator has not been updated beyond 2x its expected interval, the card shows a staleness warning badge with the last known value and "as of {date}" label.
2. **Yield curve inversion**: when 10Y yield < 2Y yield, the yield curve chart highlights the inverted segment in red and shows an "INVERTED" badge on the slope indicator.
3. **Regime transition**: when the regime changes, the previous regime is logged with its start and end dates. A transition notification is generated as an alert (see [F10 — Alerts](./F10-alerts-rebalancing.md)).
4. **News API downtime**: if the news feed source is unavailable, the Global News tab shows cached items with a "News feed temporarily unavailable — showing cached results" banner.
5. **ECB rate decision days**: on days when the ECB announces a rate decision, the ECB rate card should display a "Decision Day" badge and auto-refresh more frequently (every 5 minutes instead of the normal daily schedule).
6. **Negative yields**: the yield curve chart must handle negative yield values (possible in EU sovereign bonds). Y-axis range must accommodate negative numbers.
7. **Indicator revisions**: some macro indicators are revised after initial publication (e.g., GDP). The pipeline upserts by `(indicator_code, date)`, so revised values overwrite the original. No revision history is kept.

## Acceptance Criteria

1. All five key indicators (ECB rate, HICP, Finland GDP, PMI, unemployment) display current values with change from previous observation and sparkline.
2. Yield curve chart renders current EU government bond curve at all five maturities with at least one historical comparison curve.
3. Regime indicator correctly classifies the current phase based on the weighted signal algorithm and displays confidence level.
4. Global news feed loads with pagination, supports filtering by sentiment and asset class, and shows impact tags per item.
5. Staleness badges appear on any indicator card whose data is older than 2x the expected refresh interval.
6. Clicking an indicator card opens a historical time-series chart with configurable date range.
7. All timestamps display in `Europe/Helsinki` timezone per spec conventions.
8. News items link to the original source URL and open in a new tab.

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
