# Yahoo Finance Adapter

Primary data source for the Warren Cashett terminal. Provides daily OHLCV prices, company fundamentals, dividend history, ESG scores, and sector/industry classification for stocks and ETFs. Uses the `yfinance` Python library, which wraps Yahoo Finance's unofficial API endpoints.

**Status: DRAFT**

## Dependencies

- [Pipeline Framework](./pipeline-framework.md) — base adapter interface, scheduling, error handling
- [Data Model](../01-system/data-model.md) — target table schemas (`prices`, `securities`, `dividends`, `esg_scores`)
- [Architecture](../01-system/architecture.md) — system topology, Redis caching, environment variables
- [Spec Conventions](../00-meta/spec-conventions.md) — naming, monetary format, date format

---

## Source Description

Yahoo Finance is the most comprehensive free data source available for stock and ETF market data. The `yfinance` library (https://github.com/ranaroussi/yfinance) provides a Pythonic wrapper around Yahoo's undocumented API. Because it is unofficial, the API can change without notice and may throttle or block excessive requests. Treat this source as best-effort with graceful degradation to Alpha Vantage as a backup for price data.

### What This Adapter Provides

| Data Category | Refresh Frequency | Target Tables |
|---------------|-------------------|---------------|
| Daily OHLCV prices | Every 15 min during market hours; daily close stored permanently | `prices` |
| Company fundamentals | Weekly | `securities` (metadata columns) |
| Dividend history | Weekly | `dividends` |
| ESG scores (Sustainalytics) | Monthly | `esg_scores` |
| Sector/industry classification | Weekly | `securities.sector`, `securities.industry` |

---

## Authentication

No authentication required. `yfinance` uses publicly accessible Yahoo Finance endpoints.

**Environment variables:** None specific to this adapter.

---

## Library and Installation

```
pip install yfinance>=0.2.36
```

The adapter uses `yfinance` exclusively. No direct HTTP calls to Yahoo endpoints are needed.

---

## Rate Limits and Scheduling

Yahoo Finance has no published rate limits, but aggressive scraping leads to IP-based throttling (HTTP 429 or silent data gaps).

| Constraint | Value |
|------------|-------|
| Recommended max requests per day | ~2,000 |
| Max concurrent requests | 5 |
| Minimum delay between requests | 200ms |
| Backoff on 429 / connection error | Exponential: 1s, 2s, 4s, 8s, 16s (max 3 retries) |
| Cool-down after repeated failures | 5 minutes pause, then resume |

### Schedule

| Pipeline Job | Cron Expression | Description |
|--------------|----------------|-------------|
| `yahoo_daily_prices` | `*/15 9-18 * * 1-5` (EET) | Every 15 min during European market hours, Mon-Fri |
| `yahoo_daily_close` | `0 23 * * 1-5` (EET) | Store final daily close after US market close |
| `yahoo_fundamentals` | `0 3 * * 6` | Saturday 03:00 — weekly fundamentals refresh |
| `yahoo_dividends` | `0 4 * * 6` | Saturday 04:00 — weekly dividend history refresh |
| `yahoo_esg` | `0 5 1 * *` | 1st of month 05:00 — monthly ESG refresh |

---

## API Endpoints Used (via yfinance)

The `yfinance` library calls these Yahoo endpoints internally. Listed for transparency and debugging.

| yfinance Method | Yahoo Endpoint | Data |
|----------------|----------------|------|
| `Ticker.history()` | `query2.finance.yahoo.com/v8/finance/chart/{symbol}` | OHLCV prices |
| `Ticker.info` | `query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}` | Fundamentals, metadata |
| `Ticker.dividends` | Included in `history()` with `actions=True` | Dividend amounts and dates |
| `Ticker.sustainability` | `query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}?modules=esgScores` | ESG scores |
| `download()` (batch) | Same chart endpoint, batched | Bulk price download |

---

## Sample Code

### Fetching Daily Prices

```python
import yfinance as yf
from datetime import date, timedelta

ticker = yf.Ticker("AAPL")
hist = ticker.history(period="5d", auto_adjust=False)

# hist is a pandas DataFrame:
#                  Open       High        Low      Close  Adj Close    Volume  Dividends  Stock Splits
# Date
# 2026-03-13  171.000000  173.500000  170.250000  172.750000  172.750000  45000000        0.0           0.0
# 2026-03-14  172.800000  174.100000  171.500000  173.200000  173.200000  38000000        0.0           0.0
```

### Fetching Fundamentals

```python
ticker = yf.Ticker("AAPL")
info = ticker.info

# info is a dict with keys like:
# {
#   "shortName": "Apple Inc.",
#   "sector": "Technology",
#   "industry": "Consumer Electronics",
#   "country": "United States",
#   "currency": "USD",
#   "exchange": "NMS",
#   "trailingPE": 28.5,
#   "priceToBook": 45.2,
#   "returnOnEquity": 1.456,
#   "returnOnAssets": 0.287,
#   "marketCap": 2800000000000,
#   "totalRevenue": 385000000000,
#   "netIncomeToCommon": 97000000000,
#   "freeCashflow": 112000000000,
#   "dividendYield": 0.0055,
#   "trailingAnnualDividendRate": 0.96,
#   ...
# }
```

### Fetching Dividend History

```python
ticker = yf.Ticker("AAPL")
dividends = ticker.dividends

# dividends is a pandas Series:
# Date
# 2025-02-07    0.25
# 2025-05-09    0.25
# 2025-08-08    0.26
# 2025-11-07    0.26
# Name: Dividends, dtype: float64
```

### Fetching ESG Scores

```python
ticker = yf.Ticker("AAPL")
esg = ticker.sustainability

# esg is a pandas DataFrame (transposed) or None if unavailable:
# Value
# totalEsg                         17.0
# environmentScore                  0.5
# socialScore                       8.1
# governanceScore                   8.4
# controversyLevel                  3
# ...
```

### Batch Price Download

```python
import yfinance as yf

# Download multiple tickers at once (more efficient)
data = yf.download(
    tickers=["AAPL", "MSFT", "VWCE.DE"],
    period="5d",
    auto_adjust=False,
    threads=False,  # sequential to avoid rate limits
)
```

---

## Data Mapping

### Prices: `yfinance history()` to `prices` table

| yfinance Field | Database Column | Type | Transformation |
|---------------|-----------------|------|----------------|
| DataFrame index (`Date`) | `prices.date` | `DATE` | Convert pandas Timestamp to `date`; strip timezone |
| `Open` | `prices.open_cents` | `BIGINT` | `round(value * 100)` — convert dollars to cents |
| `High` | `prices.high_cents` | `BIGINT` | `round(value * 100)` |
| `Low` | `prices.low_cents` | `BIGINT` | `round(value * 100)` |
| `Close` | `prices.close_cents` | `BIGINT` | `round(value * 100)` |
| `Adj Close` | `prices.adjusted_close_cents` | `BIGINT` | `round(value * 100)` |
| `Volume` | `prices.volume` | `BIGINT` | Direct integer |
| (looked up from security) | `prices.currency` | `CHAR(3)` | From `securities.currency` |
| (constant) | `prices.source` | `ENUM` | Always `'yahoo_finance'` |
| (resolved from ticker) | `prices.security_id` | `BIGINT` | Look up via `securities.ticker` + `securities.exchange` |

### Fundamentals: `yfinance info` to `securities` table

| yfinance Field | Database Column | Transformation |
|---------------|-----------------|----------------|
| `shortName` | `securities.name` | Direct string, truncate to 255 chars |
| `sector` | `securities.sector` | Direct string (GICS sector) |
| `industry` | `securities.industry` | Direct string (GICS industry) |
| `country` | `securities.country` | Map full name to ISO 3166-1 alpha-2 (e.g., "United States" to "US") |
| `currency` | `securities.currency` | Direct string, uppercase |
| `exchange` | `securities.exchange` | Map Yahoo exchange code to MIC (e.g., "NMS" to "XNAS") |

### Fundamentals: `yfinance info` to application-layer cache (Redis or computed on demand)

These values are not stored in a database table but are cached in Redis for the screener and portfolio views.

| yfinance Field | Redis Key Pattern | Unit | Notes |
|---------------|-------------------|------|-------|
| `trailingPE` | `fundamentals:{security_id}:pe_ratio` | ratio | Trailing P/E |
| `forwardPE` | `fundamentals:{security_id}:forward_pe` | ratio | Forward P/E |
| `priceToBook` | `fundamentals:{security_id}:pb_ratio` | ratio | Price-to-Book |
| `returnOnEquity` | `fundamentals:{security_id}:roe` | decimal (1.0 = 100%) | Multiply by 100 for display |
| `returnOnAssets` | `fundamentals:{security_id}:roa` | decimal | Multiply by 100 for display |
| `marketCap` | `fundamentals:{security_id}:market_cap_cents` | cents | `round(value * 100)` |
| `totalRevenue` | `fundamentals:{security_id}:revenue_cents` | cents | `round(value * 100)` |
| `netIncomeToCommon` | `fundamentals:{security_id}:net_income_cents` | cents | `round(value * 100)` |
| `freeCashflow` | `fundamentals:{security_id}:fcf_cents` | cents | `round(value * 100)` |
| `dividendYield` | `fundamentals:{security_id}:dividend_yield` | decimal | Multiply by 100 for display |
| `debtToEquity` | `fundamentals:{security_id}:debt_to_equity` | ratio | Direct |
| `earningsGrowth` | `fundamentals:{security_id}:earnings_growth` | decimal | YoY earnings growth |
| `revenueGrowth` | `fundamentals:{security_id}:revenue_growth` | decimal | YoY revenue growth |

**Redis TTL**: 7 days (refreshed weekly). Set `fundamentals:{security_id}:updated_at` to the fetch timestamp.

### Dividends: `yfinance dividends` to `dividends` table

| yfinance Field | Database Column | Transformation |
|---------------|-----------------|----------------|
| Series index (`Date`) | `dividends.ex_date` | Convert pandas Timestamp to `date` |
| Series value | `dividends.amount_per_share_cents` | `round(value * 100)` |
| (from security) | `dividends.amount_currency` | From `securities.currency` |
| (calculated) | `dividends.gross_amount_cents` | `amount_per_share_cents * shares_held` — requires looking up held quantity on record date |

**Note:** yfinance dividend data only provides ex-dates and per-share amounts. Pay dates and record dates must be sourced separately or left NULL. The `dividends` table row is only created if the security is held in an account.

### ESG: `yfinance sustainability` to `esg_scores` table

| yfinance Field | Database Column | Transformation |
|---------------|-----------------|----------------|
| `totalEsg` | `esg_scores.total_score` | Direct numeric |
| `environmentScore` | `esg_scores.environment_score` | Direct numeric |
| `socialScore` | `esg_scores.social_score` | Direct numeric |
| `governanceScore` | `esg_scores.governance_score` | Direct numeric |
| `controversyLevel` | `esg_scores.controversy_level` | Map: 0-1 = `'none'`, 2 = `'low'`, 3 = `'moderate'`, 4 = `'significant'`, 5 = `'severe'` |
| (today) | `esg_scores.as_of_date` | Current date |
| (constant) | `esg_scores.source` | `'yahoo_finance'` |

---

## Yahoo Exchange Code to MIC Mapping

| Yahoo Code | MIC | Exchange Name |
|-----------|-----|---------------|
| `NMS` | `XNAS` | NASDAQ |
| `NYQ` | `XNYS` | NYSE |
| `GER` | `XFRA` | Frankfurt |
| `HEL` | `XHEL` | Helsinki (Nasdaq Helsinki) |
| `LSE` | `XLON` | London |
| `PAR` | `XPAR` | Paris (Euronext) |
| `AMS` | `XAMS` | Amsterdam (Euronext) |
| `STO` | `XSTO` | Stockholm |
| `CPH` | `XCSE` | Copenhagen |

Country name to ISO 3166-1 alpha-2 mapping is handled by a lookup dict in `app/utils/countries.py`.

---

## Validation Rules

1. **Price sanity**: `high_cents >= low_cents`, `high_cents >= open_cents`, `high_cents >= close_cents`, `low_cents <= open_cents`, `low_cents <= close_cents`. Reject row if violated.
2. **Price range**: If `close_cents` differs from previous day's close by more than 50%, log a warning (possible split not yet processed, or bad data). Do not reject — store but flag.
3. **Volume non-negative**: `volume >= 0`. Set to NULL if yfinance returns negative or NaN.
4. **Currency mismatch**: If `info['currency']` differs from `securities.currency`, log a warning and do not overwrite. Investigate manually.
5. **Null handling**: yfinance returns `None` or `NaN` for missing fields. Map to `NULL` in the database. Never store `NaN` or the string `"None"`.
6. **Duplicate dates**: Upsert (`ON CONFLICT ... DO UPDATE`) on `(security_id, date)` — always overwrite with latest fetch.
7. **ESG score range**: All scores must be 0-100. If outside range, log and discard.
8. **Fundamentals staleness**: If `info` returns an empty dict or all-None values, skip the update and keep existing data.

---

## Error Scenarios and Handling

| Scenario | Detection | Response |
|----------|-----------|----------|
| Yahoo rate limit (HTTP 429) | `yfinance` raises exception or returns empty DataFrame | Exponential backoff: 1s, 2s, 4s, 8s, 16s. Max 3 retries per ticker. After 3 failures, skip ticker and continue. |
| Ticker not found / delisted | `info` returns minimal data, `history()` returns empty DataFrame | Log warning. If previously active, mark `securities.is_active = FALSE`. |
| Network timeout | `requests.ConnectionError` or `requests.Timeout` | Retry with backoff. After 3 failures, mark pipeline run as `'failed'`. |
| Yahoo API endpoint changes | Unexpected response format, `KeyError` on expected fields | Log error with full response. Continue with other tickers. Pipeline status = `'partial'`. |
| NaN / missing data in response | `pd.isna()` checks on each field | Map to `NULL`. If `close_cents` is NaN, skip entire row (close is required). |
| Stock split not reflected in `history()` | Price jumps >50% day-over-day | Log warning. Check `corporate_actions` table for pending splits. |
| yfinance library update breaks API | Import errors, changed method signatures | Pin `yfinance` version in `pyproject.toml`. Test on upgrade before deploying. |

### Fallback to Alpha Vantage

If Yahoo fails for **price data** (3 consecutive retries exhausted for a given ticker), the adapter queues the ticker for the Alpha Vantage adapter's next run. This is implemented via a Redis set:

```python
# In yahoo_finance adapter, on persistent failure:
redis.sadd("av_fallback_tickers", ticker_symbol)

# In alpha_vantage adapter, before its own run:
fallback_tickers = redis.smembers("av_fallback_tickers")
# Fetch prices for these tickers (subject to AV rate limits)
redis.delete("av_fallback_tickers")
```

Fallback applies only to prices. Fundamentals, dividends, and ESG have no backup source.

---

## Edge Cases

1. **Market holidays**: Yahoo returns no data for holidays. The adapter must not create rows with zero or carried-forward prices. Simply skip dates with no data.
2. **European tickers with suffix**: Helsinki-listed stocks use `.HE` suffix (e.g., `NOKIA.HE`), Frankfurt uses `.DE` (e.g., `VWCE.DE`). The `securities.ticker` column stores the base ticker; the adapter appends the suffix based on `securities.exchange`.
3. **Split-adjusted vs. unadjusted prices**: Use `auto_adjust=False` to get both raw and adjusted prices. Store both (`close_cents` and `adjusted_close_cents`). Tax lot cost basis calculations use unadjusted prices.
4. **Weekend/after-hours fetches**: yfinance returns the last trading day's data. Ensure the adapter does not create duplicate rows — upsert handles this.
5. **Multi-listed securities**: A security like Nokia trades on XHEL (EUR) and XNYS (USD). These are separate `securities` rows with different currencies. Fetch each independently.
6. **Crypto tickers on Yahoo**: Yahoo supports crypto (e.g., `BTC-USD`). However, CoinGecko is the primary crypto source. Yahoo crypto data is only used as a fallback.
7. **ETF dividend data**: Accumulating (ACC) ETFs report no dividends. Distributing (DIST) ETFs report dividends. The adapter must handle both gracefully.
8. **Penny stocks / sub-cent prices**: Some securities trade below $0.01. The cents conversion `round(value * 100)` would round to 0. For prices below 1 cent, store as 1 cent minimum and log a warning.
9. **Currency conversion**: Yahoo reports prices in the security's native currency. No FX conversion happens in this adapter — FX conversion occurs at portfolio valuation time using `fx_rates`.
10. **yfinance caching**: yfinance has internal caching. Disable it for production: `yf.set_tz_cache_location(None)` or set a temporary directory.

---

## Open Questions

- Should we store fundamentals in a dedicated `fundamentals` table instead of Redis? This would preserve historical snapshots of P/E, ROE, etc.
- Should we track Yahoo's adjusted close separately for total return calculations, or rely on our own split-adjustment logic via `corporate_actions`?

---

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
