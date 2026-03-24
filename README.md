# Bloomvalley Terminal

Personal Bloomberg-style terminal for investment tracking and analysis, powered by AI analyst agents.

## Features

### Portfolio & Trading
- **Portfolio Dashboard** — real-time holdings, P&L, allocation by asset class and account
- **AI Recommendations** — buy/sell/hold signals from 9-role AI analyst swarm with bull/bear cases, confidence levels, target prices, and retrospective accuracy tracking
- **Holdings** — current positions across accounts with cost basis, unrealized P&L, live quotes, dividend income
- **Transactions** — filterable transaction log with type/account filters, search, pagination, and summary stats
- **Nordnet Import** — paste or upload Nordnet portfolio exports (UTF-16 Finnish CSV), automatic security matching and reconciliation

### Market Data
- **Data Feeds** — pipeline status dashboard with manual trigger controls for all 20+ data sources
- **Watchlists** — create multiple watchlists, track securities with latest prices across Nordic, European, and US markets
- **Charts** — TradingView candlestick/line charts with technical indicators (SMA, EMA, Bollinger, RSI, MACD)
- **Heatmap** — treemap visualization of portfolio or watchlist with 1D/1W/1M/3M/6M/1Y/YTD period selection

### Analysis
- **Risk Analysis** — portfolio volatility, Sharpe/Sortino ratios, max drawdown, VaR, beta, correlation heatmap, stress tests, glidepath tracking
- **Research** — per-security research notes with bull/bear/base cases, intrinsic value, margin of safety, moat ratings, tagging, full-text search
- **Fundamentals** — P/B ratio, free cash flow, DCF valuation, ROIC, margins, short interest
- **Earnings** — earnings calendar with estimates, actual EPS, revenue surprises, Q-over-Q comparisons

### Income & Tax
- **Tax Analysis** — Finnish tax law (30/34% brackets), tax lot tracking with specific identification, deemed cost comparison (hankintameno-olettama), osakesäästötili tracker, loss harvesting candidates
- **Fixed Income** — bond holdings with coupon rates, YTM, credit ratings, call dates, duration
- **Dividends** — upcoming dividend calendar, yield metrics (dividend yield, yield on cost), income projections, historical dividend events

### Macro & News
- **Macro Dashboard** — Finland, Eurozone, and US macroeconomic indicators with yield curves and charts
- **News Feed** — aggregated financial news from Google News RSS + regional sources (CNBC, ECB, YLE, DI, FT, Yardeni), per-security linking, impact tagging, bookmarks
- **Global Events** — GDELT-powered macro event tracking with market impact categorization and sector analysis

### Tracking & Alerts
- **Insider Trading** — insider trades (FI/SE/US), signal detection (cluster buying, CEO/CFO buys), congress trades (STOCK Act), share buyback programs
- **Alerts** — price, event, and position alerts with trigger history and notification tracking

### AI Analyst Swarm
- **9-role investment team**: Portfolio Manager, Research Analyst, Risk Manager, Quant Analyst, Macro Strategist, Fixed Income Analyst, Tax Strategist, Technical Analyst, Compliance Officer
- **Scheduled runs**: 3x daily full analysis (07:00, 12:00, 19:00) + 2x nighttime research-only runs (01:00, 03:00)
- **Automatic data refresh**: all pipelines triggered before each analysis run
- **Watchlist rotation**: 20 securities per research batch, rotating through full watchlist
- **Recommendation extraction**: portfolio manager synthesizes all analyst inputs into actionable buy/sell/hold recommendations

### Special Features
- **Security Detail Pages** — deep-dive view per ticker with fundamentals, charts, valuation, news, analyst reports, dividends, insider activity
- **TV Dashboard** — 2-page fullscreen mode (`Cmd+Shift+F`) with portfolio summary, market status, holdings heatmap, recommendations, news feed, and per-holding analysis tiles with AI-generated bull/bear cases
- **Command Palette** — `Cmd+K` search across features, securities, and quick actions
- **Privacy Mode** — `Cmd+Shift+P` to blur all monetary amounts and quantities
- **PWA** — installable on mobile with offline access to dashboard, recommendations, and holdings (service worker with network-first caching)
- **Status Bar** — live pipeline status indicators, market hours for Nordic/EU/London/US/Crypto exchanges

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 14, TypeScript, TailwindCSS, TradingView Lightweight Charts, Recharts |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0 (async), pandas, numpy |
| Database | PostgreSQL 16 + TimescaleDB |
| Cache | Redis 7 |
| AI | Claude Code CLI (analyst swarm), 9 agent definitions |
| Deployment | Docker Compose, self-hosted |

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

