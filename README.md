# Bloomvalley Terminal

Personal Bloomberg-style terminal for investment tracking and analysis.

## Features

- **Portfolio Dashboard** — real-time holdings, P&L, allocation by asset class and account
- **Nordnet Import** — paste or upload Nordnet portfolio exports (UTF-16 Finnish CSV), automatic reconciliation of changes
- **Watchlists** — create multiple watchlists, track securities with latest prices
- **Charts** — TradingView candlestick/line charts with technical indicators (SMA, EMA, Bollinger, RSI, MACD)
- **Macro Dashboard** — Finland, Eurozone, and US macroeconomic indicators with yield curves
- **Transactions** — filterable transaction log with type/account filters, search, pagination, and summary stats
- **Risk Analysis** — portfolio volatility, Sharpe/Sortino ratios, max drawdown, VaR, correlation heatmap, stress tests, glidepath tracking
- **Dividends** — upcoming dividend calendar, yield metrics (dividend yield, yield on cost), income projections, historical dividend events from Yahoo Finance
- **Research** — per-security research notes with bull/bear/base cases, intrinsic value, margin of safety, moat ratings, tagging, full-text search
- **Tax Analysis** — Finnish tax law (30/34% brackets), tax lot tracking with FIFO, deemed cost comparison (hankintameno-olettama), osakesäästötili tracker, loss harvesting candidates
- **Insider Tracking** — insider trades (FI/SE/US), signal detection (cluster buying, CEO/CFO buys), congress trades (STOCK Act), share buyback programs
- **News Feed** — aggregated financial news from Google News RSS, per-security linking, impact tagging, bookmarks, sentiment summary
- **Data Pipelines** — automated fetching from Yahoo Finance, ECB, CoinGecko, FRED, Google News

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14, TypeScript, TailwindCSS, TradingView Lightweight Charts |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0 (async), pandas, numpy |
| Database | PostgreSQL 16 + TimescaleDB |
| Cache | Redis 7 |
| Deployment | Docker Compose |

---

## Quick Start (Local Development)

### Prerequisites

- Python 3.12+
- Node.js 20+
- PostgreSQL 16 with TimescaleDB extension
- Redis 7

### 1. Clone and configure

```bash
git clone <repo-url> bloomvalley
cd bloomvalley
cp .env.example .env
```

