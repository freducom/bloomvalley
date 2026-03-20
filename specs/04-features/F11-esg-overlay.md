# F11 — ESG Overlay

ESG scoring and screening module providing the ESG / Impact Analyst with per-holding scorecards, portfolio-level ESG aggregation, controversy monitoring, EU Taxonomy alignment indicators, and sustainable investment alternatives. This module is informational only — it does not auto-exclude holdings but surfaces ESG data for the Portfolio Manager to weigh in investment decisions.

**Status: DRAFT**

## Dependencies

- [Data Model](../01-system/data-model.md) — `esg_scores` table, `securities` table, `holdings_snapshot`
- [API Overview](../01-system/api-overview.md) — `/esg` endpoint group
- [Spec Conventions](../00-meta/spec-conventions.md) — naming rules, date/time
- F01 — Portfolio Dashboard (holdings data for weighted aggregation)

## Data Requirements

### ESG Score Data

Stored in the `esg_scores` table, refreshed monthly from Yahoo Finance (Sustainalytics data):

| Field | Source | Scale | Description |
|-------|--------|-------|-------------|
| `environment_score` | Sustainalytics via Yahoo Finance | 0-100 | Environmental pillar score |
| `social_score` | Sustainalytics via Yahoo Finance | 0-100 | Social pillar score |
| `governance_score` | Sustainalytics via Yahoo Finance | 0-100 | Governance pillar score |
| `total_score` | Sustainalytics via Yahoo Finance | 0-100 | Combined ESG risk score |
| `controversy_level` | Sustainalytics via Yahoo Finance | enum | none, low, moderate, significant, severe |
| `controversy_details` | Sustainalytics via Yahoo Finance | text | Description of active controversies |
| `eu_taxonomy_aligned` | Fund disclosures / manual | boolean | Whether the security or fund reports EU Taxonomy alignment |
| `sfdr_classification` | Fund disclosures / manual | enum | article_6, article_8, article_9 (for ETFs/funds) |

### Score Interpretation

Sustainalytics ESG Risk Ratings (lower = better):
- 0-10: Negligible risk
- 10-20: Low risk
- 20-30: Medium risk
- 30-40: High risk
- 40+: Severe risk

Note: Sustainalytics uses an inverse scale where lower scores are better (less ESG risk). The UI must clearly communicate this to avoid confusion.

### Controversy Categories

| Category | Examples |
|----------|----------|
| Environmental | Oil spills, deforestation, emissions violations, water pollution |
| Social — Labor | Worker safety incidents, child labor in supply chain, union suppression |
| Social — Community | Land rights disputes, displacement, community health impacts |
| Governance | Accounting fraud, executive misconduct, bribery, tax avoidance schemes |
| Product | Product safety recalls, data privacy breaches, misleading marketing |

### Sustainable Alternatives Data

