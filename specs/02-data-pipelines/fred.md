# FRED Adapter

Federal Reserve Economic Data (FRED) adapter for the Bloomvalley terminal. Provides macroeconomic indicators including interest rates, inflation metrics, GDP, unemployment, yield curves, and manufacturing indices. These data series feed the Macro Dashboard and inform the Macro Strategist's regime assessment.

**Status: DRAFT**

## Dependencies

- [Pipeline Framework](./pipeline-framework.md) — base adapter interface, scheduling, error handling
- [Data Model](../01-system/data-model.md) — target table schema (`macro_indicators`)
- [Architecture](../01-system/architecture.md) — environment variables, Redis caching
- [Spec Conventions](../00-meta/spec-conventions.md) — naming, date format

---

## Source Description

FRED (https://fred.stlouisfed.org) is maintained by the Federal Reserve Bank of St. Louis and offers over 800,000 economic time series. It has a well-documented REST API and a Python client library (`fredapi`). The free tier is generous at 120 requests per minute, making it one of the most reliable data sources in the pipeline.

### What This Adapter Provides

| Data Category | Series Count | Refresh Frequency | Target Table |
|---------------|-------------|-------------------|--------------|
| US interest rates | 4 | Daily | `macro_indicators` |
| US Treasury yields | 5 | Daily | `macro_indicators` |
| Yield curve spread | 1 | Daily | `macro_indicators` |
| Inflation metrics | 3 | Monthly | `macro_indicators` |
| GDP | 2 | Quarterly | `macro_indicators` |
| Labor market | 2 | Monthly | `macro_indicators` |
| Manufacturing / sentiment | 2 | Monthly | `macro_indicators` |
| Credit / financial conditions | 2 | Weekly/Daily | `macro_indicators` |

---

## Authentication

FRED requires a free API key obtained by registering at https://fred.stlouisfed.org/docs/api/api_key.html.

| Environment Variable | Required | Description |
|---------------------|----------|-------------|
| `FRED_API_KEY` | Yes | Free FRED API key |

---

## Library and Installation

```
pip install fredapi>=0.5.2
```

The adapter uses the `fredapi` Python library, which provides a clean wrapper around the FRED REST API.

---

## Rate Limits and Scheduling

| Constraint | Value |
|------------|-------|
| Free tier rate limit | 120 requests/minute |
| Daily limit | None (unlimited) |
| Minimum delay between calls | None needed (generous limits) |
| Backoff on error | Exponential: 1s, 2s, 4s (max 3 retries) |

### Schedule

| Pipeline Job | Cron Expression | Description |
|--------------|----------------|-------------|
| `fred_daily_rates` | `0 22 * * 1-5` (EET) | Daily at 22:00 — after FRED publishes daily series |
| `fred_monthly_indicators` | `0 3 15 * *` | 15th of month 03:00 — most monthly series are published by mid-month |
| `fred_quarterly_gdp` | `0 3 1 1,4,7,10 *` | 1st of Jan/Apr/Jul/Oct — quarterly GDP releases |

---

## FRED Series Catalog

### Interest Rates

| Series ID | Name | Frequency | Unit | Description |
|-----------|------|-----------|------|-------------|
| `FEDFUNDS` | Federal Funds Effective Rate | Daily | percent | Overnight interbank lending rate |
| `DFEDTARU` | Fed Funds Target Upper | Daily | percent | FOMC target upper bound |
| `DFEDTARL` | Fed Funds Target Lower | Daily | percent | FOMC target lower bound |
| `PRIME` | Bank Prime Loan Rate | Daily | percent | Base rate for consumer loans |

### Treasury Yields

| Series ID | Name | Frequency | Unit | Description |
|-----------|------|-----------|------|-------------|
| `DGS1` | 1-Year Treasury Yield | Daily | percent | Short-term yield benchmark |
| `DGS2` | 2-Year Treasury Yield | Daily | percent | Rate-sensitive benchmark |
| `DGS5` | 5-Year Treasury Yield | Daily | percent | Medium-term benchmark |
| `DGS10` | 10-Year Treasury Yield | Daily | percent | Long-term benchmark, mortgage reference |
| `DGS30` | 30-Year Treasury Yield | Daily | percent | Long bond yield |

### Yield Curve

| Series ID | Name | Frequency | Unit | Description |
|-----------|------|-----------|------|-------------|
| `T10Y2Y` | 10-Year minus 2-Year Spread | Daily | percent | Yield curve slope; negative = inverted (recession signal) |

### Inflation

| Series ID | Name | Frequency | Unit | Description |
|-----------|------|-----------|------|-------------|
| `CPIAUCSL` | Consumer Price Index (All Urban) | Monthly | index (1982-84=100) | Headline CPI |
| `CPILFESL` | CPI Less Food and Energy | Monthly | index | Core CPI |
| `PCEPI` | Personal Consumption Expenditures Price Index | Monthly | index (2017=100) | Fed's preferred inflation gauge |

### GDP

| Series ID | Name | Frequency | Unit | Description |
|-----------|------|-----------|------|-------------|
| `GDP` | Gross Domestic Product | Quarterly | billions USD | Nominal GDP |
| `GDPC1` | Real Gross Domestic Product | Quarterly | billions (chained 2017 USD) | Real (inflation-adjusted) GDP |

### Labor Market

| Series ID | Name | Frequency | Unit | Description |
|-----------|------|-----------|------|-------------|
| `UNRATE` | Unemployment Rate | Monthly | percent | Civilian unemployment rate |
| `PAYEMS` | Total Nonfarm Payrolls | Monthly | thousands | Monthly jobs report |

### Manufacturing and Sentiment

| Series ID | Name | Frequency | Unit | Description |
|-----------|------|-----------|------|-------------|
| `MANEMP` | Manufacturing Employment | Monthly | thousands | Manufacturing sector jobs |
| `UMCSENT` | Univ of Michigan Consumer Sentiment | Monthly | index (1966=100) | Consumer confidence proxy |

### Credit and Financial Conditions

| Series ID | Name | Frequency | Unit | Description |
|-----------|------|-----------|------|-------------|
| `BAMLH0A0HYM2` | ICE BofA US High Yield Spread | Daily | percent | Credit spread (risk appetite indicator) |
| `NFCI` | Chicago Fed National Financial Conditions Index | Weekly | index | Financial stress; positive = tighter than average |

---

## Sample Code

### Using fredapi

```python
from fredapi import Fred
import os

fred = Fred(api_key=os.environ["FRED_API_KEY"])

# Fetch a single series (returns pandas Series)
dgs10 = fred.get_series("DGS10", observation_start="2026-01-01")
# Date
# 2026-01-02    4.25
# 2026-01-03    4.28
# 2026-01-06    4.31
# ...
# Name: DGS10, dtype: float64

# Fetch series info (metadata)
info = fred.get_series_info("DGS10")
# Returns a pandas Series with keys like:
# id                            DGS10
# title       10-Year Treasury Constant Maturity Rate
# frequency                     Daily
# units                         Percent
# seasonal_adjustment    Not Seasonally Adjusted
# ...
```

### Sample FRED REST API Response

```
GET https://api.stlouisfed.org/fred/series/observations
  ?series_id=DGS10
  &api_key={key}
  &file_type=json
  &observation_start=2026-03-01
```

```json
{
  "realtime_start": "2026-03-19",
  "realtime_end": "2026-03-19",
  "observation_start": "2026-03-01",
  "observation_end": "9999-12-31",
  "units": "lin",
  "output_type": 1,
  "file_type": "json",
  "order_by": "observation_date",
  "sort_order": "asc",
  "count": 13,
  "offset": 0,
  "limit": 100000,
  "observations": [
    {
      "realtime_start": "2026-03-19",
      "realtime_end": "2026-03-19",
      "date": "2026-03-02",
      "value": "4.25"
    },
    {
      "realtime_start": "2026-03-19",
      "realtime_end": "2026-03-19",
      "date": "2026-03-03",
      "value": "4.28"
    }
  ]
}
```

---

## Data Mapping

### All Series to `macro_indicators` table

Every FRED series maps to the same table with a consistent pattern.

| Source Field | Database Column | Type | Transformation |
|-------------|-----------------|------|----------------|
| Series ID (e.g., `DGS10`) | `macro_indicators.indicator_code` | `VARCHAR(50)` | Direct string — use FRED series ID as the indicator code |
| `date` / Series index | `macro_indicators.date` | `DATE` | Parse from `YYYY-MM-DD` string or pandas Timestamp |
| `value` / Series value | `macro_indicators.value` | `NUMERIC(18,6)` | `Decimal(value)` — preserve full precision |
| (from catalog) | `macro_indicators.unit` | `VARCHAR(20)` | Map from series catalog (see below) |
| (constant) | `macro_indicators.source` | `ENUM` | `'fred'` |

### Unit Mapping

| FRED Unit | `macro_indicators.unit` value |
|-----------|------------------------------|
| Percent | `'percent'` |
| Index (any base year) | `'index'` |
| Billions of Dollars | `'billions_usd'` |
| Billions of Chained Dollars | `'billions_usd'` |
| Thousands of Persons | `'thousands'` |

---

## Validation Rules

1. **Missing value marker**: FRED uses the string `"."` to indicate missing observations (e.g., holidays). Skip these rows — do not insert NULL or zero.
2. **Value range by series**:
   - Interest rates (`FEDFUNDS`, `DGS*`, `PRIME`): must be between -2.0 and 25.0 percent. Negative rates are valid (happened in Europe).
   - `T10Y2Y` spread: must be between -5.0 and 5.0 percent.
   - `UNRATE`: must be between 0.0 and 30.0 percent.
   - CPI/PCEPI indices: must be > 0.
   - GDP: must be > 0.
3. **Monotonic date check**: Observations should be in chronological order. If not, sort before inserting.
4. **Duplicate handling**: Upsert on `(indicator_code, date)` unique index. FRED sometimes revises historical values — always overwrite with latest.
5. **Decimal precision**: Store all values as `NUMERIC(18,6)`. Do not truncate or round.
6. **Stale data detection**: If a daily series has no new observation for 5+ business days, log a warning (possible FRED publication delay or series discontinuation).

---

## Error Scenarios and Handling

| Scenario | Detection | Response |
|----------|-----------|----------|
| Invalid API key | HTTP 400 with error message | Log critical. Mark pipeline `'failed'`. Alert operator. |
| Series discontinued | Empty response or no new observations for 30+ days | Log warning. Keep fetching but flag for review. |
| Network timeout | `requests.Timeout` after 30s | Retry with backoff (1s, 2s, 4s). Max 3 retries. |
| Rate limit (120/min) | HTTP 429 | Pause 60 seconds. Resume. Very unlikely with our call volume. |
| FRED maintenance window | HTTP 503 | Retry after 5 minutes. Max 3 retries. |
| Value = `"."` (missing) | String check before parsing | Skip observation. Log at DEBUG level. |
| Value is non-numeric | `ValueError` on `Decimal(value)` | Log warning. Skip observation. |
| Revised data (backdated updates) | FRED silently updates historical values | The `observation_start` parameter fetches recent data. For full revision capture, run a monthly full-history refresh for critical series. |

---

## Sample Adapter Logic

```python
from fredapi import Fred
from decimal import Decimal
from datetime import date, timedelta

SERIES_CATALOG = {
    "FEDFUNDS": {"unit": "percent", "frequency": "daily"},
    "DGS10":    {"unit": "percent", "frequency": "daily"},
    "DGS2":     {"unit": "percent", "frequency": "daily"},
    "DGS5":     {"unit": "percent", "frequency": "daily"},
    "DGS30":    {"unit": "percent", "frequency": "daily"},
    "DGS1":     {"unit": "percent", "frequency": "daily"},
    "T10Y2Y":   {"unit": "percent", "frequency": "daily"},
    "CPIAUCSL": {"unit": "index",   "frequency": "monthly"},
    "CPILFESL": {"unit": "index",   "frequency": "monthly"},
    "PCEPI":    {"unit": "index",   "frequency": "monthly"},
    "GDP":      {"unit": "billions_usd", "frequency": "quarterly"},
    "GDPC1":    {"unit": "billions_usd", "frequency": "quarterly"},
    "UNRATE":   {"unit": "percent", "frequency": "monthly"},
    "PAYEMS":   {"unit": "thousands", "frequency": "monthly"},
    "MANEMP":   {"unit": "thousands", "frequency": "monthly"},
    "UMCSENT":  {"unit": "index",   "frequency": "monthly"},
    "BAMLH0A0HYM2": {"unit": "percent", "frequency": "daily"},
    "NFCI":     {"unit": "index",   "frequency": "weekly"},
}

async def fetch_fred_series(series_id: str, lookback_days: int = 30):
    fred = Fred(api_key=settings.FRED_API_KEY)
    start = date.today() - timedelta(days=lookback_days)
    data = fred.get_series(series_id, observation_start=start)

    rows = []
    for obs_date, value in data.items():
        if value is None or str(value).strip() == ".":
            continue
        rows.append({
            "indicator_code": series_id,
            "date": obs_date.date() if hasattr(obs_date, 'date') else obs_date,
            "value": Decimal(str(value)),
            "unit": SERIES_CATALOG[series_id]["unit"],
            "source": "fred",
        })
    return rows
```

---

## Edge Cases

1. **FRED holiday schedule**: FRED does not publish on US federal holidays. Daily series will have gaps on these dates. Do not forward-fill — leave as-is.
2. **Revised GDP data**: GDP is released in three estimates (advance, second, third). FRED updates the same series ID with revisions. The adapter should overwrite (upsert) to capture the latest estimate.
3. **Seasonal adjustment**: Some series come in both seasonally adjusted (SA) and not seasonally adjusted (NSA) variants. The catalog above uses SA where available (e.g., `CPIAUCSL` is SA, `DGS10` is NSA because rates are not seasonally adjusted).
4. **Negative interest rates**: While uncommon for US rates, the schema supports negative values. The validation range (-2.0 to 25.0) accommodates this.
5. **Monthly series timing**: CPI is typically released mid-month for the prior month. The adapter runs on the 15th to capture it, but the observation date in FRED will be the 1st of the prior month (e.g., March CPI observation is dated `2026-02-01`).
6. **T10Y2Y inversion**: A negative `T10Y2Y` value signals yield curve inversion — a historically reliable recession predictor. The Macro Dashboard highlights this condition. No special adapter handling needed; the negative value is stored as-is.
7. **Series discontinuation**: FRED occasionally discontinues series and replaces them with new IDs. Monitor for empty responses over 30+ days and check the FRED website for replacements.
8. **Backfill on first run**: On initial deployment, fetch full history (`outputsize=full` equivalent) for all series to populate historical charts. Subsequent runs fetch only the last 30 days.
9. **FRED real-time vs. vintage data**: By default, `fredapi` fetches the latest vintage (most recent revision). For reproducibility, the `realtime_start`/`realtime_end` parameters could fetch point-in-time data, but this is not needed for the terminal.

---

## Open Questions

- Should we add Finland-specific macro series? FRED has some international data (e.g., `FINNGDP` for Finland GDP). Alternatively, these come from Statistics Finland / OECD.
- Should we compute derived indicators (e.g., CPI year-over-year change) at ingestion time and store them, or compute on the fly in the API layer?

---

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
