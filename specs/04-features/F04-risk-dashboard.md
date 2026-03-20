# F04 — Risk Dashboard

**Status: DRAFT**

Portfolio risk overview answering the question: "How much risk am I taking, where is it concentrated, and how would my portfolio behave in a crisis?" The dashboard presents key risk metrics (beta, Sharpe, Sortino, VaR, max drawdown), a correlation heatmap revealing diversification quality, stress test scenarios modeled on historical crises, and concentration risk indicators. Four sub-tabs — Metrics, Correlation, Stress Tests, and Concentration — provide progressively deeper risk analysis.

## Dependencies

- Specs: [data-model](../01-system/data-model.md), [api-overview](../01-system/api-overview.md), [architecture](../01-system/architecture.md), [spec-conventions](../00-meta/spec-conventions.md), [risk-metrics](../03-calculations/risk-metrics.md), [portfolio-math](../03-calculations/portfolio-math.md), [design-system](../05-ui/design-system.md)
- Data: Yahoo Finance daily prices pipeline (at least 1 year of history for meaningful risk metrics), ECB FX rates pipeline
- API: `GET /risk/metrics`, `GET /risk/correlation`, `GET /risk/stress-test`

## Data Requirements

### Tables Read

| Table | Purpose |
|-------|---------|
| `prices` | Historical daily prices for return calculations (minimum 252 trading days for annual metrics) |
| `holdings_snapshot` | Current positions and weights for portfolio-level aggregation |
| `securities` | Security metadata (asset class, sector, country) for concentration analysis |
| `fx_rates` | EUR conversion of multi-currency returns |
| `accounts` | Account types for account-level risk breakdown |

### Tables Written

None. Risk metrics are computed on-the-fly and cached in Redis (TTL: 1 hour per [architecture](../01-system/architecture.md)).

### Calculations Invoked

