# Alpha Vantage Adapter

Backup price source, primary forex rate provider, and technical indicator engine for the Bloomvalley terminal. Alpha Vantage provides a structured REST API with free-tier access, but the free plan is severely limited at 25 API calls per day. This adapter is used strategically: primarily for forex rates and as a fallback when Yahoo Finance fails for price data.

**Status: DRAFT**

## Dependencies

- [Pipeline Framework](./pipeline-framework.md) — base adapter interface, scheduling, error handling
- [Data Model](../01-system/data-model.md) — target table schemas (`prices`, `fx_rates`)
- [Yahoo Finance Adapter](./yahoo-finance.md) — primary price source; this adapter serves as backup
- [Architecture](../01-system/architecture.md) — environment variables, Redis caching
- [Spec Conventions](../00-meta/spec-conventions.md) — naming, monetary format, date format

---

## Source Description

Alpha Vantage (https://www.alphavantage.co) provides a well-documented REST API for stock prices, forex rates, and technical indicators. The free tier is limited to 25 API calls per day, which requires careful call budgeting across all pipeline jobs.

### What This Adapter Provides

| Data Category | Refresh Frequency | Target Tables | Priority |
|---------------|-------------------|---------------|----------|
| Forex rates (EUR/USD, EUR/GBP, etc.) | Daily | `fx_rates` | Primary use |
| Daily stock/ETF prices | On-demand (Yahoo fallback only) | `prices` | Backup only |
| Technical indicators (SMA, EMA, RSI, MACD) | Weekly | Redis cache | Secondary |

---

## Authentication

Alpha Vantage requires a free API key obtained by registering at https://www.alphavantage.co/support/#api-key.

| Environment Variable | Required | Description |
|---------------------|----------|-------------|
| `ALPHA_VANTAGE_API_KEY` | Yes | Free-tier API key |

The key is passed as a query parameter on every request: `&apikey={ALPHA_VANTAGE_API_KEY}`.

---

## Rate Limits and Call Budget

| Constraint | Value |
|------------|-------|
| Free tier daily limit | 25 API calls/day |
| Free tier per-minute limit | 5 calls/minute |
| Minimum delay between calls | 12 seconds (to stay under 5/min) |
| Backoff on rate limit (HTTP 429 or error message in JSON) | 60 seconds pause |

### Daily Call Budget Allocation

With only 25 calls/day, every call must be planned.

| Pipeline Job | Calls/Day | Description |
|--------------|-----------|-------------|
| Forex rates | 6 | EUR/USD, EUR/GBP, EUR/SEK, EUR/NOK, EUR/DKK, EUR/CHF |
| Yahoo fallback prices | 0-10 | Only when Yahoo fails; pulled from Redis `av_fallback_tickers` set |
| Technical indicators | 0-9 | Remaining budget; rotate through portfolio holdings |
| **Total** | **6-25** | Never exceed 25 |

The adapter tracks call count in Redis (`av_calls_today` with midnight expiry) and refuses to make calls once the budget is exhausted.

### Schedule

| Pipeline Job | Cron Expression | Description |
|--------------|----------------|-------------|
| `av_forex_rates` | `0 18 * * 1-5` (EET) | Daily at 18:00 — after ECB publishes rates, as backup/supplement |
| `av_fallback_prices` | `0 0 * * *` (EET) | Midnight — process Yahoo fallback tickers |
| `av_technical_indicators` | `0 6 * * 6` | Saturday 06:00 — weekly indicator refresh |

---

## API Endpoints

Base URL: `https://www.alphavantage.co/query`

### Daily Prices

```
GET https://www.alphavantage.co/query
  ?function=TIME_SERIES_DAILY
  &symbol=AAPL
  &outputsize=compact    # last 100 data points; use "full" for 20+ years
  &apikey={key}
```

### Forex Daily Rates

```
GET https://www.alphavantage.co/query
  ?function=FX_DAILY
  &from_symbol=EUR
  &to_symbol=USD
  &outputsize=compact
  &apikey={key}
```

### Technical Indicators

```
# RSI (Relative Strength Index)
GET https://www.alphavantage.co/query
  ?function=RSI
  &symbol=AAPL
  &interval=daily
  &time_period=14
  &series_type=close
  &apikey={key}

# MACD (Moving Average Convergence Divergence)
GET https://www.alphavantage.co/query
  ?function=MACD
  &symbol=AAPL
  &interval=daily
  &series_type=close
  &apikey={key}

# SMA (Simple Moving Average)
GET https://www.alphavantage.co/query
  ?function=SMA
  &symbol=AAPL
  &interval=daily
  &time_period=200
  &series_type=close
  &apikey={key}

# EMA (Exponential Moving Average)
GET https://www.alphavantage.co/query
  ?function=EMA
  &symbol=AAPL
  &interval=daily
  &time_period=50
  &series_type=close
  &apikey={key}
```

---

## Sample API Responses

### TIME_SERIES_DAILY

```json
{
  "Meta Data": {
    "1. Information": "Daily Prices (open, high, low, close) and Volumes",
    "2. Symbol": "AAPL",
    "3. Last Refreshed": "2026-03-18",
    "4. Output Size": "Compact",
    "5. Time Zone": "US/Eastern"
  },
  "Time Series (Daily)": {
    "2026-03-18": {
      "1. open": "172.5000",
      "2. high": "174.3200",
      "3. low": "171.8000",
      "4. close": "173.9500",
      "5. volume": "42000000"
    },
    "2026-03-17": {
      "1. open": "171.2000",
      "2. high": "173.0000",
      "3. low": "170.5000",
      "4. close": "172.5000",
      "5. volume": "38500000"
    }
  }
}
```

### FX_DAILY

```json
{
  "Meta Data": {
    "1. Information": "Forex Daily Prices (open, high, low, close)",
    "2. From Symbol": "EUR",
    "3. To Symbol": "USD",
    "4. Last Refreshed": "2026-03-18",
    "5. Time Zone": "US/Eastern"
  },
  "Time Series FX (Daily)": {
    "2026-03-18": {
      "1. open": "1.08520",
      "2. high": "1.09100",
      "3. low": "1.08300",
      "4. close": "1.08950"
    },
    "2026-03-17": {
      "1. open": "1.08100",
      "2. high": "1.08600",
      "3. low": "1.07800",
      "4. close": "1.08520"
    }
  }
}
```

### RSI

```json
{
  "Meta Data": {
    "1: Symbol": "AAPL",
    "2: Indicator": "Relative Strength Index (RSI)",
    "3: Last Refreshed": "2026-03-18",
    "4: Interval": "daily",
    "5: Time Period": 14,
    "6: Series Type": "close",
    "7: Time Zone": "US/Eastern"
  },
  "Technical Analysis: RSI": {
    "2026-03-18": { "RSI": "55.4321" },
    "2026-03-17": { "RSI": "52.1234" }
  }
}
```

---

## Data Mapping

### Prices: `TIME_SERIES_DAILY` to `prices` table

| API Field | Database Column | Type | Transformation |
|-----------|-----------------|------|----------------|
| Dict key (date string) | `prices.date` | `DATE` | Parse `YYYY-MM-DD` string |
| `1. open` | `prices.open_cents` | `BIGINT` | `round(float(value) * 100)` |
| `2. high` | `prices.high_cents` | `BIGINT` | `round(float(value) * 100)` |
| `3. low` | `prices.low_cents` | `BIGINT` | `round(float(value) * 100)` |
| `4. close` | `prices.close_cents` | `BIGINT` | `round(float(value) * 100)` |
| `5. volume` | `prices.volume` | `BIGINT` | `int(value)` |
| (constant) | `prices.source` | `ENUM` | `'alpha_vantage'` |
| (looked up) | `prices.security_id` | `BIGINT` | Resolve from symbol via `securities` |
| (from security) | `prices.currency` | `CHAR(3)` | From `securities.currency` |

**Note:** Alpha Vantage does not provide adjusted close. `prices.adjusted_close_cents` is left NULL when source is `alpha_vantage`.

### Forex: `FX_DAILY` to `fx_rates` table

| API Field | Database Column | Type | Transformation |
|-----------|-----------------|------|----------------|
| Dict key (date string) | `fx_rates.date` | `DATE` | Parse `YYYY-MM-DD` |
| `4. close` | `fx_rates.rate` | `NUMERIC(12,6)` | `Decimal(value)` — use close rate as the day's rate |
| (constant) | `fx_rates.base_currency` | `CHAR(3)` | `'EUR'` (always, per data model) |
| From `Meta Data` | `fx_rates.quote_currency` | `CHAR(3)` | `to_symbol` from the request |
| (constant) | `fx_rates.source` | `ENUM` | `'alpha_vantage'` |

**Important:** The `fx_rates` table requires `base_currency = 'EUR'`. All AV forex requests use `from_symbol=EUR`. The rate represents "1 EUR = X quote_currency."

### Forex Pairs to Fetch

| Pair | Purpose |
|------|---------|
| EUR/USD | US stocks and ETFs |
| EUR/GBP | UK-listed securities |
| EUR/SEK | Swedish securities (Nordic) |
| EUR/NOK | Norwegian securities (Nordic) |
| EUR/DKK | Danish securities (Nordic) |
| EUR/CHF | Swiss securities |

### Technical Indicators: API to Redis Cache

Technical indicators are stored in Redis, not in a database table, because they are derived data that can be recomputed from prices.

| Indicator | Redis Key Pattern | Value | TTL |
|-----------|-------------------|-------|-----|
| RSI (14-day) | `ta:{security_id}:rsi_14` | JSON: `{"value": 55.43, "date": "2026-03-18"}` | 7 days |
| MACD | `ta:{security_id}:macd` | JSON: `{"macd": 1.23, "signal": 0.98, "histogram": 0.25, "date": "2026-03-18"}` | 7 days |
| SMA-50 | `ta:{security_id}:sma_50` | JSON: `{"value": 168.50, "date": "2026-03-18"}` | 7 days |
| SMA-200 | `ta:{security_id}:sma_200` | JSON: `{"value": 162.30, "date": "2026-03-18"}` | 7 days |
| EMA-50 | `ta:{security_id}:ema_50` | JSON: `{"value": 169.10, "date": "2026-03-18"}` | 7 days |

---

## Validation Rules

1. **Rate limit check**: Before every API call, check `av_calls_today` in Redis. If >= 25, skip and log.
2. **Error message in JSON**: Alpha Vantage returns errors as JSON with a `"Note"` or `"Error Message"` key instead of HTTP error codes. Always check for these keys before parsing data.
3. **Empty time series**: If the time series dict is empty, treat as "no data available" — do not overwrite existing data.
4. **Price sanity**: Same OHLC validation as Yahoo adapter — `high >= low`, etc.
5. **FX rate range**: EUR/USD should be 0.5-2.0; EUR/GBP should be 0.5-1.5. Log and reject values outside a reasonable range per pair.
6. **Numeric parsing**: All values come as strings. Parse with `Decimal` for FX rates, `float` then `round()` for prices.
7. **Date format**: Always `YYYY-MM-DD`. Reject any other format.

---

## Error Scenarios and Handling

| Scenario | Detection | Response |
|----------|-----------|----------|
| Daily limit exceeded | `"Note"` key in JSON: "Thank you for using Alpha Vantage..." | Stop all AV calls for the day. Log warning. Mark pipeline as `'partial'`. |
| Invalid API key | `"Error Message"` key in JSON | Log critical error. Mark pipeline as `'failed'`. Alert operator. |
| Network timeout | `requests.Timeout` after 30s | Retry once after 60s. If still failing, skip and mark `'failed'`. |
| Symbol not found | Empty time series in response | Log warning. Skip ticker. |
| Rate limit per-minute | 5+ calls within 60 seconds | Built-in 12-second delay between calls prevents this. If hit, pause 60 seconds. |
| API response format change | Missing expected keys | Log full response. Mark pipeline as `'failed'`. |

---

## Edge Cases

1. **Call budget exhaustion**: If Yahoo fallback tickers consume all remaining calls after forex, technical indicators are skipped for the day. Forex rates always have priority.
2. **Duplicate sources in `prices`**: A security might have both Yahoo and AV price rows for the same date. The `prices` table has a unique index on `(security_id, date)`. AV data only upserts if Yahoo data is missing (check before inserting).
3. **Weekend forex data**: FX markets close Friday evening and reopen Sunday evening. The adapter only runs Mon-Fri. Weekend dates should not appear in responses.
4. **Alpha Vantage ticker format**: AV uses different ticker formats than Yahoo. Helsinki stocks may need the `.HEL` suffix, Frankfurt uses `.FRA`. The adapter maintains a mapping dict from `securities.exchange` (MIC code) to AV suffix.
5. **Premium tier upgrade**: If the project later upgrades to a paid AV plan (75-1200 calls/day), the call budget logic in Redis simply needs the limit updated. The adapter architecture supports this.
6. **FX rate for EUR/EUR**: Not needed (always 1.0). The adapter does not fetch this pair.
7. **Technical indicators require history**: RSI needs at least 14 data points. SMA-200 needs 200. If a security is new with insufficient price history, the indicator call returns empty data — handle gracefully.

---

## Open Questions

- Should we upgrade to the Alpha Vantage premium tier ($49.99/month for 75 calls/day) if forex rate coverage becomes insufficient?
- Should technical indicators be computed locally from stored prices (using `pandas_ta` or `ta-lib`) instead of consuming AV API calls?

---

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
