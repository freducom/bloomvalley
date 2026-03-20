# Warren Cashett

Personal Bloomberg-style terminal with AI-powered investment advisory.

## Project Overview

Two AI teams collaborating:
- **Investment Team** (10 roles): Portfolio Manager, Research Analyst, Risk Manager, Quant, Macro Strategist, Fixed Income Analyst, Tax Strategist, ESG Analyst, Technical Analyst, Compliance Officer
- **Development Team** (5 roles): Product Owner, Architect, DBA, Frontend Developer, Backend Developer

The Investment Team defines strategy and analysis needs. The Development Team builds the terminal that operationalizes it.

## Investor Profile

- Location: Finland (Finnish tax law, Vero.fi)
- Age: 45, target fixed income by 60 (15-year horizon)
- Philosophy: Munger total return + Boglehead hybrid (~60-70% index core, ~30-40% conviction satellite)
- Asset classes: Stocks, Bonds, ETFs, Crypto
- Tax structures: osakesaastotili, PS-sopimus, kapitalisaatiosopimus

## Tech Stack

- **Frontend**: Next.js, TypeScript, TailwindCSS, TradingView Lightweight Charts
- **Backend**: Python, FastAPI, pandas, numpy
- **Database**: PostgreSQL + TimescaleDB
- **Deployment**: Docker Compose, self-hosted
- **Data sources**: Yahoo Finance, Alpha Vantage, FRED, ECB, CoinGecko, justETF, Morningstar, Finnhub, SEC EDGAR, OpenInsider, Quiver Quantitative, Google News RSS

## Key Conventions

- All monetary values stored as integers (cents) with currency code — no floats
- All financial calculations happen server-side in Python
- Frontend is display-only — no business logic in the UI
- Tax lot tracking uses specific identification method
- Finnish tax rules: 30% capital gains up to 30k EUR, 34% above
- Data accuracy > usability > speed > aesthetics
- Accumulating (ACC) ETFs preferred over distributing
- P/B is a core metric across all analyses
- DCF is default valuation EXCEPT: banks (P/B), REITs (FFO), insurance (embedded value), utilities (DDM), mining (P/NAV)
- Commodity ETCs with contango flagged as poor long-term vehicles
- Always produce bull AND bear case for every security
- Long-term focus, no day trading
- Broker: Nordnet (Finland) — portfolio updates via paste-in export
- Watchlist: Swedish, Finnish, European, US — dividend aristocrats + growth companies
- Track recommendations with retrospective accuracy analysis

## Project Structure

See `AGENTS.md` for full team definitions, workflows, data sources, glidepath schedule, and feature roadmap.

## Development Rules

- Test all financial calculations thoroughly (tax scenarios, edge cases)
- Every data source must be replaceable (adapter pattern)
- Show stale/missing data visibly in UI — never show wrong data silently
- No auth/multi-tenancy — single-user personal tool
- Respect all API rate limits, implement backoff and caching
- **Always update `README.md`** when adding/changing: new features, new pipelines, new API keys or config, new services in docker-compose, changed project structure, new dependencies, or setup/deployment steps. The README is the single source of truth for installation and usage.
