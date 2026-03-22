# API Overview

Design principles, conventions, and standard patterns for the Bloomvalley REST API.

## Dependencies

- [Architecture](./architecture.md)
- [Data Model](./data-model.md)
- [Spec Conventions](../00-meta/spec-conventions.md)

## Base URL

```
http://localhost:8000/api/v1
```

No versioning in the URL beyond `v1` — this is a single-user personal tool. Breaking changes are handled by database migrations, not API versioning.

## Authentication

None. The API is only accessible on localhost via Docker internal network. CORS is restricted to the frontend origin (`http://localhost:3000`).

## Standard Response Envelope

### Success Response

```json
{
  "data": { ... },
  "meta": {
    "timestamp": "2026-03-19T14:30:00Z",
    "cacheAge": 45,
    "stale": false
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `data` | object or array | The requested resource(s) |
| `meta.timestamp` | string (ISO 8601) | When the response was generated |
| `meta.cacheAge` | integer or null | Seconds since data was last refreshed from source (null if not cached) |
| `meta.stale` | boolean | `true` if `cacheAge` exceeds the expected refresh interval for this data type |

### Paginated Response

```json
{
  "data": [ ... ],
  "meta": {
    "timestamp": "2026-03-19T14:30:00Z",
    "cacheAge": null,
    "stale": false
  },
  "pagination": {
    "total": 347,
    "limit": 50,
    "offset": 0,
    "hasMore": true
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `pagination.total` | integer | Total matching records |
| `pagination.limit` | integer | Page size (default 50, max 500) |
| `pagination.offset` | integer | Number of records skipped |
| `pagination.hasMore` | boolean | Whether more records exist beyond this page |

Pagination uses offset-based pagination with `limit` and `offset` query parameters. Cursor-based pagination is not needed for this scale.

### Error Response

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Transaction amount must be positive",
    "details": [
      {
        "field": "amountCents",
        "message": "Must be greater than 0",
        "value": -500
      }
    ]
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `error.code` | string | Machine-readable error code (UPPER_SNAKE_CASE) |
| `error.message` | string | Human-readable description |
| `error.details` | array or null | Field-level validation errors (for 422 responses) |

### Standard Error Codes

| HTTP Status | Error Code | When |
|-------------|-----------|------|
| 400 | `BAD_REQUEST` | Malformed request syntax |
| 404 | `NOT_FOUND` | Resource does not exist |
| 422 | `VALIDATION_ERROR` | Request body fails validation |
| 409 | `CONFLICT` | Operation conflicts with current state (e.g., duplicate transaction) |
| 500 | `INTERNAL_ERROR` | Unexpected server error |
| 503 | `DATA_UNAVAILABLE` | Required data source is down or stale beyond threshold |

## Monetary Fields

All monetary values in API responses use the `Money` object:

```json
{
  "amount": 123456,
  "currency": "EUR"
}
```

- `amount`: integer in cents (123456 = €1,234.56)
- `currency`: ISO 4217 code

Request bodies accept the same format. The API never accepts or returns floating-point money values.

## Date and Time

- All timestamps in responses: ISO 8601 with UTC timezone (`2026-03-19T14:30:00Z`)
- Date-only fields: ISO 8601 date (`2026-03-19`)
- Query parameter date filters: `fromDate` and `toDate` (inclusive), ISO 8601 date format
- If `fromDate` is omitted, defaults to account inception
- If `toDate` is omitted, defaults to today

## Query Parameter Conventions

| Pattern | Format | Example |
|---------|--------|---------|
| Filtering by ID | camelCase + `Id` | `?accountId=1` |
| Date range | `fromDate`, `toDate` | `?fromDate=2025-01-01&toDate=2025-12-31` |
| Pagination | `limit`, `offset` | `?limit=50&offset=100` |
| Sorting | `sortBy`, `sortOrder` | `?sortBy=marketValue&sortOrder=desc` |
| Filtering by enum | camelCase field name | `?assetClass=stock&assetClass=etf` (multi-value) |
| Text search | `q` | `?q=apple` |

Multiple values for the same parameter are supported via repeated keys: `?assetClass=stock&assetClass=etf`.

## Endpoint Organization

Endpoints are grouped by feature domain, matching the feature spec numbering:

| Tag | Prefix | Feature |
|-----|--------|---------|
| Portfolio | `/portfolio` | F01 — Dashboard, holdings, allocation |
| Prices | `/prices` | F02 — Market data, live prices |
| Watchlists | `/watchlists` | F03 — Watchlist management |
| Screener | `/screener` | F03 — Security screening |
| Risk | `/risk` | F04 — Risk metrics, stress tests |
| Tax | `/tax` | F05 — Tax lots, gains, harvesting |
| Research | `/research` | F06 — Research notes, theses |
| Macro | `/macro` | F07 — Economic indicators |
| Charts | `/charts` | F08 — Chart data, indicators |
| Fixed Income | `/fixed-income` | F09 — Bond analysis, ladder |
| Alerts | `/alerts` | F10 — Alert management |
| ESG | `/esg` | F11 — ESG scores |
| Transactions | `/transactions` | F12 — Transaction log |
| Reports | `/reports` | F12 — Report generation |
| Securities | `/securities` | Shared — Security catalog |
| Accounts | `/accounts` | Shared — Account management |
| Pipelines | `/pipelines` | System — Data pipeline control |
| Health | `/health` | System — Health check |

## Key Endpoint Summary

### System
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check with DB and Redis status |
| GET | `/pipelines` | List all pipelines with last-run status |
| POST | `/pipelines/{name}/run` | Manually trigger a pipeline |

### Securities & Accounts
| Method | Path | Description |
|--------|------|-------------|
| GET | `/securities` | List securities (paginated, searchable) |
| GET | `/securities/{id}` | Security detail with fundamentals |
| POST | `/securities` | Add a security to the catalog |
| GET | `/accounts` | List all accounts |
| POST | `/accounts` | Create an account |
| GET | `/accounts/{id}` | Account detail with summary |

### Portfolio (F01)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/portfolio/summary` | Total value, P&L, allocation vs target |
| GET | `/portfolio/holdings` | All current positions with market values |
| GET | `/portfolio/allocation` | Current vs target allocation breakdown |
| GET | `/portfolio/glidepath` | Glidepath target vs actual over time |
| GET | `/portfolio/performance` | TWR and MWWR over configurable periods |

### Prices (F02)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/prices/{securityId}` | Historical prices (OHLCV) with date range |
| GET | `/prices/current` | Current prices for all held securities |
| GET | `/prices/stream` | SSE stream of live price updates |

### Transactions (F12)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/transactions` | List transactions (paginated, filterable) |
| POST | `/transactions` | Record a new transaction |
| PUT | `/transactions/{id}` | Update a transaction |
| DELETE | `/transactions/{id}` | Delete a transaction (cascades to tax lots) |

### Tax (F05)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/tax/lots` | List tax lots (filterable by status, account, security) |
| GET | `/tax/gains` | Realized + unrealized gains by period |
| GET | `/tax/gains/annual` | Annual tax summary for Vero.fi |
| GET | `/tax/harvesting` | Loss harvesting candidates |
| GET | `/tax/osakesaastotili` | Osakesäästötili account status (deposits, value, gains portion) |

### Risk (F04)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/risk/metrics` | Portfolio risk metrics (beta, Sharpe, Sortino, VaR, drawdown) |
| GET | `/risk/correlation` | Correlation matrix for held securities |
| GET | `/risk/stress-test` | Stress test results against predefined scenarios |

### Watchlists & Screener (F03)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/watchlists` | List all watchlists |
| POST | `/watchlists` | Create a watchlist |
| POST | `/watchlists/{id}/items` | Add security to watchlist |
| DELETE | `/watchlists/{id}/items/{securityId}` | Remove from watchlist |
| POST | `/screener/run` | Run a screen with factor filters (POST because filter body can be complex) |
| GET | `/screener/presets` | List saved screener presets |

### Research (F06)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/research/notes` | List research notes |
| GET | `/research/notes/{securityId}` | Research notes for a security |
| POST | `/research/notes` | Create a research note |
| PUT | `/research/notes/{id}` | Update a research note |

### Macro (F07)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/macro/indicators` | List available indicators with latest values |
| GET | `/macro/indicators/{code}` | Historical values for an indicator |
| GET | `/macro/regime` | Current economic regime assessment |

### Alerts (F10)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/alerts` | List all alerts |
| POST | `/alerts` | Create an alert |
| PUT | `/alerts/{id}` | Update an alert |
| DELETE | `/alerts/{id}` | Delete an alert |
| GET | `/alerts/rebalancing` | Current rebalancing suggestions with tax impact |

### Reports (F12)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/reports/tax/{year}` | Generate annual tax report |
| GET | `/reports/performance` | Performance attribution report |
| GET | `/reports/transactions/export` | Export transactions as CSV |

## SSE (Server-Sent Events) for Live Data

The `/prices/stream` endpoint provides real-time price updates:

```
GET /api/v1/prices/stream
Accept: text/event-stream
```

Event format:
```
event: price
data: {"securityId": 42, "price": {"amount": 15234, "currency": "USD"}, "change": 125, "changePercent": 0.83, "timestamp": "2026-03-19T14:30:00Z"}

event: status
data: {"market": "NYSE", "status": "open"}

event: heartbeat
data: {"timestamp": "2026-03-19T14:30:30Z"}
```

- Heartbeat every 30 seconds to keep connection alive
- Client should auto-reconnect with `Last-Event-ID` header
- Only securities in the current portfolio + watchlists are streamed

## Caching Headers

Responses include caching hints:

```
Cache-Control: private, max-age=60
X-Data-Age: 45
X-Data-Stale: false
```

- `X-Data-Age`: seconds since underlying data was refreshed from external source
- `X-Data-Stale`: `true` if the data source hasn't been updated within its expected interval

## Request Size Limits

- Maximum request body: 1 MB
- Maximum query string: 4 KB
- Maximum `limit` parameter: 500

## Edge Cases

1. **Stale data**: If a pipeline hasn't run successfully within 2× its scheduled interval, `meta.stale` is `true` and `X-Data-Stale: true` header is set
2. **Missing prices**: If a security has no price data, its market value is reported as `null` (not 0), and `holdings` response includes `"priceAvailable": false`
3. **Multi-currency**: All portfolio-level aggregations convert to EUR using the latest available FX rate. If FX rate is missing, the holding is excluded with a warning in the response
4. **Empty portfolio**: Returns valid empty arrays/objects, not errors
5. **Transaction deletion**: Cascades to tax lot recalculation — all lots after the deleted transaction are recomputed

## Open Questions

1. Should we add GraphQL alongside REST for complex dashboard queries? (Deferred — start with REST, add if N+1 becomes a problem)

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