### 3. Create config files before first start

The analyst-swarm service mounts `config.local.yaml` as a file bind mount. If this file doesn't exist when Docker Compose starts, Docker will create it as an **empty directory**, which crashes the service. Create it first:

```bash
# Copy default config (uses claude_cli provider by default)
cp analyst-swarm/config.yaml analyst-swarm/config.local.yaml

# Edit to customize LLM provider, schedule, etc.
# See analyst-swarm/config.yaml for all options
```

### 4. Start all services

```bash
docker compose up -d --build
```

This starts 6 services:

| Service | Port | Description |
|---------|------|-------------|
| `db` | 5432 | TimescaleDB (PostgreSQL 16) |
| `redis` | 6379 | Redis 7 with AOF persistence |
| `backend` | 8000 | FastAPI application |
| `frontend` | 3000 | Next.js application (PWA-enabled) |
| `cron` | — | Scheduled pipeline runner (20 jobs) |
| `analyst-swarm` | — | AI analyst agents (3 daily + 2 nighttime runs) |

### 5. Run database migrations

```bash
docker compose exec backend alembic upgrade head
```

### 6. Verify

```bash
curl http://localhost:8000/api/v1/health
# {"data":{"status":"healthy","checks":{"database":"ok","redis":"ok"}}, ...}
```

### 7. Initial data fetch

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

# Fetch dividends
curl -X POST "http://localhost:8000/api/v1/pipelines/yahoo_dividends/run"

# Fetch fundamentals
curl -X POST "http://localhost:8000/api/v1/pipelines/yahoo_fundamentals/run"

# Fetch insider trades
curl -X POST "http://localhost:8000/api/v1/pipelines/openinsider/run"
curl -X POST "http://localhost:8000/api/v1/pipelines/nasdaq_nordic_insider/run"
curl -X POST "http://localhost:8000/api/v1/pipelines/fi_se_insider/run"

# Fetch news
curl -X POST "http://localhost:8000/api/v1/pipelines/google_news/run"
curl -X POST "http://localhost:8000/api/v1/pipelines/regional_news/run"

# Fetch global events
curl -X POST "http://localhost:8000/api/v1/pipelines/gdelt_events/run"
```

---

## API Keys

All API keys are stored in `.env` (never committed to git).

| Key | Required | Free? | Where to get it |
|-----|----------|-------|-----------------|
| `FRED_API_KEY` | Yes (for macro dashboard) | Yes | https://fred.stlouisfed.org/docs/api/api_key.html |
| `ALPHA_VANTAGE_API_KEY` | Optional (backup prices) | Yes (limited) | https://www.alphavantage.co/support/#api-key |
| `FINNHUB_API_KEY` | Optional (earnings) | Yes (limited) | https://finnhub.io/ |

**No API key needed for:** Yahoo Finance (yfinance), ECB Statistical Data Warehouse, CoinGecko (public API), Google News RSS, OpenInsider (scraping), Nasdaq Nordic, Swedish FI, SEC EDGAR, Quiver Quantitative, Morningstar (public APIs), justETF, Kenneth French Data Library, GDELT, regional RSS feeds.

---

## Reverse Proxy Setup

When deploying behind a reverse proxy (Traefik, nginx, Caddy), two things must be configured:

### 1. Update `FRONTEND_URL` for CORS

The backend uses `FRONTEND_URL` from `.env` to set the `Access-Control-Allow-Origin` header. This must match the domain users access in their browser:

```bash
# In .env — change from default localhost to your domain
FRONTEND_URL=http://bloomvalley.example.com
```

### 2. Set `NEXT_PUBLIC_API_URL` to empty

In `docker-compose.yml`, the frontend's `NEXT_PUBLIC_API_URL` must be empty so browser API calls go to the same origin (your reverse proxy), not `localhost:8000`:

```yaml
environment:
  - NEXT_PUBLIC_API_URL=
