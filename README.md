# Warren Cashett

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
- **Data Pipelines** — automated fetching from Yahoo Finance, ECB, CoinGecko, FRED

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
git clone <repo-url> warren-cashett
cd warren-cashett
cp .env.example .env
```

Edit `.env` and add your API keys (see [API Keys](#api-keys) below).

### 2. Database setup

```bash
# Create database
createdb warren_cashett

# Enable TimescaleDB extension
psql warren_cashett -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
psql warren_cashett -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
```

### 3. Backend

```bash
cd backend
cp ../.env .env   # Or create a local .env with localhost URLs:
# DATABASE_URL=postgresql+asyncpg://youruser@localhost:5432/warren_cashett
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
git clone <repo-url> warren-cashett
cd warren-cashett
cp .env.example .env
```

Edit `.env` with your API keys and a strong database password:

```bash
POSTGRES_PASSWORD=your_strong_password_here
DATABASE_URL=postgresql+asyncpg://warren:your_strong_password_here@db:5432/warren
FRED_API_KEY=your_fred_api_key
```

### 2. Create persistent data directories

```bash
mkdir -p data/postgres data/redis
```

These directories store all persistent state:

| Directory | Contents | Backup? |
|-----------|----------|---------|
| `data/postgres/` | PostgreSQL database files (all portfolio data, prices, indicators) | **Yes** |
| `data/redis/` | Redis AOF persistence (pipeline cache, session state) | Optional |
| `.env` | API keys and secrets | **Yes** (keep separate backup) |

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
# Warren Cashett data pipelines (times in server local timezone)
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

## Backup

### Database Backup

```bash
# Docker
docker compose exec db pg_dump -U warren warren > backup_$(date +%Y%m%d).sql

# Local
pg_dump warren_cashett > backup_$(date +%Y%m%d).sql
```

### Restore

```bash
# Docker
docker compose exec -T db psql -U warren warren < backup_20260320.sql

# Local
psql warren_cashett < backup_20260320.sql
```

---

## Project Structure

```
warren-cashett/
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
