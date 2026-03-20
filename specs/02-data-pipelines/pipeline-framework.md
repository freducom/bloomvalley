# Data Pipeline Framework

Defines the common framework that all data pipeline adapters must implement, including the adapter interface, scheduling, rate limiting, retry logic, validation, idempotency, staleness tracking, and API endpoints for monitoring and manual control. Every external data source in Warren Cashett is ingested through this framework.

**Status: DRAFT**

## Dependencies

- [Spec Conventions](../00-meta/spec-conventions.md) — naming rules, terminology, spec template
- [Architecture](../01-system/architecture.md) — APScheduler, adapter pattern, Redis caching, project structure
- [Data Model](../01-system/data-model.md) — `pipeline_runs` table, `pipeline_runs_source_enum`, `pipeline_runs_status_enum`

---

## Data Source Summary

| Source | Data Types | Schedule | Rate Limit | Auth |
|--------|-----------|----------|------------|------|
| **Yahoo Finance** | Daily OHLCV prices, dividends, splits, fundamentals | Prices: every 15 min (market hours). Fundamentals: weekly. | 60 req/min (reasonable, no published limit) | None |
| **Alpha Vantage** | Fundamentals, earnings, financial statements | Weekly | 25 req/day (free tier) | API key (required) |
| **CoinGecko** | Crypto prices, market cap, volume | Every 5 min (24/7) | 10 req/min (free tier) | API key (optional) |
| **FRED** | Macro indicators (Fed Funds, CPI, GDP, unemployment) | Daily | 120 req/min | API key (required) |
| **ECB** | EUR FX rates | Daily (weekdays) | No published limit (reasonable use) | None |
| **justETF** | ETF holdings, TER, replication method | Weekly | Scraping — conservative (2 req/min) | None |
| **Morningstar** | ESG scores, fund ratings | Monthly | Scraping — conservative (2 req/min) | None |

---

## Adapter Interface

Every data source has a dedicated adapter module located at `backend/app/pipelines/{source_name}.py`. All adapters inherit from the abstract base class defined in `backend/app/pipelines/base.py`.

### Abstract Base Class

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Any

@dataclass
class PipelineResult:
    """Outcome of a single pipeline run."""
    rows_fetched: int
    rows_valid: int
    rows_stored: int
    rows_skipped: int
    errors: list[str]        # validation/transformation error messages
    metadata: dict[str, Any] # source-specific details (tickers processed, etc.)

