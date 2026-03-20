# F16 — Recommendation Tracker & Retrospective

Manages a structured recommendation list with buy/sell/hold ratings, target prices, and confidence levels, combined with rigorous retrospective analysis of past recommendations. Answers the questions: "What should I buy/sell? How accurate have my past recommendations been?" Drives continuous improvement of the investment process by objectively measuring recommendation outcomes against benchmarks and identifying systematic biases.

**Status: DRAFT**

## Dependencies

- [Data Model](../01-system/data-model.md) — `securities`, `prices` tables for current/historical prices
- [API Overview](../01-system/api-overview.md) — endpoint conventions, response envelope, pagination
- [Spec Conventions](../00-meta/spec-conventions.md) — date format, monetary values in cents, naming rules
- `../02-data-pipelines/yahoo-finance.md` — price data for target tracking and outcome measurement

## Data Requirements

### New Enum Types

```sql
CREATE TYPE recommendations_action_enum AS ENUM (
    'buy',
    'sell',
    'hold'
);

CREATE TYPE recommendations_confidence_enum AS ENUM (
    'high',
    'medium',
    'low'
);

CREATE TYPE recommendations_status_enum AS ENUM (
    'active',
    'target_hit',
    'stopped_out',
    'time_expired',
    'manually_closed'
);

CREATE TYPE recommendations_time_horizon_enum AS ENUM (
    '1m',       -- 1 month
    '3m',       -- 3 months
    '6m',       -- 6 months
    '1y',       -- 1 year
    '2y',       -- 2 years
    '5y'        -- 5 years
);
```

### New Tables

#### `recommendations`

```sql
CREATE TABLE recommendations (
    id                      BIGSERIAL       PRIMARY KEY,
    security_id             BIGINT          NOT NULL REFERENCES securities(id),
    action                  recommendations_action_enum NOT NULL,
    confidence              recommendations_confidence_enum NOT NULL,
    time_horizon            recommendations_time_horizon_enum NOT NULL,
    target_price_cents      BIGINT          NOT NULL,       -- target price per share
    stop_loss_cents         BIGINT,                         -- optional stop-loss price
    entry_price_cents       BIGINT          NOT NULL,       -- price at time of recommendation
    currency                CHAR(3)         NOT NULL,
    bull_case               TEXT            NOT NULL,        -- required: why this could go well
    bear_case               TEXT            NOT NULL,        -- required: why this could go wrong
    rationale_summary       VARCHAR(500)    NOT NULL,        -- one-paragraph summary
    key_catalysts           TEXT,                            -- comma-separated or JSON array of expected catalysts
    status                  recommendations_status_enum NOT NULL DEFAULT 'active',
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),
    expires_at              TIMESTAMPTZ     NOT NULL,        -- calculated from created_at + time_horizon
    closed_at               TIMESTAMPTZ,
    close_price_cents       BIGINT,                          -- price at close
    close_reason            VARCHAR(500),                    -- explanation for manual close
    actual_return_percent   NUMERIC(8, 4),                   -- calculated at close
    benchmark_return_percent NUMERIC(8, 4),                  -- benchmark return over same period
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT chk_recommendations_target_positive
        CHECK (target_price_cents > 0),
    CONSTRAINT chk_recommendations_entry_positive
        CHECK (entry_price_cents > 0),
    CONSTRAINT chk_recommendations_bull_case_required
        CHECK (length(trim(bull_case)) > 0),
    CONSTRAINT chk_recommendations_bear_case_required
        CHECK (length(trim(bear_case)) > 0),
    CONSTRAINT chk_recommendations_currency_upper
        CHECK (currency = upper(currency))
);
```

**Indexes:**

```sql
CREATE INDEX idx_recommendations_security_id ON recommendations (security_id);
CREATE INDEX idx_recommendations_status ON recommendations (status);
CREATE INDEX idx_recommendations_created_at ON recommendations (created_at DESC);
CREATE INDEX idx_recommendations_expires_at ON recommendations (expires_at) WHERE status = 'active';
```