Edit `.env` and add your API keys (see [API Keys](#api-keys) below).

### 2. Database setup

```bash
# Create database
createdb bloomvalley

# Enable TimescaleDB extension
psql bloomvalley -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
psql bloomvalley -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

### 3. Backend

```bash
cd backend
cp ../.env .env   # Or create a local .env with localhost URLs:
# DATABASE_URL=postgresql+asyncpg://youruser@localhost:5432/bloomvalley
# REDIS_URL=redis://localhost:6379/0
# FRED_API_KEY=your_key_here

python -m venv .venv
source .venv/bin/activate
pip install -e .

# Run migrations
alembic upgrade head

# Seed initial securities (optional)
python -m app.db.seed

# Start backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000.

---

## Docker Deployment (Server)

### 1. Clone and configure

```bash
git clone <repo-url> bloomvalley
cd bloomvalley
cp .env.example .env
```

Edit `.env` with your API keys and a strong database password:

```bash
POSTGRES_PASSWORD=your_strong_password_here
DATABASE_URL=postgresql+asyncpg://warren:your_strong_password_here@db:5432/warren
FRED_API_KEY=your_fred_api_key
```

### 2. Create persistent data directories

By default, data is stored in `./data/` within the project. To use custom locations (e.g., a separate disk or partition), set these in `.env`:

```bash
# Default: data stored in project directory
mkdir -p data/postgres data/redis

# Or: custom locations (set in .env)
POSTGRES_DATA_DIR=/mnt/storage/bloomvalley/postgres
REDIS_DATA_DIR=/mnt/storage/bloomvalley/redis
```

Create whichever directories you chose:

```bash
# If using defaults:
mkdir -p data/postgres data/redis

# If using custom paths (example):
mkdir -p /mnt/storage/bloomvalley/postgres /mnt/storage/bloomvalley/redis
```

These directories store all persistent state:

| Variable | Default | Contents | Backup? |
|----------|---------|----------|---------|
| `POSTGRES_DATA_DIR` | `./data/postgres` | PostgreSQL database files (all portfolio data, prices, indicators) | **Yes** |
| `REDIS_DATA_DIR` | `./data/redis` | Redis AOF persistence (pipeline cache, session state) | Optional |
| `.env` | — | API keys and secrets | **Yes** (keep separate backup) |

### 3. Start all services

```bash
docker compose up -d --build
```

This starts 5 services:

| Service | Port | Description |
|---------|------|-------------|
| `db` | 5432 | TimescaleDB (PostgreSQL 16) |
| `redis` | 6379 | Redis 7 with AOF persistence |
| `backend` | 8000 | FastAPI application |
| `frontend` | 3000 | Next.js application |
| `cron` | — | Scheduled pipeline runner |

### 4. Run database migrations

```bash
docker compose exec backend alembic upgrade head
```

### 5. Verify

```bash
curl http://localhost:8000/api/v1/health
# {"data":{"status":"healthy","checks":{"database":"ok","redis":"ok"}}, ...}
```

### 6. Initial data fetch

Trigger all pipelines to populate the database:

```bash
# Fetch stock/ETF prices (last 1 year)
curl -X POST "http://localhost:8000/api/v1/pipelines/yahoo_daily_prices/run?fromDate=2025-01-01"

# Fetch EUR exchange rates
curl -X POST "http://localhost:8000/api/v1/pipelines/ecb_fx_rates/run"

# Fetch crypto prices
curl -X POST "http://localhost:8000/api/v1/pipelines/coingecko_prices/run"

# Fetch US macro indicators (FRED)
curl -X POST "http://localhost:8000/api/v1/pipelines/fred_macro_indicators/run"

# Fetch Eurozone/Finland macro indicators (ECB)
curl -X POST "http://localhost:8000/api/v1/pipelines/ecb_macro_indicators/run"
```

---

## API Keys

All API keys are stored in `.env` (never committed to git).

| Key | Required | Free? | Where to get it |
|-----|----------|-------|-----------------|
| `FRED_API_KEY` | Yes (for macro dashboard) | Yes | https://fred.stlouisfed.org/docs/api/api_key.html |
| `ALPHA_VANTAGE_API_KEY` | No (future use) | Yes (limited) | https://www.alphavantage.co/support/#api-key |

**No API key needed for:** Yahoo Finance (yfinance library), ECB Statistical Data Warehouse, CoinGecko (public API).

---

## Data Pipelines

### Available Pipelines

| Pipeline | Source | Data | Frequency |
|----------|--------|------|-----------|
| `yahoo_daily_prices` | Yahoo Finance | OHLCV prices for all securities | Daily (weekdays) |
| `ecb_fx_rates` | ECB | EUR-based exchange rates (USD, GBP, SEK, etc.) | Daily (weekdays) |
| `coingecko_prices` | CoinGecko | Crypto prices (BTC, ETH) | Every 6 hours |
| `fred_macro_indicators` | FRED | US + Eurozone + Finland macro data (30+ series) | Daily |
| `ecb_macro_indicators` | ECB SDW | ECB rates, Euro yield curve, HICP inflation, unemployment | Daily (weekdays) |
| `yahoo_dividends` | Yahoo Finance | Dividend events (ex-dates, amounts, frequency) for all stocks/ETFs | Daily |
| `google_news` | Google News RSS | News articles for held securities + global macro topics | Every 30 min (market hours) |

### Manual Trigger

Trigger any pipeline via the REST API:

```bash
# Default date range (last 7 days for prices, last 1 year for macro)
curl -X POST http://localhost:8000/api/v1/pipelines/{pipeline_name}/run

# Custom date range
curl -X POST "http://localhost:8000/api/v1/pipelines/yahoo_daily_prices/run?fromDate=2024-01-01&toDate=2026-03-20"

# Check pipeline status
curl http://localhost:8000/api/v1/pipelines

# View run history
curl http://localhost:8000/api/v1/pipelines/{pipeline_name}/runs
```

### Automated Scheduling (Docker)

The `cron` service in Docker Compose runs all pipelines on schedule:

| Pipeline | Schedule (Helsinki time) | Why |
|----------|------------------------|-----|
| `yahoo_daily_prices` | Weekdays 23:00 | After US/EU markets close |
| `ecb_fx_rates` | Weekdays 17:00 | ECB publishes rates ~16:00 CET |
| `coingecko_prices` | Every 6 hours | Crypto trades 24/7 |
| `fred_macro_indicators` | Daily 15:00 | US data published morning ET |
| `ecb_macro_indicators` | Weekdays 12:00 | ECB data published morning CET |

The cron service is started automatically with `docker compose up`.

### Automated Scheduling (Local / Non-Docker Server)

If running without Docker, set up a system crontab:

```bash
crontab -e
```

Add these lines (adjust paths and timezone):

```cron
# Bloomvalley data pipelines (times in server local timezone)
# Yahoo Finance prices — weekdays at 23:00
0 23 * * 1-5 curl -s -X POST http://localhost:8000/api/v1/pipelines/yahoo_daily_prices/run > /dev/null 2>&1
# ECB FX rates — weekdays at 17:00
0 17 * * 1-5 curl -s -X POST http://localhost:8000/api/v1/pipelines/ecb_fx_rates/run > /dev/null 2>&1
# CoinGecko — every 6 hours
0 */6 * * * curl -s -X POST http://localhost:8000/api/v1/pipelines/coingecko_prices/run > /dev/null 2>&1
# FRED macro — daily at 15:00
0 15 * * * curl -s -X POST http://localhost:8000/api/v1/pipelines/fred_macro_indicators/run > /dev/null 2>&1
# ECB macro — weekdays at 12:00
0 12 * * 1-5 curl -s -X POST http://localhost:8000/api/v1/pipelines/ecb_macro_indicators/run > /dev/null 2>&1
```

---

## Backup & Migration

### What to back up

| File / Directory | Contains | Critical? | Size |
|-----------------|----------|-----------|------|
| `$POSTGRES_DATA_DIR` (default: `data/postgres/`) | All portfolio data, prices, fundamentals, recommendations, news, research notes | **Yes** | ~100-500 MB |
| `$REDIS_DATA_DIR` (default: `data/redis/`) | Pipeline cache, session state | No (regenerated) | ~1 MB |
| `.env` | API keys (FRED, Alpha Vantage, Finnhub), DB passwords | **Yes** | <1 KB |
| `.claude/agents/` | AI analyst agent definitions and strategy rules | **Yes** (in git) | ~50 KB |
| `analyst-swarm/config.local.yaml` | Swarm LLM provider config, schedule | **Yes** | <1 KB |
| `~/.claude/` | Claude CLI auth tokens (for claude_cli provider) | **Yes** if using claude_cli | ~10 KB |

### Database backup

```bash
# Create a timestamped SQL dump (run from project root)
docker compose exec db pg_dump -U warren --disable-triggers warren > backup_$(date +%Y%m%d_%H%M).sql

# Compressed backup (recommended for large databases)
docker compose exec db pg_dump -U warren --disable-triggers warren | gzip > backup_$(date +%Y%m%d).sql.gz
```

> **Note:** TimescaleDB's internal tables (`hypertable`, `chunk`, `continuous_agg`) have circular foreign-key constraints that produce warnings during `pg_dump`. The `--disable-triggers` flag ensures clean restore. These warnings are cosmetic and do not affect the backup data.

### Database restore

```bash
# Stop backend first to prevent writes during restore
docker compose stop backend cron analyst-swarm

# Restore from SQL dump
docker compose exec -T db psql -U warren --single-transaction warren < backup_20260323.sql

# Restore from compressed dump
gunzip -c backup_20260323.sql.gz | docker compose exec -T db psql -U warren --single-transaction warren

# Restart services
docker compose up -d
```

### Full backup script

Save as `backup.sh` and run via cron (`0 2 * * * /path/to/backup.sh`):

```bash
#!/bin/bash
BACKUP_DIR="/path/to/backups"
PROJECT_DIR="/path/to/bloomvalley"
DATE=$(date +%Y%m%d)

# Database
cd "$PROJECT_DIR"
docker compose exec -T db pg_dump -U warren --disable-triggers warren | gzip > "$BACKUP_DIR/db_${DATE}.sql.gz"

# Config files
cp "$PROJECT_DIR/.env" "$BACKUP_DIR/env_${DATE}"
cp "$PROJECT_DIR/analyst-swarm/config.local.yaml" "$BACKUP_DIR/swarm_config_${DATE}.yaml" 2>/dev/null

# Keep last 30 days
find "$BACKUP_DIR" -name "db_*.sql.gz" -mtime +30 -delete
find "$BACKUP_DIR" -name "env_*" -mtime +30 -delete

echo "[backup] Done: $BACKUP_DIR/db_${DATE}.sql.gz"
```

### Migrating to a new server

**On the old server:**

```bash
cd /path/to/bloomvalley

# 1. Create database dump
docker compose exec db pg_dump -U warren --disable-triggers warren | gzip > migration_backup.sql.gz

# 2. Bundle config files
tar czf migration_config.tar.gz .env analyst-swarm/config.local.yaml .claude/agents/

# 3. Copy Claude auth (if using claude_cli provider)
tar czf migration_claude_auth.tar.gz -C ~ .claude/
```

**Transfer to new server:**

```bash
scp migration_backup.sql.gz migration_config.tar.gz migration_claude_auth.tar.gz user@newserver:/tmp/
```

**On the new server:**

```bash
# 1. Clone the repo
git clone https://github.com/freducom/bloomvalley.git
cd bloomvalley

# 2. Restore config files
tar xzf /tmp/migration_config.tar.gz

# 3. Restore Claude auth (if using claude_cli)
tar xzf /tmp/migration_claude_auth.tar.gz -C ~/

# 4. Create data directories and start database
# Edit .env to set POSTGRES_DATA_DIR / REDIS_DATA_DIR if using custom paths
mkdir -p data/postgres data/redis  # or your custom paths from .env
docker compose up -d db redis
sleep 10  # Wait for DB to initialize

# 5. Run migrations to create schema
docker compose up -d backend
sleep 5
docker compose exec backend alembic upgrade head

# 6. Restore data
gunzip -c /tmp/migration_backup.sql.gz | docker compose exec -T db psql -U warren warren

# 7. Start all services
docker compose up -d --build

# 8. Verify
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/portfolio/summary
```

### What you do NOT need to copy

- `$POSTGRES_DATA_DIR` raw directory — use SQL dump instead (portable across architectures)
- `$REDIS_DATA_DIR` — regenerated automatically by pipelines
- `node_modules/`, `.venv/`, `__pycache__/` — rebuilt by Docker
- `frontend/.next/` — rebuilt on container start

---

## Project Structure

```
bloomvalley/
├── .env.example            # Template for environment variables
├── .env                    # Your API keys (git-ignored)
├── .gitignore
├── docker-compose.yml      # All services + cron scheduler
├── data/                   # Persistent storage (git-ignored)
│   ├── postgres/           # Database files
│   └── redis/              # Redis AOF
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/            # Database migrations
│   ├── app/
│   │   ├── main.py         # FastAPI app + lifespan
│   │   ├── config.py       # Pydantic settings from .env
│   │   ├── db/
│   │   │   ├── engine.py   # Async SQLAlchemy engine
│   │   │   ├── models/     # ORM models (16 tables)
│   │   │   └── seed.py     # Initial securities catalog
│   │   ├── api/v1/
│   │   │   ├── router.py   # All route registrations
│   │   │   ├── portfolio.py
│   │   │   ├── imports.py  # Nordnet import + reconciliation
│   │   │   ├── watchlists.py
│   │   │   ├── charts.py   # OHLC + technical indicators
│   │   │   ├── macro.py    # Macro dashboard API
│   │   │   ├── risk.py     # Risk analysis + stress tests
│   │   │   ├── dividends.py # Dividend calendar + yield metrics
│   │   │   ├── research.py # Research notes CRUD
│   │   │   └── ...
│   │   ├── pipelines/
│   │   │   ├── runner.py   # Pipeline executor with retry
│   │   │   ├── yahoo_finance.py
│   │   │   ├── ecb.py      # FX rates
│   │   │   ├── ecb_macro.py # ECB macro indicators
│   │   │   ├── fred.py     # FRED macro indicators
│   │   │   └── coingecko.py
│   │   └── services/
│   │       └── nordnet_parser.py
│   └── tests/
└── frontend/
    ├── Dockerfile
    ├── package.json
    ├── src/app/
    │   ├── portfolio/      # Dashboard, holdings, P&L
    │   ├── import/         # Nordnet CSV import
    │   ├── watchlist/      # Watchlist management
    │   ├── charts/         # TradingView charts + indicators
    │   └── macro/          # Macro dashboard (FI/EZ/US)
    ├── src/components/
    │   ├── layout/         # Sidebar, StatusBar
    │   └── ui/             # MetricCard, etc.
    └── src/lib/
        ├── api.ts          # Fetch wrapper
        └── format.ts       # Currency/number formatters
```

---

## Macro Indicators

### Finland
- HICP inflation (YoY), Unemployment rate, Real GDP

### Eurozone
- ECB key rates (Main Refinancing, Deposit Facility)
- Euro AAA sovereign yield curve (2Y, 5Y, 10Y, 30Y)
- HICP inflation (headline + core), Unemployment, GDP growth

### United States
- Fed Funds rate, Treasury yields (2Y, 5Y, 10Y, 30Y) + spreads
- CPI, Core CPI, PCE, Breakeven inflation
- GDP, Unemployment, Nonfarm Payrolls, Jobless Claims
- Manufacturing employment

### Global
- High Yield and Investment Grade credit spreads (OAS)