class PipelineAdapter(ABC):
    """Base class for all data pipeline adapters."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Pipeline source identifier matching pipeline_runs_source_enum."""
        ...

    @property
    @abstractmethod
    def pipeline_name(self) -> str:
        """Human-readable pipeline name, e.g. 'yahoo_daily_prices'."""
        ...

    @abstractmethod
    async def fetch(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch raw data from the external source.

        Args:
            from_date: Start of date range (inclusive). None = use default lookback.
            to_date: End of date range (inclusive). None = today.

        Returns:
            List of raw records as dicts.

        Raises:
            RetryableError: For transient failures (will be retried).
            NonRetryableError: For permanent failures (logged and skipped).
        """
        ...

    @abstractmethod
    async def validate(self, raw_records: list[dict]) -> tuple[list[dict], list[str]]:
        """Validate raw records against data quality rules.

        Returns:
            Tuple of (valid_records, error_messages).
            Invalid records are excluded from valid_records.
            Each error message describes why a record was rejected.
        """
        ...

    @abstractmethod
    async def transform(self, valid_records: list[dict]) -> list[dict]:
        """Transform validated records into the schema expected by the database.

        Handles unit conversions, field mapping, currency normalization, etc.
        """
        ...

    @abstractmethod
    async def load(self, transformed_records: list[dict]) -> int:
        """Upsert transformed records into the database.

        Uses ON CONFLICT ... DO UPDATE for idempotency.

        Returns:
            Number of rows affected (inserted + updated).
        """
        ...

    async def run(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> PipelineResult:
        """Execute the full pipeline: fetch → validate → transform → load.

        This method is called by the scheduler and manual trigger endpoint.
        The base class provides the default implementation; adapters
        override only the four abstract methods above.
        """
        raw = await self.fetch(from_date, to_date)
        valid, errors = await self.validate(raw)
        transformed = await self.transform(valid)
        rows_stored = await self.load(transformed)

        return PipelineResult(
            rows_fetched=len(raw),
            rows_valid=len(valid),
            rows_stored=rows_stored,
            rows_skipped=len(raw) - len(valid),
            errors=errors,
            metadata={},
        )
```

### Error Types

```python
class RetryableError(Exception):
    """Transient error — the pipeline runner will retry."""
    pass

class NonRetryableError(Exception):
    """Permanent error — logged and skipped, no retry."""
    pass
```

### Adapter Registration

Each adapter class is registered in a central registry dict keyed by `source_name`. The scheduler and manual trigger endpoint look up adapters by name from this registry.

```python
# backend/app/pipelines/__init__.py
PIPELINE_REGISTRY: dict[str, type[PipelineAdapter]] = {}

def register_pipeline(cls: type[PipelineAdapter]) -> type[PipelineAdapter]:
    """Class decorator to register a pipeline adapter."""
    PIPELINE_REGISTRY[cls.source_name] = cls
    return cls
```

---

## Scheduling

### APScheduler Configuration

The scheduler runs inside the FastAPI process using APScheduler's async scheduler. It is initialized during the FastAPI lifespan event and shut down gracefully on exit.

- **Job store**: PostgreSQL (via SQLAlchemy) — job state survives container restarts
- **Executor**: AsyncIO executor — pipeline adapters are async
- **Max concurrent jobs**: 3 — prevents overwhelming external APIs and the database
- **Misfire grace time**: 300 seconds — if a job is delayed by up to 5 minutes it still runs; beyond that it skips to the next scheduled time

### Pipeline Configuration File

All schedules are defined in `backend/pipelines.yaml`, loaded at startup.

```yaml
pipelines:
  yahoo_finance_prices:
    source: yahoo_finance
    schedule: "*/15 * * * *"       # every 15 minutes
    market_hours_only: true        # skip outside NYSE/Helsinki hours
    enabled: true
    timeout: 60                    # seconds
    max_retries: 3
    rate_limit:
      requests_per_minute: 60

  yahoo_finance_fundamentals:
    source: yahoo_finance
    schedule: "0 2 * * 0"         # weekly, Sunday 02:00
    enabled: true
    timeout: 300
    max_retries: 3
    rate_limit:
      requests_per_minute: 60

  alpha_vantage:
    source: alpha_vantage
    schedule: "0 3 * * 0"         # weekly, Sunday 03:00
    enabled: true
    timeout: 600
    max_retries: 3
    rate_limit:
      requests_per_day: 25

  coingecko:
    source: coingecko
    schedule: "*/5 * * * *"       # every 5 minutes, 24/7
    enabled: true
    timeout: 30
    max_retries: 3
    rate_limit:
      requests_per_minute: 10

  fred:
    source: fred
    schedule: "0 6 * * *"         # daily at 06:00 UTC
    enabled: true
    timeout: 120
    max_retries: 3
    rate_limit:
      requests_per_minute: 120

  ecb_fx:
    source: ecb
    schedule: "0 16 * * 1-5"      # weekdays at 16:00 UTC (ECB publishes ~15:00 CET)
    enabled: true
    timeout: 60
    max_retries: 3
    rate_limit:
      requests_per_minute: 30

  justetf:
    source: justetf
    schedule: "0 4 * * 0"         # weekly, Sunday 04:00
    enabled: true
    timeout: 600
    max_retries: 3
    rate_limit:
      requests_per_minute: 2

  morningstar_esg:
    source: morningstar
    schedule: "0 5 1 * *"         # monthly, 1st of month at 05:00
    enabled: true
    timeout: 600
    max_retries: 3
    rate_limit:
      requests_per_minute: 2
```

### Refresh Schedule Summary

| Data Type | Frequency | Notes |
|-----------|-----------|-------|
| Prices (stocks, ETFs) | Every 15 minutes during market hours | Daily close stored permanently |
| Prices (crypto) | Every 5 minutes, 24/7 | No market hours restriction |
| Fundamentals | Weekly (Sunday) | Earnings, balance sheet, cash flow |
| FX rates | Daily (weekdays, 16:00 UTC) | ECB reference rates |
| Macro indicators | Daily (06:00 UTC) | FRED data series |
| ETF details | Weekly (Sunday) | Holdings, TER, replication |
| ESG scores | Monthly (1st of month) | Morningstar ESG ratings |

### Market Hours Handling

When `market_hours_only: true` is set, the scheduler checks whether the current time falls within active market hours before executing the pipeline. If outside market hours, the job is skipped silently (no error logged).

Market hours are defined as: NYSE 09:30-16:00 ET or Helsinki 10:00-18:30 EET, whichever is wider. Weekends and known market holidays are skipped.

---

## Rate Limiting

### Per-Source Rate Limit Registry

A shared rate limiter registry ensures all pipeline runs for the same source respect the same limits, even if multiple pipelines query the same source concurrently.

```python
@dataclass
class RateLimitConfig:
    requests_per_minute: int | None = None
    requests_per_day: int | None = None
```

### Implementation

- **Algorithm**: Token bucket
- **Scope**: One bucket per source (e.g., all Yahoo Finance pipelines share one bucket)
- **Bucket refill**: Tokens replenish at a constant rate (requests_per_minute / 60 tokens per second)
- **Daily limits**: For sources with daily limits (Alpha Vantage), a separate daily counter resets at 00:00 UTC
- **Blocking behavior**: When tokens are exhausted, the adapter `await`s until tokens are available (does not raise an error)
- **Shared state**: Rate limit state is held in-memory (single process). If the container restarts, buckets start full — acceptable since restarts are infrequent

### Source Rate Limits

| Source | Limit | Implementation |
|--------|-------|----------------|
| Yahoo Finance | 60 req/min | Token bucket, 1 token/sec |
| Alpha Vantage | 25 req/day | Daily counter, resets 00:00 UTC |
| CoinGecko | 10 req/min | Token bucket, 1 token/6sec |
| FRED | 120 req/min | Token bucket, 2 tokens/sec |
| ECB | 30 req/min | Token bucket, 0.5 tokens/sec |
| justETF | 2 req/min | Token bucket, 1 token/30sec |
| Morningstar | 2 req/min | Token bucket, 1 token/30sec |

---

## Retry and Backoff

### Strategy

- **Algorithm**: Exponential backoff with jitter
- **Base delay**: 1 second
- **Maximum delay**: 60 seconds
- **Jitter**: +/- 20% (randomized to prevent thundering herd)
- **Max retries**: 3 per pipeline run (configurable per pipeline in YAML)

### Delay Formula

```
delay = min(base * 2^attempt, max_delay)
jitter = delay * random.uniform(-0.20, 0.20)
actual_delay = delay + jitter
```

| Attempt | Base Delay | Delay Range (with jitter) |
|---------|-----------|---------------------------|
| 1 | 2s | 1.6s - 2.4s |
| 2 | 4s | 3.2s - 4.8s |
| 3 | 8s | 6.4s - 9.6s |

### Retryable Errors

These errors trigger a retry (wrapped as `RetryableError`):

- HTTP 429 (Too Many Requests)
- HTTP 500 (Internal Server Error)
- HTTP 502 (Bad Gateway)
- HTTP 503 (Service Unavailable)
- HTTP 504 (Gateway Timeout)
- Connection timeout
- DNS resolution failure
- Connection reset / refused (transient)

### Non-Retryable Errors

These errors are logged and the pipeline run ends immediately (wrapped as `NonRetryableError`):

- HTTP 400 (Bad Request) — malformed request, likely a bug
- HTTP 401 (Unauthorized) — invalid API key
- HTTP 403 (Forbidden) — access denied
- HTTP 404 (Not Found) — invalid ticker or endpoint
- JSON decode errors from API response
- Unexpected response schema

### Retry Wrapper

The base `PipelineAdapter.run()` method wraps the `fetch()` call with retry logic. The `validate()`, `transform()`, and `load()` steps are not retried — if they fail, it indicates a code bug, not a transient issue.

---

## Data Validation

### Validation Rules

Every record fetched from an external source passes through the adapter's `validate()` method before storage. Validation rules are specific to each data type:

#### Price Data
- `close_cents` is required and > 0
- `high_cents >= low_cents` (when both present)
- `high_cents >= open_cents` and `high_cents >= close_cents` (when present)
- `low_cents <= open_cents` and `low_cents <= close_cents` (when present)
- `date` is not in the future
- `date` is a valid trading day for the market (weekday for stocks, any day for crypto)
- `volume >= 0` (when present)

#### FX Rate Data
- `rate > 0`
- `base_currency = 'EUR'`
- `quote_currency` is a valid ISO 4217 code
- `date` is not in the future

#### Macro Indicator Data
- `indicator_code` is a recognized series
- `date` is not in the future
- `value` is a finite number (not NaN or Inf)

#### Fundamental Data
- Required fields present (varies by statement type)
- Monetary values are finite numbers
- Fiscal period date is not in the future

#### ESG Data
- Scores in range 0-100 (when present)
- `as_of_date` is not in the future

### Handling Invalid Records

- Invalid records are excluded from the `transform()` and `load()` steps
- Each invalid record generates a log entry with: source, record identifier (e.g., ticker + date), validation rule violated, actual value
- Invalid record count is tracked in `PipelineResult.rows_skipped`
- A pipeline run with some invalid records is marked as `partial` status (not `failed`)
- A pipeline run with all records invalid is marked as `failed`

---

## Idempotency

All adapters use `INSERT ... ON CONFLICT ... DO UPDATE` (UPSERT) when writing to the database.

### Conflict Keys by Table

| Table | Conflict Key | Update Columns |
|-------|-------------|----------------|
| `prices` | `(security_id, date)` | All OHLCV columns, `source` |
| `fx_rates` | `(base_currency, quote_currency, date)` | `rate`, `source` |
| `macro_indicators` | `(indicator_code, date)` | `value`, `unit`, `source` |
| `esg_scores` | `(security_id, as_of_date)` | All score columns, `source` |

### Guarantees

- Re-running any pipeline for the same date range produces the same result
- No duplicate records are ever created
- Later data overwrites earlier data for the same key (latest source wins)
- Safe to manually trigger any pipeline at any time

---

## Staleness Tracking

### Pipeline Run Recording

After each pipeline run (success or failure), the adapter runner inserts a row into the `pipeline_runs` table:

| Field | Value |
|-------|-------|
| `source` | Adapter's `source_name` |
| `pipeline_name` | Adapter's `pipeline_name` |
| `status` | `success`, `failed`, or `partial` |
| `started_at` | Timestamp when `run()` was called |
| `finished_at` | Timestamp when `run()` completed |
| `duration_ms` | `finished_at - started_at` in milliseconds |
| `rows_affected` | `PipelineResult.rows_stored` |
| `error_message` | First error message (if any), truncated to 2000 chars |
| `metadata` | JSON with `rows_fetched`, `rows_valid`, `rows_skipped`, plus adapter-specific data |

### Redis Caching of Pipeline Status

After a successful run, the runner stores `last_success_at` per pipeline in Redis:

- **Key**: `pipeline:{pipeline_name}:last_success_at`
- **Value**: ISO 8601 timestamp
- **TTL**: None (persistent until overwritten)

This allows the status endpoint to respond without querying PostgreSQL.

### Staleness Thresholds

A pipeline is considered stale if `now() - last_success_at > 2 * scheduled_interval`.

| Pipeline | Scheduled Interval | Staleness Threshold |
|----------|-------------------|-------------------|
| yahoo_finance_prices | 15 min | 30 min |
| coingecko | 5 min | 10 min |
| fred | 24 hours | 48 hours |
| ecb_fx | 24 hours | 48 hours |
| yahoo_finance_fundamentals | 7 days | 14 days |
| alpha_vantage | 7 days | 14 days |
| justetf | 7 days | 14 days |
| morningstar_esg | 30 days | 60 days |

---

## API Endpoints

### `GET /api/v1/pipelines`

Returns last-run information for every configured pipeline.

**Response** `200 OK`:

```json
{
  "pipelines": [
    {
      "name": "yahoo_finance_prices",
      "source": "yahoo_finance",
      "schedule": "*/15 * * * *",
      "enabled": true,
      "lastSuccess": "2026-03-19T14:15:00Z",
      "lastFailure": null,
      "lastRunStatus": "success",
      "lastRunDurationMs": 4523,
      "lastRunRowsAffected": 142,
      "isStale": false,
      "nextScheduledRun": "2026-03-19T14:30:00Z"
    }
  ]
}
```

### `GET /api/v1/pipelines/status`

Health check endpoint. Returns all pipelines with operational status.

**Response** `200 OK`:

```json
{
  "overall": "healthy",
  "pipelines": [
    {
      "name": "yahoo_finance_prices",
      "lastSuccess": "2026-03-19T14:15:00Z",
      "lastFailure": null,
      "isStale": false,
      "nextScheduledRun": "2026-03-19T14:30:00Z"
    },
    {
      "name": "coingecko",
      "lastSuccess": "2026-03-19T14:10:00Z",
      "lastFailure": "2026-03-19T14:05:00Z",
      "isStale": false,
      "nextScheduledRun": "2026-03-19T14:15:00Z"
    }
  ]
}
```

The `overall` field is `"healthy"` when no pipelines are stale, `"degraded"` when one or more are stale, and `"unhealthy"` when critical pipelines (prices, FX rates) are stale.

### `POST /api/v1/pipelines/{name}/run`

Manually trigger a pipeline run. Useful for initial setup, debugging, or historical backfill.

**Path parameter**: `name` — the pipeline name (e.g., `yahoo_finance_prices`)

**Query parameters** (optional):
- `fromDate` — start of date range, ISO 8601 date (e.g., `2025-01-01`)
- `toDate` — end of date range, ISO 8601 date (e.g., `2026-03-19`)

**Response** `202 Accepted`:

```json
{
  "message": "Pipeline yahoo_finance_prices triggered",
  "pipelineRunId": 1234
}
```

The pipeline runs asynchronously. The caller can poll `GET /api/v1/pipelines` to check completion, or query the `pipeline_runs` table by ID.

**Error responses**:
- `404 Not Found` — unknown pipeline name
- `409 Conflict` — pipeline is already running
- `422 Unprocessable Entity` — invalid date range (fromDate > toDate)

---

## Logging

Every pipeline run is logged with structlog, producing structured JSON entries.

### Log Fields

| Field | Description |
|-------|-------------|
| `event` | `"pipeline_run_completed"` or `"pipeline_run_failed"` |
| `source` | Data source name |
| `pipeline_name` | Pipeline identifier |
| `status` | `success`, `failed`, or `partial` |
| `duration_ms` | Total execution time |
| `rows_fetched` | Records received from external API |
| `rows_valid` | Records that passed validation |
| `rows_stored` | Records written to database |
| `rows_skipped` | Records that failed validation |
| `error` | Error message (on failure) |
| `from_date` | Date range start (if specified) |
| `to_date` | Date range end (if specified) |
| `trigger` | `"scheduled"` or `"manual"` |

### Example Log Entry

```json
{
  "event": "pipeline_run_completed",
  "source": "yahoo_finance",
  "pipeline_name": "yahoo_finance_prices",
  "status": "partial",
  "duration_ms": 4523,
  "rows_fetched": 150,
  "rows_valid": 142,
  "rows_stored": 142,
  "rows_skipped": 8,
  "trigger": "scheduled",
  "timestamp": "2026-03-19T14:15:04Z",
  "level": "warning"
}
```

Log levels: `info` for success, `warning` for partial, `error` for failed.

---

## Graceful Degradation

### Principles

- **No cascade failures**: Each pipeline runs independently. One broken pipeline never affects others.
- **Serve stale data**: If a source is down, the system continues serving the most recent stored data. The data is stale but still useful.
- **UI staleness indicators**: The frontend shows a staleness badge on any data whose source pipeline is stale (see staleness thresholds above).
- **No empty states**: Even if all pipelines fail, previously stored data remains available.

### Failure Isolation

- Each pipeline runs in its own async task with an independent timeout
- Database connections are returned to the pool on failure (no leaked connections)
- Rate limiter state is unaffected by pipeline failures
- Redis cache invalidation only happens on successful writes

### Recovery

- When a previously-failed source recovers, the next scheduled run picks up fresh data automatically
- No manual intervention required for recovery
- Staleness indicators clear automatically once a successful run completes

---

## Pipeline Runner Lifecycle

The complete lifecycle of a pipeline run (scheduled or manual):

```
1. Scheduler triggers adapter (or manual API call)
2. Check if pipeline is already running → reject if so (409)
3. Insert pipeline_runs row with status='running'
4. Acquire rate limiter tokens
5. Execute: fetch() → validate() → transform() → load()
   - fetch() is wrapped with retry logic (up to max_retries)
   - On RetryableError: wait with exponential backoff, retry fetch()
   - On NonRetryableError: mark run as failed, exit
6. On timeout: mark run as failed with error "timeout after {N}s"
7. Update pipeline_runs row: status, finished_at, duration_ms, rows_affected, error
8. On success/partial: update Redis last_success_at
9. On success/partial: invalidate relevant Redis cache keys
10. Log structured run summary
```

---

## Edge Cases

1. **Container restart during pipeline run**: The `pipeline_runs` row with `status='running'` will have no `finished_at`. On startup, the scheduler detects orphaned running jobs (started_at > 10 minutes ago, no finished_at) and marks them as `failed` with error `"orphaned — container restart"`.

2. **External API returns empty data**: Treated as a successful run with `rows_fetched=0`. No existing data is deleted. Logged at `warning` level.

3. **Clock skew between container and external API**: Date comparisons use the container's UTC clock. A record with a date slightly in the future (up to 1 day) is accepted — the "not in the future" validation allows a 1-day tolerance.

4. **Rate limit exceeded despite local limiting**: If the external API returns 429 despite local rate limiting (e.g., shared API key), treated as a retryable error. The retry backoff naturally provides additional delay.

5. **Database connection pool exhausted**: Pipeline load() will wait for a connection up to the configured pool timeout, then fail with a retryable error.

6. **Multiple manual triggers for the same pipeline**: The second request gets a `409 Conflict` while the first is still running.

7. **Pipeline YAML config changes**: The scheduler reloads `pipelines.yaml` on container restart. Hot-reloading is not supported — restart the backend container to pick up schedule changes.

8. **Source API schema change**: Unexpected fields are ignored. Missing required fields cause validation failures, which are logged and the records are skipped. The pipeline does not crash.

9. **Daylight saving time transitions**: All scheduling uses UTC cron expressions. Market hours checking accounts for the current timezone offset of the relevant exchange.

10. **Very large backfill requests**: Manual triggers with wide date ranges may exceed rate limits or timeouts. The adapter should chunk large date ranges internally and process them in batches, respecting rate limits.

## Open Questions

- Should we add a dead-letter queue for persistently failed records (e.g., store them for manual review)?
- Should pipeline YAML support hot-reloading via a file watcher, or is container restart sufficient?

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