#### `recommendation_snapshots`

Weekly price snapshots for active recommendations, used for tracking progress and building the retrospective time-series.

```sql
CREATE TABLE recommendation_snapshots (
    id                  BIGSERIAL       PRIMARY KEY,
    recommendation_id   BIGINT          NOT NULL REFERENCES recommendations(id) ON DELETE CASCADE,
    snapshot_date       DATE            NOT NULL,
    price_cents         BIGINT          NOT NULL,
    distance_to_target_percent  NUMERIC(8, 4),   -- (target - current) / current * 100
    benchmark_value     NUMERIC(12, 4),           -- benchmark index value for alpha calc
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT uq_recommendation_snapshots
        UNIQUE (recommendation_id, snapshot_date)
);
```

**Indexes:**

```sql
CREATE INDEX idx_recommendation_snapshots_recommendation_id ON recommendation_snapshots (recommendation_id);
CREATE INDEX idx_recommendation_snapshots_date ON recommendation_snapshots (snapshot_date DESC);
```

### Data Ingestion

- **Price tracking**: Active recommendations have their security prices checked daily. Weekly snapshots stored in `recommendation_snapshots`.
- **Auto-close check**: Daily job checks if any active recommendation has hit its target price or stop-loss. Also checks for expiration.
- **Benchmark data**: MSCI World, OMXH25, and S&P 500 index values fetched daily for benchmark comparison.
- **Retrospective recalculation**: Runs weekly (Sunday night) to update all aggregate statistics.

## API Endpoints

| Tag | Prefix | Feature |
|-----|--------|---------|
| Recommendations | `/recommendations` | F16 — Recommendation tracking, retrospective |

| Method | Path | Description |
|--------|------|-------------|
| GET | `/recommendations` | List recommendations, paginated. Filters: `status`, `action`, `confidence`, `securityId`, `fromDate`, `toDate`. Sort: `createdAt` desc (default) |
| GET | `/recommendations/{id}` | Recommendation detail with snapshot history |
| POST | `/recommendations` | Create a new recommendation. Body must include `securityId`, `action`, `confidence`, `timeHorizon`, `targetPriceCents`, `currency`, `bullCase`, `bearCase`, `rationaleSummary`. Optional: `stopLossCents`, `keyCatalysts` |
| PUT | `/recommendations/{id}` | Update recommendation (only while `status = 'active'`). Can update target, stop-loss, catalysts, cases |
| POST | `/recommendations/{id}/close` | Manually close a recommendation. Body: `{ closeReason }` |
| POST | `/recommendations/{id}/extend` | Extend time horizon. Body: `{ newTimeHorizon }`. Resets `expiresAt` |
| GET | `/recommendations/retrospective` | Full retrospective analysis with all metrics |
| GET | `/recommendations/retrospective/time-series` | Cumulative alpha time-series for chart rendering |

### Example Responses

**GET `/recommendations?status=active&limit=1`**

```json
{
  "data": [
    {
      "id": 101,
      "securityId": 42,
      "ticker": "NESTE",
      "name": "Neste Oyj",
      "action": "buy",
      "confidence": "high",
      "timeHorizon": "1y",
      "targetPrice": { "amount": 4500, "currency": "EUR" },
      "stopLoss": { "amount": 3200, "currency": "EUR" },
      "entryPrice": { "amount": 3650, "currency": "EUR" },
      "currentPrice": { "amount": 3800, "currency": "EUR" },
      "distanceToTarget": 18.42,
      "rationaleSummary": "Neste's renewable diesel capacity expansion positions it for strong growth as EU mandates increase biofuel blending requirements.",
      "bullCase": "EU biofuel mandates drive volume growth; SAF demand accelerates; margin expansion from Singapore refinery optimization.",
      "bearCase": "Feedstock cost inflation compresses margins; competitor capacity additions; regulatory risk if EU weakens mandates.",
      "keyCatalysts": ["Q2 earnings (margin guidance)", "EU RED III implementation timeline", "Singapore refinery ramp-up"],
      "status": "active",
      "createdAt": "2026-01-15T10:00:00Z",
      "expiresAt": "2027-01-15T10:00:00Z"
    }
  ],
  "meta": { "timestamp": "2026-03-19T10:00:00Z", "cacheAge": 300, "stale": false },
  "pagination": { "total": 8, "limit": 1, "offset": 0, "hasMore": true }
}
```