- [risk-metrics](../03-calculations/risk-metrics.md): portfolio beta (vs MSCI World), Sharpe ratio, Sortino ratio, VaR (95% parametric + historical), max drawdown, correlation matrix, rolling volatility
- [portfolio-math](../03-calculations/portfolio-math.md): daily returns, portfolio return series from individual position returns and weights

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/risk/metrics` | Portfolio risk metrics: beta, Sharpe, Sortino, VaR 95%, max drawdown, annualized volatility. Supports `?period` (1Y, 3Y, 5Y, ALL) and `?benchmark` (default: MSCI World) |
| GET | `/risk/correlation` | Pairwise correlation matrix for all held securities. Supports `?period` (1Y, 3Y). Returns matrix + eigenvalue decomposition for diversification ratio |
| GET | `/risk/stress-test` | Portfolio impact under predefined stress scenarios. Returns per-scenario: estimated loss %, estimated loss amount, most affected positions |

See [api-overview](../01-system/api-overview.md) for full request/response schemas.

## UI Views

### Page Layout (`/risk`)

Top: sub-tab bar — **Metrics** | **Correlation** | **Stress Tests** | **Concentration**

### Sub-tab: Metrics (default)

**Top row — Risk metric cards (5 MetricCards, full width):**

| Metric | Format | Color Logic |
|--------|--------|-------------|
| Portfolio Beta | `0.85` (2 decimal) | Green if < 1.0, yellow if 1.0-1.2, red if > 1.2 |
| Sharpe Ratio | `1.23` (2 decimal) | Green if > 1.0, yellow if 0.5-1.0, red if < 0.5 |
| Sortino Ratio | `1.56` (2 decimal) | Green if > 1.5, yellow if 0.8-1.5, red if < 0.8 |
| VaR 95% (1-day) | `-€12,345` (absolute) and `-1.23%` | Always `negative` color (it is a loss figure) |
| Max Drawdown | `-15.67%` | Green if > -10%, yellow if -10% to -20%, red if < -20% |

Each card includes a small subtitle showing the calculation period (e.g., "1Y, vs MSCI World").

**Period selector:** Toggle buttons for 1Y, 3Y, 5Y, ALL. Changing the period re-computes all metrics.

**Benchmark selector:** Dropdown to choose benchmark (MSCI World, S&P 500, OMXH25, OMXS30). Default: MSCI World.

**Middle section — Rolling volatility chart:**

A line chart (Recharts) showing:
- Portfolio rolling annualized volatility (30-day window) as the primary line
- Benchmark rolling volatility as a dashed secondary line
- Period: matches the selected period above

X-axis: dates. Y-axis: annualized volatility (%). Hover tooltip shows exact values and date.

**Bottom section — Risk metrics detail table:**

A supplementary table expanding on the metric cards with additional context:

| Metric | Value | Period | Benchmark | Interpretation |
|--------|-------|--------|-----------|----------------|
| Annualized Return | +12.34% | 1Y | MSCI World: +10.5% | Outperforming |
| Annualized Volatility | 14.5% | 1Y | MSCI World: 15.2% | Lower vol |
| Beta | 0.85 | 1Y | — | Defensive tilt |
| Sharpe Ratio | 1.23 | 1Y | MSCI World: 0.95 | Superior risk-adjusted |
| Sortino Ratio | 1.56 | 1Y | — | Good downside control |
| VaR 95% (1-day) | -1.23% | 1Y | — | 5% chance of worse |
| VaR 95% (1-month) | -5.67% | 1Y | — | — |
| Max Drawdown | -15.67% | 1Y | MSCI World: -12.3% | Deeper drawdown |
| Calmar Ratio | 0.79 | 1Y | — | Return / max drawdown |
| Tracking Error | 3.45% | 1Y | vs MSCI World | Active risk |

### Sub-tab: Correlation

**Main section — Correlation heatmap:**

A matrix heatmap (Recharts or D3) showing pairwise correlation coefficients between all held securities.

- Rows and columns: security tickers (sorted by asset class, then alphabetically)
- Cell color: diverging scale from blue (-1.0, negative correlation) through white (0.0) to red (+1.0, positive correlation)
- Cell text: correlation coefficient (2 decimal places)
- Diagonal: always 1.00 (self-correlation)
- Hover: tooltip showing full security names and exact correlation

**Clustering:** Securities are optionally clustered by correlation (hierarchical clustering) to visually group correlated positions together. Toggle: "Cluster" / "Alphabetical" sorting.

**Below heatmap — Diversification summary:**

- **Diversification ratio**: portfolio volatility / weighted-average individual volatility. Higher is better (> 1.0 means diversification is helping).
- **Average pairwise correlation**: single number summarizing how correlated the portfolio is overall.
- **Most correlated pair**: the two securities with the highest correlation (excluding self), flagged if > 0.8.
- **Least correlated pair**: the two securities with the lowest (or most negative) correlation — the best diversifiers.

### Sub-tab: Stress Tests

**Scenario results table:**

| Scenario | Description | Estimated Loss % | Estimated Loss € | Most Affected | Recovery Time |
|----------|-------------|-------------------|-------------------|---------------|---------------|
| 2008 Financial Crisis | -50% equities, -10% bonds, -20% commodities | -35.2% | -€435,678 | AAPL, MSFT | 4.5 years |
| Rate Shock (+300bp) | Bond prices fall, growth stocks hit, value outperforms | -12.5% | -€154,321 | Bond ETF, Growth stocks | 1.5 years |
| Crypto Winter | -80% crypto, equities flat | -6.4% | -€79,012 | BTC, ETH | 2+ years |
| Stagflation | -20% equities, bonds flat, commodities +20% | -14.8% | -€182,456 | Tech stocks | 3 years |
| Nordic Housing Crisis | Nordic equities -30%, banks -50%, EUR weakness | -18.3% | -€225,678 | Nordea, Sampo | 2 years |

Each row expands on click to show:
- Per-position impact (which holdings lose the most, which gain or are neutral)
- Methodology: how the scenario stress factors were derived (historical analogy, hypothetical)
- Assumptions: duration, recovery path

**Below table — Scenario comparison chart:**

A grouped bar chart showing portfolio loss under each scenario, making it easy to visually compare severity.

### Sub-tab: Concentration

**Top section — Concentration risk indicators (MetricCards):**

| Indicator | Format | Threshold |
|-----------|--------|-----------|
| Largest Position Weight | `AAPL: 4.8%` | Warning if > 5% (per AGENTS.md position limit) |
| Largest Sector Weight | `Technology: 28%` | Warning if > 20% (per AGENTS.md sector limit) |
| Top 5 Holdings Weight | `32.4%` | Informational |
| Herfindahl Index (HHI) | `0.045` | Low (< 0.1), moderate (0.1-0.2), high (> 0.2) |
| Crypto Allocation | `6.2%` | Warning if > 10% (per AGENTS.md crypto limit) |

**Middle section — Concentration breakdown charts (two columns):**

- Left: **By sector** — horizontal bar chart showing weight per GICS sector. Bars colored red if exceeding 20% threshold.
- Right: **By country** — horizontal bar chart showing weight per country of domicile. Highlights home bias if Finland > 20%.

**Bottom section — Position limit violations table:**

Lists any positions or sectors currently exceeding the limits defined in AGENTS.md:

| Rule | Limit | Current | Status |
|------|-------|---------|--------|
| Single stock max | 5% | AAPL: 4.8% | OK |
| Single sector max | 20% | Tech: 28% | VIOLATION |
| Crypto max | 5-10% | 6.2% | OK |

Violations are highlighted in `negative` color with an alert icon.

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `1` | Switch to Metrics sub-tab |
| `2` | Switch to Correlation sub-tab |
| `3` | Switch to Stress Tests sub-tab |
| `4` | Switch to Concentration sub-tab |
| `p` | Cycle through period selections (1Y -> 3Y -> 5Y -> ALL) |

## Business Rules

1. **Minimum data requirement**: Risk metrics require at least 60 trading days of price history to compute. If fewer are available, metrics show `—` with a tooltip: "Insufficient history. {N} days available, 60 required." Full annualized metrics require 252 days.

2. **Benchmark proxy**: MSCI World is the default benchmark. It is proxied by an MSCI World ETF in the `securities` table (e.g., iShares MSCI World UCITS ETF). The user cannot currently add custom benchmarks.

3. **VaR methodology**: VaR 95% is computed using both parametric (normal distribution assumption) and historical simulation. The displayed value is the more conservative (larger loss) of the two methods.

4. **Correlation period**: Correlation is computed using daily returns over the selected period. A minimum of 120 overlapping trading days is required between any pair. Pairs with insufficient overlap show `N/A` in the heatmap.

5. **Stress test methodology**: Scenarios use historical factor shocks applied to current portfolio weights. Per-position impact is estimated from the security's beta to the relevant risk factor (equity market, rates, crypto index). Recovery time is derived from historical analogy.

6. **Concentration limits** follow AGENTS.md constraints: single stock max 5%, single sector max 20%, crypto 5-10% of portfolio. These are monitoring thresholds — the dashboard flags violations but does not prevent trades.

7. **Cache TTL**: Risk metrics are cached in Redis with a 1-hour TTL. Correlation matrices and stress tests are recomputed when the cache expires or when the user changes the period/benchmark.

8. **Computation time**: Full portfolio risk computation must complete within 2 seconds (see architecture performance targets). For portfolios with > 50 positions, the correlation matrix may take longer; a loading spinner is shown.

## Edge Cases

1. **New portfolio (< 60 days of history)**: All risk metrics show `—` with an explanation: "Risk metrics require at least 60 trading days of portfolio history. Your portfolio has {N} days." The Concentration tab still works since it only needs current weights.

2. **Single-security portfolio**: Beta equals the security's own beta. Sharpe/Sortino are computed for the single position. Correlation heatmap shows a 1x1 grid (trivially 1.00). Concentration tab shows 100% in one position, triggering the > 5% warning.

3. **Crypto-only portfolio**: Beta relative to equity benchmarks is meaningless. The dashboard shows a note: "Beta is computed against an equity benchmark and may not be meaningful for crypto-heavy portfolios." Suggest a crypto-specific benchmark if available.

4. **Missing price data for a position**: The security is excluded from risk calculations with a warning: "{ticker} excluded from risk metrics due to missing price data." Remaining positions are still analyzed.

5. **Stale risk cache**: If the cache has expired and recomputation is in progress, show the previous cached values with a "Recalculating..." indicator. Do not show stale metrics without indication.

6. **All positions in one sector**: The concentration tab correctly shows 100% in one sector. The sector bar chart has a single red bar. The HHI is high, flagging concentration risk.

7. **Benchmark data unavailable**: If the MSCI World proxy ETF has no price data, beta and tracking error show `—`. Sharpe and Sortino are still computed using the risk-free rate (from FRED data or a default 3%).

8. **Stress test on an empty portfolio**: All scenarios show 0% loss, 0 EUR. Message: "Add positions to see stress test impact."

## Acceptance Criteria

1. The Metrics sub-tab displays beta, Sharpe, Sortino, VaR 95%, and max drawdown as MetricCards with correct color coding based on thresholds.
2. Changing the period selector (1Y/3Y/5Y/ALL) recomputes and updates all risk metrics.
3. Changing the benchmark selector updates beta, tracking error, and benchmark comparison values.
4. The rolling volatility chart displays portfolio and benchmark volatility over the selected period.
5. The correlation heatmap correctly shows pairwise correlations with a diverging color scale.
6. Clustering mode groups correlated securities together in the heatmap.
7. Diversification summary shows diversification ratio, average pairwise correlation, and most/least correlated pairs.
8. All 5 stress test scenarios display estimated loss (% and absolute), most affected positions, and expandable detail.
9. Concentration indicators correctly flag violations of AGENTS.md position limits (5% stock, 20% sector, 10% crypto).
10. Sector and country concentration bar charts render correctly with threshold violation highlighting.
11. Risk computation completes within 2 seconds for a portfolio with up to 50 positions.
12. Portfolios with insufficient history show appropriate "insufficient data" messages instead of incorrect metrics.
13. Keyboard shortcuts (1-4 for tabs, p for period cycling) work correctly.
14. Metrics are cached and display a loading indicator during recomputation.

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
