# System Architecture

Defines the component architecture, deployment topology, data flow, and cross-cutting concerns for the Bloomvalley terminal.

## Dependencies

- [Spec Conventions](../00-meta/spec-conventions.md)

## System Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Compose                        │
│                                                         │
│  ┌──────────┐    ┌──────────┐    ┌──────────────────┐  │
│  │ Frontend  │◄──►│ Backend  │◄──►│    Database       │  │
│  │ Next.js   │    │ FastAPI  │    │ PostgreSQL +     │  │
│  │ :3000     │    │ :8000    │    │ TimescaleDB      │  │
│  └──────────┘    └────┬─────┘    │ :5432            │  │
│                       │          └──────────────────┘  │
│                       │                                 │
│                  ┌────┴─────┐    ┌──────────┐          │
│                  │ Scheduler│    │  Redis    │          │
│                  │ (APScheduler)│ │  :6379   │          │
│                  └────┬─────┘    └──────────┘          │
│                       │                                 │
│              ┌────────┴────────┐                       │
│              │  Data Pipelines │                       │
│              │  (adapters)     │                       │
│              └────────┬────────┘                       │
│                       │                                 │
└───────────────────────┼─────────────────────────────────┘
                        │
              ┌─────────┴─────────┐
              │  External APIs    │
              │  Yahoo, FRED,     │
              │  ECB, CoinGecko,  │
              │  Alpha Vantage... │
              └───────────────────┘
```

## Components

### Frontend — Next.js (TypeScript)

- **Port**: 3000
- **Framework**: Next.js 14+ with App Router
- **Styling**: TailwindCSS with custom dark terminal theme
- **Charts**: TradingView Lightweight Charts (price/candle), Recharts (analytics)
- **Tables**: TanStack Table (virtual scrolling, sorting, filtering)
- **State**: TanStack Query for server state, React Context for UI state (theme, sidebar)
- **Role**: Display-only. All financial calculations, data processing, and business logic happen server-side. The frontend fetches pre-computed data from the API and renders it.

### Backend — FastAPI (Python)

- **Port**: 8000
- **Framework**: FastAPI with async support
- **Financial libs**: pandas, numpy, scipy (for XIRR, Monte Carlo)
- **ORM / DB access**: SQLAlchemy 2.0 (async) with Alembic for migrations
- **Validation**: Pydantic v2 models for request/response schemas
- **Role**: All business logic — portfolio valuation, risk calculations, tax computations, screening, rebalancing suggestions. Serves the REST API consumed by the frontend.

### Database — PostgreSQL 16 + TimescaleDB 2.x

- **Port**: 5432
- **Regular tables**: accounts, securities, transactions, tax_lots, holdings, watchlists, research_notes, alerts, esg_scores, corporate_actions, dividends
- **TimescaleDB hypertables**: prices (daily OHLCV), fx_rates (daily), macro_indicators (daily/monthly)
- **Chunk interval**: 1 month for prices/fx_rates (optimized for "last N days" queries)
- **Extensions**: `timescaledb`, `pg_trgm` (for text search on security names)

### Redis

- **Port**: 6379
- **Role**: Caching layer for frequently accessed data
  - Current prices (TTL: 60 seconds during market hours, 24 hours after close)
  - Portfolio snapshot (TTL: 5 minutes)
  - Computed risk metrics (TTL: 1 hour)
  - Pipeline status / last-run timestamps
- **Not used for**: persistent data, message queuing, or session storage

### Scheduler — APScheduler

- **Runs inside**: the Backend container (same Python process)
- **Role**: Triggers data pipeline jobs on schedule
- **Schedules**: defined in a YAML config file, per-pipeline
- **Persistence**: job state stored in PostgreSQL (survives container restarts)
- **Concurrency**: max 3 concurrent pipeline jobs to respect rate limits

### Data Pipelines (Adapters)

- Each external data source has a dedicated adapter module
- All adapters implement a common interface (see [pipeline framework](../02-data-pipelines/pipeline-framework.md))
- Adapters are invoked by the scheduler or manually via API (`POST /api/v1/pipelines/{name}/run`)

## Data Flow

### Ingestion Flow (Pipelines → Database)
```
Scheduler triggers adapter
  → Adapter fetches from external API
  → Adapter validates and transforms data
  → Adapter upserts into database (idempotent)
  → Adapter updates pipeline_runs table (status, timestamp, row count)
  → Redis cache invalidated for affected data