```

The Next.js rewrite in `next.config.mjs` proxies `/api/*` requests to the backend container. Your reverse proxy should route both the frontend and `/api/*` paths to the appropriate service.

### Example: Traefik (file provider)

Create a dynamic config file (e.g., `bloomvalley.yml`):

```yaml
http:
  routers:
    bloomvalley-api:
      rule: "Host(`bloomvalley.example.com`) && PathPrefix(`/api`)"
      entryPoints:
        - web
      service: bloomvalley-api
      priority: 100

    bloomvalley-frontend:
      rule: "Host(`bloomvalley.example.com`)"
      entryPoints:
        - web
      service: bloomvalley-frontend

  services:
    bloomvalley-api:
      loadBalancer:
        servers:
          - url: "http://<docker-host-ip>:8000"

    bloomvalley-frontend:
      loadBalancer:
        servers:
          - url: "http://<docker-host-ip>:3000"
```

Replace `<docker-host-ip>` with your Docker bridge IP (typically `172.17.0.1`, check with `ip -4 addr show docker0`).

### Example: nginx

```nginx
server {
    listen 80;
    server_name bloomvalley.example.com;

    location /api/ {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

---

## Data Pipelines

### Available Pipelines

| Pipeline | Source | Data | Schedule |
|----------|--------|------|----------|
| `yahoo_daily_prices` | Yahoo Finance | OHLCV prices for all securities | Weekdays 23:00 |
| `yahoo_dividends` | Yahoo Finance | Dividend events (ex-dates, amounts, frequency) | Weekdays 23:30 |
| `yahoo_fundamentals` | Yahoo Finance | Key metrics (ROIC, P/B, FCF, margins, DCF) | Weekdays 23:45 |
| `ecb_fx_rates` | ECB | EUR-based exchange rates (USD, GBP, SEK, etc.) | Weekdays 17:00 |
| `ecb_macro_indicators` | ECB SDW | ECB rates, Euro yield curve, HICP inflation, unemployment | Weekdays 12:00 |
| `fred_macro_indicators` | FRED | US + Eurozone + Finland macro data (30+ series) | Daily 15:00 |
| `coingecko_prices` | CoinGecko | Crypto prices (BTC, ETH) | Every 6 hours |
| `alpha_vantage_prices` | Alpha Vantage | Backup prices for stale securities + forex | Weekdays 00:00 |
| `google_news` | Google News RSS | News for held securities + global macro topics | Every 4 hours |
| `regional_news` | CNBC, ECB, YLE, DI, FT, Yardeni | Regional financial news from RSS feeds | Every 4 hours |
| `gdelt_events` | GDELT DOC API | Global macro events (economic crisis, trade wars, sanctions) | Every 6 hours |
| `openinsider` | OpenInsider.com | US insider transactions (SEC Form 4) | Weekdays 22:00 |
| `nasdaq_nordic_insider` | Nasdaq News API | Finnish PDMR transactions | Weekdays 19:00 |
| `fi_se_insider` | Swedish FI | Swedish insider transactions | Weekdays 19:30 |
| `sec_edgar_filings` | SEC EDGAR | Form 4 & 13F-HR insider filings | Weekdays 21:00 |
| `quiver_congress_trades` | Quiver Quantitative | US Congress member stock trades (STOCK Act) | Weekdays 20:00 |
| `morningstar_ratings` | Morningstar | Star ratings, analyst ratings, expense ratios | Sundays 11:00 |
| `justetf_profiles` | justETF.com | ETF profiles (TER, fund size, replication method) | Sundays 10:00 |
| `french_factors` | Kenneth French Library | Fama-French 5-factor daily data (US & Europe) | Sundays 12:00 |
| `news_cleanup` | — | Retention cleanup for old news items | Daily 04:00 |

All times are Europe/Helsinki timezone.

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

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Cmd+K` | Open command palette (search features/securities) |
| `Cmd+1` | Go to portfolio dashboard |
| `Cmd+2` | Go to transactions |
| `Cmd+3` | Go to import |
| `Cmd+Shift+P` | Toggle privacy mode (blur amounts) |
| `Cmd+Shift+F` | Toggle fullscreen TV dashboard |
| `Arrow Left/Right` | Navigate fullscreen dashboard pages |
| `Esc` | Close command palette or exit fullscreen |

---

## PWA / Mobile

The app is installable as a Progressive Web App on mobile devices.

- **Offline support**: Dashboard, Recommendations, and Holdings pages work offline with cached data
- **Install prompt**: Shows on mobile after 60 seconds with instructions (iOS: Share > Add to Home Screen; Android: native install button)
- **Service worker**: Network-first strategy — always tries fresh data, falls back to cache when offline
- **Cached API endpoints**: portfolio summary, holdings, recommendations, dividend projections, live quotes

Note: iOS Safari does not support background fetch in service workers. Data is cached when you visit — there is no background refresh on iPhone.

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

> **Important:** Do NOT use `--single-transaction` with TimescaleDB dumps. TimescaleDB's circular foreign-key constraints cause the first error to abort the entire transaction, resulting in an empty database. Run the restore without it — the `--disable-triggers` flag used during backup ensures correct ordering.

```bash
# Stop services to prevent writes during restore
docker compose stop backend cron analyst-swarm

# If restoring into an existing database, drop and recreate it first
docker compose exec db psql -U warren -d postgres -c "DROP DATABASE warren;"
docker compose exec db psql -U warren -d postgres -c "CREATE DATABASE warren OWNER warren;"

# Restore from SQL dump (no --single-transaction)
docker compose exec -T db psql -U warren warren < backup_20260323.sql

# Restore from compressed dump
gunzip -c backup_20260323.sql.gz | docker compose exec -T db psql -U warren warren

# Restart services
docker compose up -d
```

You may see two harmless TimescaleDB warnings (`table "prices" is not a hypertable` and `ONLY option not supported`). These are cosmetic and do not affect the restored data.

After restoring, verify with:

```bash
docker compose exec db psql -U warren warren -c "SELECT count(*) FROM securities;"
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

```

**Transfer to new server:**

```bash
scp migration_backup.sql.gz migration_config.tar.gz user@newserver:/tmp/
```

**On the new server:**

```bash
# 1. Clone the repo
git clone https://github.com/freducom/bloomvalley.git
cd bloomvalley

# 2. Restore config files
tar xzf /tmp/migration_config.tar.gz

# 3. Install Claude CLI and log in (if using claude_cli provider)
npm install -g @anthropic-ai/claude-code
claude login

# 4. Create data directories and start database
# Edit .env to set POSTGRES_DATA_DIR / REDIS_DATA_DIR if using custom paths
mkdir -p data/postgres data/redis  # or your custom paths from .env
docker compose up -d db redis
sleep 10  # Wait for DB to initialize

# 5. Restore data (the dump includes the full schema, no need to run migrations)
docker compose up -d backend
sleep 5
gunzip -c /tmp/migration_backup.sql.gz | docker compose exec -T db psql -U warren warren

# 6. Start all services
docker compose up -d --build

# 7. Verify
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
├── CLAUDE.md               # AI agent instructions
├── AGENTS.md               # Investment team definitions
├── data/                   # Persistent storage (git-ignored)
│   ├── postgres/           # Database files
│   └── redis/              # Redis AOF
├── .claude/agents/         # AI analyst agent definitions
│   ├── portfolio-manager.md
│   ├── research-analyst.md
│   ├── risk-manager.md
│   ├── quant-analyst.md
│   ├── macro-strategist.md
│   ├── fixed-income-analyst.md
│   ├── tax-strategist.md
│   ├── technical-analyst.md
│   └── compliance-officer.md
├── analyst-swarm/
│   ├── Dockerfile
│   ├── swarm.py            # Orchestrator (schedules, runs agents, extracts recommendations)
│   ├── config.yaml         # Default config
│   └── config.local.yaml   # Local overrides (LLM provider, schedule)
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/            # Database migrations
│   ├── cron_scheduler.py   # Pipeline scheduler (20 jobs)
│   ├── app/
│   │   ├── main.py         # FastAPI app + lifespan
│   │   ├── config.py       # Pydantic settings from .env
│   │   ├── db/
│   │   │   ├── engine.py   # Async SQLAlchemy engine
│   │   │   ├── models/     # ORM models (20+ tables)
│   │   │   └── seed.py     # Initial securities catalog
│   │   ├── api/v1/
│   │   │   ├── router.py   # All route registrations
│   │   │   ├── portfolio.py, holdings.py, transactions.py
│   │   │   ├── recommendations.py, research.py, fundamentals.py
│   │   │   ├── risk.py, tax.py, dividends.py, fixed_income.py
│   │   │   ├── macro.py, news.py, global_events.py
│   │   │   ├── insider.py, alerts.py, earnings.py
│   │   │   ├── charts.py, screener.py, technical.py
│   │   │   ├── optimization.py, backtest.py, factors.py
│   │   │   ├── attribution.py, projections.py, reports.py
│   │   │   ├── quotes.py, swarm.py
│   │   │   └── imports.py, watchlists.py, securities.py
│   │   ├── pipelines/      # 20 data source adapters
│   │   │   ├── yahoo_finance.py, yahoo_dividends.py, yahoo_fundamentals.py
│   │   │   ├── ecb.py, ecb_macro.py, fred.py
│   │   │   ├── coingecko.py, alpha_vantage.py
│   │   │   ├── google_news.py, regional_news.py, gdelt.py
│   │   │   ├── openinsider.py, nasdaq_nordic_insider.py, fi_se_insider.py
│   │   │   ├── sec_edgar.py, quiver_congress.py
│   │   │   ├── morningstar.py, justetf.py
│   │   │   ├── french_factors.py, finnhub_earnings.py
│   │   │   └── runner.py, base.py
│   │   └── services/
│   │       ├── nordnet_parser.py, optimizer.py, monte_carlo.py
│   │       ├── screener.py, backtester.py, factor_analysis.py
│   │       ├── alert_evaluator.py, rebalancer.py
│   │       ├── bond_calculator.py, technical.py
│   │       └── sector_impact.py, news_cleanup.py
│   └── tests/
└── frontend/
    ├── Dockerfile
    ├── package.json
    ├── next.config.mjs
    ├── public/
    │   ├── manifest.json   # PWA manifest
    │   ├── sw.js           # Service worker (offline caching)
    │   └── icon-*.svg      # PWA icons
    ├── src/app/
    │   ├── layout.tsx      # Root layout with sidebar, status bar, PWA
    │   ├── portfolio/      # Dashboard
    │   ├── recommendations/# AI recommendations
    │   ├── holdings/       # Current positions
    │   ├── transactions/   # Trade history
    │   ├── import/         # Nordnet CSV import
    │   ├── market/         # Data feed status
    │   ├── watchlist/      # Watchlist management
    │   ├── charts/         # TradingView charts
    │   ├── heatmap/        # Treemap visualization
    │   ├── risk/           # Risk analysis
    │   ├── research/       # Research notes
    │   ├── fundamentals/   # Company fundamentals
    │   ├── earnings/       # Earnings calendar
    │   ├── tax/            # Tax analysis
    │   ├── fixed-income/   # Bond analysis
    │   ├── dividends/      # Dividend tracking
    │   ├── macro/          # Macro dashboard
    │   ├── news/           # News feed
    │   ├── global-events/  # GDELT events
    │   ├── insider/        # Insider trading
    │   ├── alerts/         # Alert management
    │   ├── security/[ticker]/ # Security detail
    │   └── fullscreen/     # TV dashboard
    ├── src/components/
    │   ├── layout/         # Sidebar, StatusBar, CommandPalette
    │   ├── pwa/            # InstallPrompt, ServiceWorkerRegistration
    │   └── ui/             # MetricCard, TickerLink
    └── src/lib/
        ├── api.ts          # Fetch wrapper
        ├── format.ts       # Currency/number formatters
        └── privacy.tsx     # Privacy mode context
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