**GET `/recommendations/retrospective`**

```json
{
  "data": {
    "totalRecommendations": 45,
    "closedRecommendations": 32,
    "activeRecommendations": 13,
    "isStatisticallyMeaningful": true,
    "hitRate": 62.5,
    "averageReturn": 12.3,
    "benchmarkAverageReturn": 8.7,
    "alpha": 3.6,
    "averageHoldingPeriodDays": 187,
    "confidenceCalibration": {
      "high": { "count": 12, "hitRate": 75.0, "avgReturn": 18.2 },
      "medium": { "count": 14, "hitRate": 57.1, "avgReturn": 10.1 },
      "low": { "count": 6, "hitRate": 50.0, "avgReturn": 5.8 }
    },
    "byAction": {
      "buy": { "count": 25, "hitRate": 64.0, "avgReturn": 14.1 },
      "sell": { "count": 5, "hitRate": 60.0, "avgReturn": 8.2 },
      "hold": { "count": 2, "hitRate": 50.0, "avgReturn": 6.0 }
    },
    "bySector": [
      { "sector": "Energy", "count": 8, "hitRate": 75.0, "avgReturn": 16.5 },
      { "sector": "Technology", "count": 10, "hitRate": 50.0, "avgReturn": 9.2 }
    ],
    "byGeography": [
      { "country": "FI", "count": 12, "hitRate": 66.7, "avgReturn": 13.5 },
      { "country": "US", "count": 15, "hitRate": 60.0, "avgReturn": 11.8 }
    ],
    "bestCalls": [
      { "id": 23, "ticker": "NVDA", "action": "buy", "returnPercent": 45.2, "holdingDays": 120 }
    ],
    "worstCalls": [
      { "id": 37, "ticker": "INTC", "action": "buy", "returnPercent": -22.1, "holdingDays": 180 }
    ],
    "biasAnalysis": [
      { "bias": "Overconfidence in tech sector — high confidence calls in tech underperform other sectors by 8%", "severity": "medium" },
      { "bias": "Time horizon too short — 3-month calls have 40% hit rate vs 70% for 1-year calls", "severity": "high" }
    ],
    "benchmarks": {
      "msciWorld": { "returnOverPeriod": 8.7 },
      "omxh25": { "returnOverPeriod": 6.2 },
      "sp500": { "returnOverPeriod": 10.1 }
    },
    "lastCalculated": "2026-03-16T03:00:00Z"
  },
  "meta": { "timestamp": "2026-03-19T10:00:00Z", "cacheAge": 259200, "stale": false }
}
```

## UI Views

### Active Recommendations Table

Primary view showing all open recommendations:

| Column | Description |
|--------|-------------|
| Security | Ticker + name |
| Action | BUY (green) / SELL (red) / HOLD (gray) badge |
| Target Price | Target price per share |
| Current Price | Live price (updates via SSE) |
| Distance to Target | % remaining to target (color: green if >0 for buy, red if <0) |
| Confidence | High / Medium / Low badge (gold / silver / bronze) |
| Time Horizon | Duration label |
| Expires | Date or "in X days" |
| Created | Date recommendation was made |
| Rationale | Truncated summary (expandable) |

- Sortable by any column; default sort by created date descending
- Row click expands to show full bull/bear case and catalysts
- Action buttons on each row: Edit, Close, Extend

### Create / Edit Recommendation Form

