# CoinGecko Adapter

Crypto data source for the Warren Cashett terminal. Provides cryptocurrency prices, market capitalization, trading volume, and historical price data via the CoinGecko REST API. Crypto markets operate 24/7/365, so this adapter has different scheduling patterns than the equity-focused adapters.

**Status: DRAFT**

## Dependencies

- [Pipeline Framework](./pipeline-framework.md) — base adapter interface, scheduling, error handling
- [Data Model](../01-system/data-model.md) — target table schemas (`prices`, `securities`)
- [Architecture](../01-system/architecture.md) — environment variables, Redis caching
- [Spec Conventions](../00-meta/spec-conventions.md) — naming, monetary format, date format

---

## Source Description

CoinGecko (https://www.coingecko.com) is the leading independent cryptocurrency data aggregator. Its API covers 10,000+ coins with price data from 600+ exchanges. The free tier (Demo API) provides sufficient access for portfolio-level crypto tracking.

### What This Adapter Provides

| Data Category | Refresh Frequency | Target Tables |
|---------------|-------------------|---------------|
| Current crypto prices (BTC, ETH, etc.) | Every 5 minutes | `prices` + Redis cache |
| Daily OHLCV history | Daily at midnight | `prices` |
| Market data (market cap, 24h volume) | Every 5 minutes | Redis cache |
| Coin metadata (name, symbol, category) | Weekly | `securities` |

---

## Authentication

CoinGecko offers a free Demo API key for higher rate limits. Without a key, rate limits are more restrictive.

| Environment Variable | Required | Description |
|---------------------|----------|-------------|
| `COINGECKO_API_KEY` | No | Demo API key (free registration at https://www.coingecko.com/en/api/pricing) |

**With key:** Use `https://api.coingecko.com/api/v3` with header `x-cg-demo-key: {key}`

**Without key:** Use `https://api.coingecko.com/api/v3` — lower rate limits apply.

---

## Rate Limits and Scheduling

| Constraint | With Demo Key | Without Key |
|------------|---------------|-------------|
| Rate limit | 30 calls/minute | 10-15 calls/minute |
| Monthly limit | 10,000 calls/month | ~500 calls/day |
| Minimum delay between calls | 2 seconds | 6 seconds |
| Backoff on HTTP 429 | 60 seconds | 120 seconds |

### Schedule

| Pipeline Job | Cron Expression | Description |
|--------------|----------------|-------------|
| `cg_current_prices` | `*/5 * * * *` | Every 5 minutes — current prices for held crypto |
| `cg_daily_history` | `5 0 * * *` (UTC) | Daily at 00:05 UTC — store yesterday's daily candle |
| `cg_coin_metadata` | `0 4 * * 6` | Saturday 04:00 — weekly metadata refresh |

---

## API Endpoints

Base URL: `https://api.coingecko.com/api/v3`

### Current Prices (Simple)

```
GET /simple/price
  ?ids=bitcoin,ethereum,solana,cardano
  &vs_currencies=eur,usd
  &include_market_cap=true
  &include_24hr_vol=true
  &include_24hr_change=true
  &include_last_updated_at=true
```

### Historical Prices (Market Chart)

```
GET /coins/{id}/market_chart
  ?vs_currency=eur
  &days=1            # 1 = last 24h (5-min intervals), 30 = daily, 365 = daily
  &interval=daily    # optional: force daily granularity
```

### Daily OHLC

```
GET /coins/{id}/ohlc
  ?vs_currency=eur
  &days=30           # 1, 7, 14, 30, 90, 180, 365, max
```

### Coin Detail (Metadata)

```
GET /coins/{id}
  ?localization=false
  &tickers=false
  &market_data=true
  &community_data=false
  &developer_data=false
```

### Coin List (ID Discovery)

```
GET /coins/list
  ?include_platform=false
```

---

## Sample API Responses

### /simple/price

```json
{
  "bitcoin": {
    "eur": 62500.00,
    "usd": 68000.00,
    "eur_market_cap": 1230000000000,
    "usd_market_cap": 1340000000000,
    "eur_24h_vol": 28000000000,
    "usd_24h_vol": 30500000000,
    "eur_24h_change": -1.25,
    "usd_24h_change": -1.18,
    "last_updated_at": 1742400000
  },
  "ethereum": {
    "eur": 3200.00,
    "usd": 3480.00,
    "eur_market_cap": 385000000000,
    "usd_market_cap": 419000000000,
    "eur_24h_vol": 15000000000,
    "usd_24h_vol": 16300000000,
    "eur_24h_change": 0.85,
    "usd_24h_change": 0.92,
    "last_updated_at": 1742400000
  }
}
```

### /coins/{id}/ohlc

```json
[
  [1742256000000, 63000.00, 63500.00, 62200.00, 62800.00],
  [1742342400000, 62800.00, 63100.00, 61500.00, 62500.00]
]
```

Each array: `[timestamp_ms, open, high, low, close]`

### /coins/{id} (metadata subset)

```json
{
  "id": "bitcoin",
  "symbol": "btc",
  "name": "Bitcoin",
  "categories": ["Cryptocurrency", "Layer 1 (L1)"],
  "description": { "en": "Bitcoin is the first successful..." },
  "market_data": {
    "current_price": { "eur": 62500, "usd": 68000 },
    "market_cap": { "eur": 1230000000000 },
    "total_volume": { "eur": 28000000000 },
    "circulating_supply": 19680000,
    "total_supply": 21000000,
    "max_supply": 21000000,
    "ath": { "eur": 69000, "usd": 73000 },
    "ath_date": { "eur": "2025-11-15T00:00:00.000Z" },
    "atl": { "eur": 51.30 },
    "price_change_percentage_24h": -1.25
  }
}
```

---

## Coin ID Mapping

CoinGecko uses its own `id` system (e.g., `"bitcoin"`, `"ethereum"`). The `securities.coingecko_id` column stores this mapping.

| Ticker | CoinGecko ID | Name |
|--------|-------------|------|
| `BTC` | `bitcoin` | Bitcoin |
| `ETH` | `ethereum` | Ethereum |
| `SOL` | `solana` | Solana |
| `ADA` | `cardano` | Cardano |
| `DOT` | `polkadot` | Polkadot |
| `AVAX` | `avalanche-2` | Avalanche |
| `MATIC` | `matic-network` | Polygon |
| `LINK` | `chainlink` | Chainlink |
| `XRP` | `ripple` | XRP |
| `BNB` | `binancecoin` | BNB |

New coins are added to `securities` with `asset_class = 'crypto'` and the `coingecko_id` populated. The `/coins/list` endpoint can discover new IDs.

---

## Data Mapping

### Current Prices: `/simple/price` to `prices` table + Redis

| API Field | Database Column | Type | Transformation |
|-----------|-----------------|------|----------------|
| (from coin mapping) | `prices.security_id` | `BIGINT` | Look up via `securities.coingecko_id` |
| (today) | `prices.date` | `DATE` | `date.today()` (UTC) |
| `{coin}.eur` | `prices.close_cents` | `BIGINT` | `round(value * 100)` |
| (no intraday OHLC from simple endpoint) | `prices.open_cents` | `BIGINT` | NULL (filled later from OHLC endpoint) |
| (no intraday OHLC from simple endpoint) | `prices.high_cents` | `BIGINT` | NULL |
| (no intraday OHLC from simple endpoint) | `prices.low_cents` | `BIGINT` | NULL |
| `{coin}.eur_24h_vol` | `prices.volume` | `BIGINT` | `round(value)` — volume in EUR |
| (constant) | `prices.currency` | `CHAR(3)` | `'EUR'` |
| (constant) | `prices.source` | `ENUM` | `'coingecko'` |

**Redis cache** (for live dashboard display):

| API Field | Redis Key | Value | TTL |
|-----------|-----------|-------|-----|
| `{coin}.eur` | `price:current:{security_id}` | `{"price_cents": 6250000, "currency": "EUR", "updated_at": "..."}` | 60 seconds |
| `{coin}.eur_market_cap` | `crypto:{security_id}:market_cap_cents` | integer cents | 5 minutes |
| `{coin}.eur_24h_vol` | `crypto:{security_id}:volume_24h_cents` | integer cents | 5 minutes |
| `{coin}.eur_24h_change` | `crypto:{security_id}:change_24h_pct` | decimal | 5 minutes |

### Daily OHLC: `/coins/{id}/ohlc` to `prices` table

| API Field | Database Column | Type | Transformation |
|-----------|-----------------|------|----------------|
| `[0]` (timestamp ms) | `prices.date` | `DATE` | `datetime.utcfromtimestamp(ts/1000).date()` |
| `[1]` (open) | `prices.open_cents` | `BIGINT` | `round(value * 100)` |
| `[2]` (high) | `prices.high_cents` | `BIGINT` | `round(value * 100)` |
| `[3]` (low) | `prices.low_cents` | `BIGINT` | `round(value * 100)` |
| `[4]` (close) | `prices.close_cents` | `BIGINT` | `round(value * 100)` |
| (constant) | `prices.currency` | `CHAR(3)` | `'EUR'` |
| (constant) | `prices.source` | `ENUM` | `'coingecko'` |

### Coin Metadata: `/coins/{id}` to `securities` table

| API Field | Database Column | Transformation |
|-----------|-----------------|----------------|
| `symbol` | `securities.ticker` | Uppercase: `value.upper()` |
| `name` | `securities.name` | Direct string |
| `id` | `securities.coingecko_id` | Direct string |
| (constant) | `securities.asset_class` | `'crypto'` |
| (constant) | `securities.currency` | `'EUR'` (prices stored in EUR) |
| (constant) | `securities.exchange` | NULL (crypto has no exchange in MIC sense) |

---

## Validation Rules

1. **Price positive**: All prices must be > 0. Reject zero or negative prices.
2. **OHLC consistency**: `high >= low`, `high >= open`, `high >= close`, `low <= open`, `low <= close`. Reject row if violated.
3. **Volume non-negative**: Volume must be >= 0.
4. **Timestamp validation**: OHLC timestamps must be within the last 365 days (for `days=365` request). Reject future dates.
5. **Market cap sanity**: BTC market cap should be > $100B. If suspiciously low, log warning.
6. **Null handling**: If any field is null in the API response, map to NULL in the database. Do not store zeros for missing data.
7. **Duplicate date handling**: Upsert on `(security_id, date)`. CoinGecko OHLC may return overlapping dates with the simple price endpoint — the OHLC data (with full candle) takes precedence.
8. **Price precision**: Crypto prices can have many decimal places (e.g., low-cap tokens at $0.00001234). After conversion to cents (`round(value * 100)`), very low prices round to 0. Store a minimum of 1 cent and log a warning for prices below $0.01.

---

## Error Scenarios and Handling

| Scenario | Detection | Response |
|----------|-----------|----------|
| Rate limit (HTTP 429) | HTTP status code 429 | Pause 60s (with key) or 120s (without). Retry. Log warning. |
| Invalid API key | HTTP 401 or 403 | Fall back to keyless mode. Log warning. |
| Coin not found | HTTP 404 on `/coins/{id}` | Log warning. Deactivate coin in securities if 3 consecutive 404s. |
| Network timeout | `httpx.TimeoutException` after 30s | Retry with backoff (2s, 4s, 8s). Max 3 retries. |
| CoinGecko maintenance | HTTP 503 | Retry after 5 minutes. Mark `'failed'` after 3 retries. |
| Empty response | HTTP 200 but empty JSON body or empty array | Skip. Log warning. Use cached data. |
| Price anomaly | Price change > 50% in 5 minutes | Store the data but log a warning. Could be legitimate (crypto is volatile). |
| API deprecation | Changed response format | Log error with full response. Mark `'failed'`. |

---

## Edge Cases

1. **24/7 market**: Crypto trades continuously. Unlike equities, there is no "market close." The daily OHLC candle is based on UTC midnight boundaries. The adapter's `cg_daily_history` job runs at 00:05 UTC to capture the completed UTC-day candle.
2. **Price in EUR vs USD**: CoinGecko supports multi-currency price queries. The adapter fetches prices in EUR (the portfolio's base currency) to avoid an extra FX conversion step. USD prices are also fetched for the Redis cache (some users may want USD reference).
3. **High-precision tokens**: Some tokens trade at fractions of a cent (e.g., SHIB at $0.00001). The cents representation truncates precision. For portfolio positions in such tokens, the quantity column (`NUMERIC(28,18)`) carries the precision. The `price_cents` at 1 cent minimum is acceptable for display; actual value = quantity * exact price (computed from CoinGecko's raw value stored in Redis).
4. **Token renames / migrations**: Crypto projects sometimes rebrand or migrate to new chains. CoinGecko may change the coin ID. The adapter should detect when a previously valid `coingecko_id` returns 404 and alert for manual remapping.
5. **Stablecoin prices**: Stablecoins (USDT, USDC) trade very close to 1.00. Price deviation > 2% from the peg is an anomaly worth flagging.
6. **Multiple chains**: Some tokens exist on multiple blockchains (e.g., USDC on Ethereum, Solana, Polygon). CoinGecko tracks a single aggregated price per coin ID. This is correct for portfolio valuation regardless of which chain the user holds.
7. **CoinGecko rate limit changes**: CoinGecko periodically adjusts rate limits. The adapter reads limits from config, not hardcoded, to allow quick adjustment.
8. **Crypto tax implications**: Every price update does NOT create a taxable event. Only trades (buy/sell/swap) are taxable. The adapter only records market prices for valuation purposes.
9. **Data gaps**: CoinGecko occasionally has brief outages. If the `cg_current_prices` job fails, the Redis cache retains the last price with its TTL. The UI shows the staleness timestamp.

---

## Open Questions

- Should we track DeFi protocol data (TVL, yields) for any DeFi tokens in the portfolio?
- Should we store sub-cent prices at higher precision in a separate column (e.g., `price_micro_cents BIGINT` representing 1/10000 of a cent)?

---

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
