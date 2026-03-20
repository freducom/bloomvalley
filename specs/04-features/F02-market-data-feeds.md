# F02 — Market Data Feeds

**Status: DRAFT**

The live price data backbone of the terminal. This feature provides real-time (or near-real-time) market data to every other feature that displays prices, and gives the user visibility into whether the data feeding the terminal is fresh and healthy. It answers: "Are my prices current, which markets are open, and is the data pipeline working?"

## Dependencies

- Specs: [data-model](../01-system/data-model.md), [api-overview](../01-system/api-overview.md), [architecture](../01-system/architecture.md), [spec-conventions](../00-meta/spec-conventions.md), [pipeline-framework](../02-data-pipelines/pipeline-framework.md), [yahoo-finance](../02-data-pipelines/yahoo-finance.md), [alpha-vantage](../02-data-pipelines/alpha-vantage.md), [coingecko](../02-data-pipelines/coingecko.md), [ecb](../02-data-pipelines/ecb.md), [design-system](../05-ui/design-system.md)
- Data: Yahoo Finance price pipeline, Alpha Vantage price pipeline, CoinGecko crypto pipeline, ECB FX rates pipeline — all must be configured and running
- API: `GET /prices/stream` (SSE), `GET /prices/current`, `GET /prices/{securityId}`, `GET /pipelines`

## Data Requirements

### Tables Read

| Table | Purpose |
|-------|---------|
| `prices` | Historical and latest close prices for all securities |
| `fx_rates` | Latest FX rates, data freshness |
| `securities` | Security metadata (ticker, name, exchange, currency) for display |
| `pipeline_runs` | Pipeline status, last run timestamps, error messages |
| `watchlist_items` | Securities to include in the live price stream (held + watchlisted) |
| `holdings_snapshot` | Current positions to determine which securities need live prices |

### Tables Written

None directly by the UI feature. The data pipelines write to `prices`, `fx_rates`, and `pipeline_runs`.

### Calculations Invoked