Modal or full-page form with the following fields:

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| Security | Searchable dropdown | Yes | Must exist in securities catalog |
| Action | Radio: BUY / SELL / HOLD | Yes | |
| Target Price | Number input (in security currency) | Yes | Must be positive |
| Stop Loss | Number input | No | If provided, must be < target for BUY, > target for SELL |
| Time Horizon | Dropdown: 1M / 3M / 6M / 1Y / 2Y / 5Y | Yes | |
| Confidence | Radio: High / Medium / Low | Yes | |
| Rationale Summary | Text area (max 500 chars) | Yes | Min 20 characters |
| Bull Case | Text area | Yes | Min 50 characters — enforced, cannot be empty |
| Bear Case | Text area | Yes | Min 50 characters — enforced, cannot be empty |
| Key Catalysts | Tag input (add multiple) | No | |

- Current price auto-populated and shown for reference
- Distance to target auto-calculated and shown
- Expiration date auto-calculated from time horizon

### Closed Recommendations

Table of past recommendations with outcomes:

| Column | Description |
|--------|-------------|
| Security | Ticker + name |
| Action | BUY / SELL / HOLD |
| Entry Price | Price when recommended |
| Close Price | Price when closed |
| Target Price | Original target |
| Actual Return | % return achieved |
| Benchmark Return | Benchmark % over same period |
| Alpha | Actual - Benchmark |
| Outcome | Target Hit / Stopped Out / Time Expired / Manually Closed (colored badge) |
| Holding Period | Days held |
| Confidence | Original confidence level |

- Sortable; filterable by outcome, action, confidence, date range
- Summary row: average return, hit rate, average alpha

### Retrospective Dashboard

The core analytical view. Only shown when `closedRecommendations >= 20` (statistically meaningful threshold). Below threshold, show a progress bar: "15/20 closed recommendations needed for retrospective analysis."

**Sections:**

1. **Key Metrics Row** (MetricCard components):
   - Hit Rate: % of recommendations that reached target
   - Average Return vs. Benchmark (alpha)
   - Average Holding Period
   - Total Recommendations (active / closed)

2. **Confidence Calibration Chart**:
   - Grouped bar chart: for each confidence level (High/Medium/Low), show the actual hit rate
   - Ideal: High confidence should have highest hit rate. If not, flag as a calibration issue
   - Additional line showing average return per confidence level

3. **Best and Worst Calls**:
   - Top 5 best calls (highest return)
   - Top 5 worst calls (lowest return)
   - Each showing security, action, return, holding period

4. **Sector / Geography Breakdown**:
   - Two tables showing hit rate and average return by sector and by country
   - Highlight sectors/geographies where performance significantly differs from average

5. **Cumulative Alpha Time-Series Chart**:
   - Line chart showing cumulative recommendation alpha over time
   - X-axis: date, Y-axis: cumulative % alpha over benchmark
   - Benchmark line at 0% for reference
   - Uses data from `recommendation_snapshots`

6. **Improvement Suggestions / Bias Analysis**:
   - Auto-generated observations based on the data:
     - "Your 3-month horizon calls have a 40% hit rate vs. 70% for 1-year calls — consider longer time horizons"
     - "High confidence calls in Technology have underperformed — possible sector overconfidence"
     - "Sell recommendations have higher hit rate than buy — consider more contrarian calls"
   - These are rule-based pattern detections, not AI-generated (v1)

7. **Benchmark Comparison**:
   - Bar chart comparing average recommendation return against MSCI World, OMXH25, S&P 500

## Business Rules

1. **Bull and bear case mandatory**: Every recommendation MUST have both a bull case and a bear case. The database enforces non-empty strings. The UI enforces minimum 50 characters each. This is a core Munger principle: always consider what could go wrong.

2. **Auto-expiration**: A daily job checks all active recommendations where `expires_at <= now()`. These are auto-closed with `status = 'time_expired'`, `close_price_cents` set to the current price, and `actual_return_percent` calculated.

3. **Target price hit detection**: A daily job checks if the current price has reached or exceeded the target price (for BUY: price >= target; for SELL: price <= target). If hit, auto-close with `status = 'target_hit'`.