```

### Read Flow (Database → Frontend)
```
Frontend makes API request
  → FastAPI checks Redis cache
  → Cache hit: return cached data
  → Cache miss: query PostgreSQL, compute if needed, cache result, return
  → Frontend renders data
```

### Live Price Flow (WebSocket/SSE)
```
Frontend opens SSE connection to /api/v1/prices/stream
  → Backend streams price updates as they arrive from pipelines
  → Frontend updates displayed prices in real-time
  → Connection auto-reconnects on failure
```

## Project Structure

```
bloomvalley/
├── AGENTS.md                    # Team definitions, domain requirements
├── CLAUDE.md                    # Project conventions for Claude Code
├── specs/                       # All specification documents
├── docker-compose.yml           # Container orchestration
├── .env.example                 # Environment variable template
│
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml           # Python dependencies (Poetry or uv)
│   ├── alembic/                 # Database migrations
│   │   ├── alembic.ini
│   │   └── versions/
│   ├── app/
│   │   ├── main.py              # FastAPI app factory, middleware, lifespan
│   │   ├── config.py            # Settings from environment variables
│   │   ├── db/
│   │   │   ├── engine.py        # SQLAlchemy engine and session
│   │   │   ├── models/          # SQLAlchemy ORM models (one file per table group)
│   │   │   └── seed.py          # Seed data scripts
│   │   ├── api/
│   │   │   ├── v1/
│   │   │   │   ├── router.py    # Top-level v1 router
│   │   │   │   ├── portfolio.py # Portfolio endpoints
│   │   │   │   ├── holdings.py
│   │   │   │   ├── transactions.py
│   │   │   │   ├── prices.py
│   │   │   │   ├── watchlists.py
│   │   │   │   ├── screener.py
│   │   │   │   ├── risk.py
│   │   │   │   ├── tax.py
│   │   │   │   ├── research.py
│   │   │   │   ├── macro.py
│   │   │   │   ├── alerts.py
│   │   │   │   ├── esg.py
│   │   │   │   ├── pipelines.py
│   │   │   │   └── reports.py
│   │   │   └── schemas/         # Pydantic request/response models
│   │   ├── services/            # Business logic layer
│   │   │   ├── portfolio.py
│   │   │   ├── valuation.py
│   │   │   ├── risk.py
│   │   │   ├── tax.py
│   │   │   ├── tax_lots.py
│   │   │   ├── glidepath.py
│   │   │   ├── screener.py
│   │   │   ├── monte_carlo.py
│   │   │   └── rebalancing.py
│   │   ├── pipelines/           # Data ingestion adapters
│   │   │   ├── base.py          # Abstract adapter interface
│   │   │   ├── scheduler.py     # APScheduler setup
│   │   │   ├── yahoo_finance.py
│   │   │   ├── alpha_vantage.py
│   │   │   ├── fred.py
│   │   │   ├── ecb.py
│   │   │   ├── coingecko.py
│   │   │   ├── justetf.py
│   │   │   └── morningstar.py
│   │   └── utils/
│   │       ├── money.py         # Integer money arithmetic helpers
│   │       └── dates.py         # Market calendar, timezone helpers
│   └── tests/
│       ├── conftest.py
│       ├── test_tax.py          # Extensive Finnish tax scenario tests
│       ├── test_tax_lots.py
│       ├── test_valuation.py
│       ├── test_risk.py
│       └── ...
│
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── next.config.ts
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx       # Root layout with sidebar
│   │   │   ├── page.tsx         # Redirects to /portfolio
│   │   │   ├── portfolio/       # F01
│   │   │   ├── market/          # F02
│   │   │   ├── watchlist/       # F03
│   │   │   ├── risk/            # F04
│   │   │   ├── tax/             # F05
│   │   │   ├── research/        # F06
│   │   │   ├── macro/           # F07
│   │   │   ├── charts/          # F08
│   │   │   ├── fixed-income/    # F09
│   │   │   ├── alerts/          # F10
│   │   │   ├── esg/             # F11
│   │   │   └── transactions/    # F12
│   │   ├── components/
│   │   │   ├── ui/              # Generic: MetricCard, DataTable, ChartCard, etc.
│   │   │   ├── layout/          # Shell, Sidebar, StatusBar, CommandPalette
│   │   │   └── charts/          # Chart wrappers: PriceChart, AllocationRing, etc.
│   │   ├── lib/
│   │   │   ├── api.ts           # API client (fetch wrapper)
│   │   │   ├── types.ts         # Generated from OpenAPI schema
│   │   │   ├── format.ts        # Number/date/currency formatters
│   │   │   └── constants.ts     # Feature routes, keyboard shortcuts
│   │   └── hooks/
│   │       ├── usePortfolio.ts  # TanStack Query hooks per feature
│   │       ├── usePrices.ts
│   │       └── ...
│   └── public/
│       └── favicon.ico
│
└── scripts/
    ├── seed-securities.py       # Seed initial security catalog
    └── generate-types.sh        # Generate TS types from OpenAPI