None. This feature displays raw price data and pipeline health; no derived calculations.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/prices/stream` | SSE endpoint streaming live price updates for held and watchlisted securities. Events: `price` (price update), `status` (market status change), `heartbeat` (keepalive every 30s) |
| GET | `/prices/current` | Current prices for all held securities. Returns price, day change, change %, timestamp, staleness flag per security |
| GET | `/prices/{securityId}` | Historical OHLCV prices for a single security. Supports `?fromDate`, `?toDate`, `?interval` (daily only for now) |
| GET | `/pipelines` | List all pipelines with last run status, timestamp, duration, rows affected, and error message if failed |
| POST | `/pipelines/{name}/run` | Manually trigger a pipeline run (used from the pipeline health panel) |

See [api-overview](../01-system/api-overview.md) for full request/response schemas and SSE event format.

## UI Views

### Market Data Page (`/market`)

**Top bar — Market status indicators:**

A horizontal row of market status badges, one per tracked exchange:

| Exchange | Label | Timezone |
|----------|-------|----------|
| NYSE | `NYSE` | ET (UTC-5/UTC-4) |
| NASDAQ | `NASDAQ` | ET (UTC-5/UTC-4) |
| OMX Helsinki | `XHEL` | EET (UTC+2/UTC+3) |
| OMX Stockholm | `XSTO` | CET (UTC+1/UTC+2) |

Each badge displays:
- Exchange name
- Status: `OPEN` (green dot), `CLOSED` (gray dot), `PRE-MARKET` (yellow dot), `POST-MARKET` (yellow dot)
- Local time at the exchange
- Next open/close time

Crypto markets always show `24/7` with a green dot.

**Main section — Price ticker table (DataTable):**

A table showing live prices for all held and watchlisted securities, sorted by most recently updated.

| Column | Type | Description |
|--------|------|-------------|
| Security | ticker + name | Ticker in monospace, name in secondary text |
| Exchange | badge | MIC code with market status dot |
| Last Price | currency | Latest price in native currency |
| Day Change | currency + % | Change from previous close, gain/loss colored |
| Bid / Ask | currency pair | If available from data source |
| Volume | number | Today's trading volume |
| Last Updated | relative time | "2 min ago", "15 min ago", etc. |
| Source | badge | `Yahoo`, `Alpha Vantage`, `CoinGecko` |
| Freshness | status dot | Green (< 5 min), yellow (5-30 min), red (> 30 min) |

**Interactions:**
- Click a row to navigate to the security's chart page (F08)
- Filter by: exchange, asset class, held/watchlisted
- Sort by any column
- Prices flash briefly (200ms background highlight) when updated via SSE

**Right sidebar — Data freshness panel:**

A compact panel showing per-source data freshness:

| Source | Last Updated | Status | Rows |
|--------|-------------|--------|------|
| Yahoo Finance | 2 min ago | OK | 156 |
| Alpha Vantage | 1 hour ago | OK | 12 |
| CoinGecko | 4 min ago | OK | 8 |
| ECB FX Rates | 6 hours ago | OK | 32 |

Each row shows the last successful pipeline run. Status is `OK` (green), `STALE` (yellow, > 2x scheduled interval), or `FAILED` (red, last run failed). Clicking a source expands to show last 5 pipeline runs with timestamps, durations, and error messages.

A "Refresh All" button triggers all pipeline runs manually. Individual "Run Now" buttons per source for targeted refresh.

### Status Bar Integration (global)

The bottom status bar of the terminal (visible on every page) includes a compact market data section:

- **Pipeline health dot**: Green if all pipelines are healthy, yellow if any are stale, red if any have failed
- **Last price update**: "Prices: 2 min ago" — timestamp of the most recent price event from SSE
- **Market status mini-badges**: Compact colored dots for each tracked exchange (hover to see full status)

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `m` | Navigate to Market Data page |
| `R` (Shift+R) | Trigger refresh all pipelines |
| `f` | Toggle freshness panel open/close |

## Business Rules

1. **SSE connection management**: The frontend opens a single SSE connection to `/prices/stream` on app load. The connection streams updates only for securities in the user's portfolio (open positions) plus all securities on active watchlists. The connection auto-reconnects with exponential backoff on failure, sending the `Last-Event-ID` header to resume from the last received event.

2. **Price staleness thresholds**: Freshness is determined by `meta.cacheAge` in the API response and by the per-source scheduled interval from the pipeline framework:

   | Source | Scheduled Interval | Stale Threshold (2x) |
   |--------|-------------------|---------------------|
   | Yahoo Finance | 15 min (market hours) | 30 min |
   | Alpha Vantage | Daily | 48 hours |
   | CoinGecko | 5 min | 10 min |
   | ECB FX Rates | Daily | 48 hours |

3. **Market status determination**: Exchange status is computed from market calendars, not from incoming data. The backend maintains market calendar data (holidays, half-days) for each tracked exchange. Status transitions: `PRE-MARKET` (30 min before open) -> `OPEN` -> `POST-MARKET` (until data feeds stop) -> `CLOSED`.

4. **Price source priority**: When multiple sources provide prices for the same security, priority order is: Yahoo Finance > Alpha Vantage > manual entry. The source displayed in the table is the one that provided the latest price.

5. **FX rate freshness**: ECB publishes reference rates around 16:00 CET on business days. Weekends and holidays use the last available rate. The freshness badge for ECB shows `OK` even on weekends if the Friday rate is present.

6. **Redis caching**: Current prices are cached in Redis with TTL 60 seconds during market hours, 24 hours after close (see [architecture](../01-system/architecture.md)). The SSE stream reads from Redis, not directly from the database.

7. **Rate limit awareness**: The status bar shows remaining API calls for rate-limited sources (Alpha Vantage free tier: 25/day). If a source is rate-limited, manual refresh is disabled with a tooltip: "Rate limit reached. Next reset: {time}."

## Edge Cases

1. **SSE connection lost**: The frontend displays a yellow "Reconnecting..." banner below the status bar. Prices freeze at their last known values. All freshness indicators switch to stale (yellow) after 60 seconds of disconnection. On reconnect, a full price snapshot is fetched via `GET /prices/current` to catch up.

2. **All pipelines down**: Status bar dot turns red. A red banner appears at the top of every page: "Market data feeds are unavailable. Showing last known prices from {timestamp}." The dashboard and all features continue to display cached data with prominent staleness warnings.

3. **Market holiday (no prices expected)**: The market status badge shows `CLOSED — Holiday: {name}`. Freshness indicators for that exchange do not degrade to stale during the holiday. The pipeline scheduler skips runs for holidays.

4. **New security added (no price history)**: Appears in the price table with `Last Price: —` and `Freshness: N/A`. Price data populates on the next pipeline run that includes this security.

5. **Price data gap (missed trading day)**: If a security has no price for a date that is not a holiday, the freshness indicator turns yellow. The previous available close price is used. The gap is noted in the pipeline metadata.

6. **Crypto during traditional market hours display**: Crypto prices update continuously (5 min intervals via CoinGecko). Their freshness badges follow the CoinGecko schedule, independent of stock exchange hours.

7. **Manual pipeline trigger during active run**: The API returns `409 CONFLICT` if the pipeline is already running. The UI disables the "Run Now" button and shows a spinner with "Running..." until the pipeline completes.

8. **Alpha Vantage rate limit exhausted**: The Alpha Vantage source row in the freshness panel shows an orange "Rate Limited" badge. Manual refresh for Alpha Vantage is disabled. Securities that rely solely on Alpha Vantage show stale prices with a "Rate limited" tooltip.

## Acceptance Criteria

1. The market status bar displays correct open/closed/pre-market status for NYSE, NASDAQ, OMX Helsinki, and OMX Stockholm based on current time and market calendars.
2. The SSE stream delivers price updates to the frontend in real-time, and the price table updates without page refresh.
3. Price freshness badges correctly reflect green (< threshold), yellow (stale), and red (failed) states per data source.
4. The pipeline health panel shows the last run status, timestamp, duration, and row count for each data pipeline.
5. Manual pipeline trigger via "Run Now" button works and shows a running indicator until completion.
6. The status bar (visible on all pages) shows pipeline health dot, last price update time, and compact market status indicators.
7. SSE auto-reconnects within 5 seconds on connection loss and fetches a full snapshot to catch up on missed events.
8. The disconnection banner appears when SSE is lost and disappears on successful reconnection.
9. Market holidays are correctly handled: no stale warnings, status badge shows holiday name.
10. Price flashing (background highlight on update) is visible and lasts approximately 200ms.
11. Sorting and filtering on the price table work correctly across all columns.
12. Rate-limited sources display appropriate warnings and disable manual refresh.

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