4. **Stop-loss hit detection**: If `stop_loss_cents` is set, a daily job checks if the price has breached the stop-loss (for BUY: price <= stop_loss; for SELL: price >= stop_loss). If hit, auto-close with `status = 'stopped_out'`.

5. **Extension**: Active recommendations can be extended to a longer time horizon via the extend endpoint. This resets `expires_at` based on the new horizon from the current date. The original `created_at` is preserved.

6. **Retrospective threshold**: Retrospective analysis requires a minimum of 20 closed recommendations to be statistically meaningful. Below this threshold, the retrospective dashboard shows a progress indicator but no analytics.

7. **Retrospective recalculation**: The full retrospective is recalculated weekly (Sunday 03:00 Helsinki time). Results are cached. The `lastCalculated` timestamp is shown in the UI.

8. **Benchmark tracking**: Each recommendation tracks returns against three benchmarks:
   - MSCI World (global, primary benchmark)
   - OMXH25 (Finnish market)
   - S&P 500 (US market)

   The benchmark return is calculated over the exact same holding period as the recommendation.

9. **Bias analysis rules** (v1, rule-based):
   - If hit rate for a confidence level is lower than the level below it (e.g., "high" < "medium"), flag as "Confidence miscalibration"
   - If average holding period for a time horizon is <50% of the horizon, flag as "Premature closing"
   - If any sector has >10 closed recommendations and hit rate differs from overall by >15 percentage points, flag as "Sector bias"
   - If buy recommendations consistently underperform sell recommendations, flag as "Possible bullish bias"

10. **No editing closed recommendations**: Once a recommendation is closed (any terminal status), it cannot be edited. This preserves the integrity of the retrospective analysis.

## Edge Cases

1. **Security delisted**: If a held security is delisted while a recommendation is active, manually close the recommendation with the last available price and note the delisting as the close reason.
2. **Stock split during active recommendation**: Target price and entry price must be adjusted for splits. The daily check job detects corporate actions and adjusts `target_price_cents`, `stop_loss_cents`, and `entry_price_cents` proportionally.
3. **Currency fluctuation**: Recommendations are tracked in the security's native currency. Benchmark comparison is also in native currency (or local benchmark). FX effects are noted but not mixed into the return calculation.
4. **Target and stop-loss hit on same day**: If both target and stop-loss are breached intraday (gap move), use the closing price to determine which was hit. If close is at or above target (for BUY), mark as target hit; otherwise, stopped out.
5. **Duplicate recommendation**: The system allows multiple active recommendations for the same security (e.g., different time horizons or re-evaluation). Each is tracked independently.
6. **Recommendation with HOLD action**: HOLD recommendations have a target price representing the price at which the action would change (e.g., "hold unless it drops below X"). Hit rate for HOLD is measured as: did the price stay within the expected range for the time horizon?
7. **Insufficient price data**: If price data is unavailable for the auto-close check (e.g., data pipeline failure), the check is skipped and retried the next day. No recommendation is closed without a valid price.
8. **Retrospective with mixed currencies**: Recommendations in different currencies are aggregated by converting returns to percentages (not absolute amounts), making cross-currency comparison valid.

## Acceptance Criteria

1. Creating a recommendation requires both bull case and bear case (cannot submit with either empty or <50 chars).
2. Active recommendations table shows current price, distance to target, and expiration with live updates.
3. Recommendations auto-close when target price is hit, stop-loss is breached, or time horizon expires.
4. Closed recommendations show actual return, benchmark return, and alpha.
5. Retrospective dashboard appears only after 20+ closed recommendations.
6. Hit rate, average return, and confidence calibration are calculated correctly.
7. Bias analysis identifies at least the four rule-based patterns defined in business rules.
8. Cumulative alpha time-series chart renders correctly from snapshot data.
9. Recommendations can be extended but not edited after closure.
10. Stock splits correctly adjust target, stop-loss, and entry prices.
11. All monetary values follow the cents convention with currency codes.
12. Weekly recalculation updates the retrospective without manual intervention.

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