For each held security, the module identifies ESG-superior alternatives:
- Same asset class and sector
- Total ESG score at least 10 points lower (better) than the current holding
- Total Expense Ratio (TER) within 0.15% of the current holding (for ETFs) or comparable market cap (for stocks)
- Data sourced from justETF (for ETF alternatives) and Yahoo Finance (for stock alternatives)

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/esg/portfolio` | Portfolio-level ESG summary: weighted average scores, controversy count, worst-scoring holdings |
| GET | `/esg/holdings` | Per-holding ESG scores for all current positions |
| GET | `/esg/holdings/{securityId}` | Detailed ESG scorecard for a single security |
| GET | `/esg/controversies` | List of all active controversies across held securities |
| GET | `/esg/alternatives/{securityId}` | Sustainable alternatives for a specific holding |
| GET | `/esg/taxonomy` | EU Taxonomy alignment summary for the portfolio |

### Response: `GET /esg/portfolio`

```json
{
  "data": {
    "portfolioScores": {
      "environment": 24.5,
      "social": 18.3,
      "governance": 15.7,
      "total": 19.8,
      "interpretation": "low_risk"
    },
    "weightingMethod": "market_value_weighted",
    "holdingsWithScores": 42,
    "holdingsWithoutScores": 3,
    "controversySummary": {
      "none": 35,
      "low": 5,
      "moderate": 2,
      "significant": 0,
      "severe": 0
    },
    "worstHoldings": [
      {
        "securityId": 88,
        "ticker": "XOM",
        "name": "Exxon Mobil Corporation",
        "totalScore": 42.1,
        "controversyLevel": "moderate",
        "weight": 2.3
      }
    ],
    "bestHoldings": [
      {
        "securityId": 210,
        "ticker": "VAGF",
        "name": "Vanguard EUR Govt Bond ETF",
        "totalScore": 8.2,
        "controversyLevel": "none",
        "weight": 5.1
      }
    ],
    "taxonomyAligned": {
      "alignedWeight": 12.5,
      "notAlignedWeight": 65.3,
      "noDataWeight": 22.2
    },
    "asOfDate": "2026-03-01"
  }
}
```

### Response: `GET /esg/holdings/{securityId}`

```json
{
  "data": {
    "securityId": 88,
    "ticker": "XOM",
    "name": "Exxon Mobil Corporation",
    "scores": {
      "environment": 48.2,
      "social": 32.1,
      "governance": 28.5,
      "total": 42.1,
      "interpretation": "severe_risk"
    },
    "controversies": [
      {
        "category": "environmental",
        "level": "moderate",
        "description": "Ongoing litigation related to climate change disclosure and greenhouse gas emissions.",
        "since": "2019-06-01"
      }
    ],
    "euTaxonomyAligned": false,
    "sfdrClassification": null,
    "scoreHistory": [
      { "asOfDate": "2026-03-01", "total": 42.1 },
      { "asOfDate": "2026-02-01", "total": 41.8 },
      { "asOfDate": "2026-01-01", "total": 40.5 }
    ],
    "peerComparison": {
      "sectorAverage": 35.2,
      "sectorBest": 18.4,
      "sectorWorst": 52.1,
      "percentileRank": 78
    },
    "alternatives": [
      {
        "securityId": 312,
        "ticker": "IQQH",
        "name": "iShares Global Clean Energy UCITS ETF",
        "totalScore": 15.3,
        "ter": 0.65,
        "assetClass": "etf"
      }
    ],
    "asOfDate": "2026-03-01"
  }
}
```

## UI Views

### Portfolio ESG Summary (top section, visible on all sub-tabs)

- **Aggregate ESG score cards** (row of 4):
  - Environment, Social, Governance, Total
  - Each card: score value, color-coded risk level (green = negligible/low, yellow = medium, orange = high, red = severe), trend arrow vs previous month
  - See component: `MetricCard`
- **Coverage note**: "ESG data available for {N} of {M} holdings ({X}% of portfolio by value)"

### ESG Scorecard per Holding

- **Holdings table** with ESG columns:
  - Columns: Security, Weight (%), E Score, S Score, G Score, Total Score, Risk Level, Controversy, EU Taxonomy
  - Sortable by any column
  - Risk level cell: colored badge (Negligible / Low / Medium / High / Severe)
  - Controversy cell: colored dot (green = none, yellow = low, orange = moderate, red = significant/severe)
  - EU Taxonomy cell: check mark, X mark, or "N/A"
  - Row click opens detailed ESG scorecard (sidebar or modal)
- **Detailed scorecard** (for selected security):
  - Pillar breakdown: horizontal bar chart for E, S, G with sector average overlay
  - Score history: sparkline showing total ESG score over last 12 months
  - Controversy list: each controversy with category, severity, description, and duration
  - Peer comparison: where this security ranks within its sector (percentile)
  - Alternatives list: sustainable replacements with score comparison

### Controversy Monitor

- **Active controversies table**:
  - Columns: Security, Category (icon + label), Severity (colored badge), Description, Since
  - Sorted by severity (severe first)
  - Filter by category and severity
- **Controversy trend**: count of controversies over time (line chart, last 12 months)
- **Empty state**: "No active controversies in your portfolio" (green banner)

### EU Taxonomy & SFDR

- **Taxonomy alignment gauge**: percentage of portfolio (by market value) aligned with EU Taxonomy
- **SFDR classification breakdown** (for ETFs/funds only):
  - Pie chart: Article 6, Article 8, Article 9, Not classified
  - Table listing each fund with its classification
- **Note**: EU Taxonomy data is limited; the module shows "No data" for securities without disclosure and does not penalize them

### Sustainable Alternatives

- Accessed from the per-holding scorecard or as a standalone view
- **Alternatives comparison table** (for a selected holding):
  - Columns: Alternative Security, ESG Total Score, Score Improvement, TER/Cost, Asset Class, Key Difference
  - Score improvement = current holding score minus alternative score (positive = better)
  - Highlight alternatives with >20 point improvement
- **Portfolio-wide scan**: button to scan all holdings and list those with available superior ESG alternatives
  - Shows: current holding, best alternative, score improvement, cost difference
  - Sorted by largest potential ESG improvement

## Business Rules

1. **Weighted average calculation**: portfolio ESG scores are computed as market-value-weighted averages. Only holdings with available ESG data are included; holdings without data are excluded from the weighted average but their weight is reported as "unscored."

2. **Monthly refresh cycle**: ESG scores are refreshed monthly. The `as_of_date` in `esg_scores` determines the data vintage. If the latest score is more than 45 days old, a staleness warning appears.

3. **No auto-exclusion**: this module is informational only. It does not block trades, filter the screener, or modify allocation targets based on ESG criteria. The Portfolio Manager retains full discretion.

4. **Controversy escalation**: if a holding's controversy level changes from a lower to a higher severity, a notification is generated and queued in the alert feed (see [F10 — Alerts](./F10-alerts-rebalancing.md)).

5. **Alternative matching criteria**:
   - Same broad asset class (stock for stock, ETF for ETF)
   - Same sector or sub-sector (GICS level 2 match)
   - ESG total score improvement of at least 10 points
   - For ETFs: TER difference within 0.15%
   - For stocks: market cap within the same category (mega, large, mid, small)
   - Must be available on exchanges accessible from Finland (EU-listed or US-listed)

6. **ETF ESG scoring**: for ETFs, the ESG score represents the fund-level aggregate (not the underlying holdings). If fund-level ESG data is unavailable, the module reports "N/A" rather than attempting to compute from holdings.

7. **Peer comparison**: sector average, best, and worst ESG scores are computed from all securities in the `securities` table within the same `sector` that have ESG data. If fewer than 5 peers exist, the comparison section is hidden.

## Edge Cases

1. **No ESG data available**: if Yahoo Finance returns no Sustainalytics data for a security (common for small-cap, non-US, and crypto), the holding appears in the table with "N/A" in all ESG columns and is excluded from portfolio aggregation.
2. **Crypto holdings**: cryptocurrencies do not have ESG scores from Sustainalytics. They are permanently "N/A" with a note "ESG ratings not available for cryptocurrency assets."
3. **ESG score improves above threshold**: if a previously "severe risk" holding improves to "moderate" or below, the controversy monitor notes the improvement but does not auto-remove the flag until the next refresh cycle confirms the change.
4. **All holdings unscored**: if no holdings have ESG data, the portfolio summary shows "Insufficient ESG data — add holdings with ESG coverage to enable portfolio scoring."
5. **Bond ESG scores**: individual bonds rarely have ESG scores. The module reports "N/A" for individual bonds but may have data for bond ETFs. Government bonds are assumed "low risk" for governance but marked "N/A" if no formal score exists.
6. **Duplicate alternatives**: if the same ETF is suggested as an alternative for multiple holdings, it appears in each holding's alternatives list independently.
7. **Score scale confusion**: since Sustainalytics uses an inverse scale (lower = better), the UI explicitly labels scores with "Lower is better" and uses green for low scores and red for high scores — the opposite of intuitive expectations.
8. **EU Taxonomy data gaps**: EU Taxonomy alignment is only disclosed by EU-regulated funds and certain large companies. For most securities, this field is NULL. The module shows "No data" without penalizing the holding.

## Acceptance Criteria

1. Portfolio-level ESG summary displays weighted average E, S, G, and Total scores with correct risk level interpretation.
2. Per-holding ESG scorecard shows all three pillar scores, total score, controversy level, and EU Taxonomy status.
3. Holdings table is sortable by any ESG column and color-codes risk levels correctly.
4. Controversy monitor lists all active controversies across the portfolio, sorted by severity.
5. Sustainable alternatives are suggested for holdings where a qualifying alternative exists (same sector, 10+ point improvement, similar cost).
6. ESG scores correctly use the inverse Sustainalytics scale with "Lower is better" labeling throughout the UI.
7. Holdings without ESG data display "N/A" and are excluded from portfolio weighted averages, with their unscored weight reported.
8. Monthly staleness warning appears when ESG data is older than 45 days.
9. EU Taxonomy alignment percentage is calculated based on market value weight of aligned holdings.
10. SFDR classification breakdown displays for ETF/fund holdings with available classification data.

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