```

## Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://warren:warren@db:5432/warren` | Yes |
| `REDIS_URL` | Redis connection string | `redis://redis:6379/0` | Yes |
| `ALPHA_VANTAGE_API_KEY` | Alpha Vantage free tier key | — | Yes |
| `COINGECKO_API_KEY` | CoinGecko free tier key (optional) | — | No |
| `LOG_LEVEL` | Logging level | `INFO` | No |
| `FRONTEND_URL` | Frontend origin for CORS | `http://localhost:3000` | No |
| `TZ` | Container timezone | `Europe/Helsinki` | No |

## Docker Compose Services

| Service | Image | Ports | Volumes |
|---------|-------|-------|---------|
| `frontend` | Build from `./frontend` | `3000:3000` | Source code (dev mount) |
| `backend` | Build from `./backend` | `8000:8000` | Source code (dev mount) |
| `db` | `timescale/timescaledb:latest-pg16` | `5432:5432` | `pgdata` named volume |
| `redis` | `redis:7-alpine` | `6379:6379` | — (ephemeral cache) |

## Cross-Cutting Concerns

### Error Handling
- **Data pipeline failures**: logged, staleness counter incremented, previous data preserved. UI shows staleness badge.
- **Calculation errors**: return error response with detail, never return wrong numbers silently.
- **External API errors**: retry with exponential backoff (max 3 attempts), then mark pipeline as failed.

### Logging
- Structured JSON logging via Python `structlog`
- Every pipeline run logs: source, status, duration, rows affected, errors
- API requests logged with response time (no sensitive data)

### Security
- No authentication (single-user, localhost)
- API keys stored in `.env`, never in code or database
- CORS restricted to `FRONTEND_URL`
- No public network exposure — Docker internal network only

### Performance Targets
- Portfolio dashboard load: < 500ms
- Price history query (1 year, 1 security): < 100ms
- Risk metric computation (full portfolio): < 2 seconds
- Screener query (500 securities, 5 factors): < 3 seconds

### Technology Versions
- Python: 3.12+
- Node.js: 20 LTS
- PostgreSQL: 16
- TimescaleDB: 2.x (latest)
- Redis: 7.x
- Next.js: 14+
- FastAPI: 0.110+

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
