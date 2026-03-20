# Portfolio Risk Metrics

Server-side calculation of all portfolio risk metrics used by the Risk Manager and displayed on the Risk Dashboard. Every metric is computed in Python using numpy/scipy, with daily return series from the `prices` hypertable as the primary input. This spec defines the formulas (math notation and Python pseudocode), data requirements, API surface, edge cases, and stress testing scenarios.

**Status: DRAFT**

## Dependencies

- [Spec Conventions](../00-meta/spec-conventions.md) — naming rules, monetary format, date format
- [Data Model](../01-system/data-model.md) — `prices`, `securities`, `holdings_snapshot`, `accounts` tables
- [AGENTS.md](../../AGENTS.md) — Risk Manager role definition, glidepath schedule, position limits

---

## General Conventions

- **Return series**: daily log returns unless stated otherwise: `r_t = ln(P_t / P_{t-1})`
- **Trading days per year**: 252 (stocks/bonds/ETFs), 365 (crypto — markets never close)
- **Base currency**: EUR. All returns are FX-adjusted before calculation.
- **Portfolio returns**: weighted sum of individual holding returns, where weights are beginning-of-day market values.
- **Minimum observations**: 30 trading days unless a metric specifies otherwise.
- **All monetary outputs** follow the cents convention from spec-conventions: integers representing EUR cents, paired with `currency: "EUR"`.

```python
import numpy as np
from scipy import stats

def daily_log_returns(prices: np.ndarray) -> np.ndarray:
    """Compute daily log returns from a price series."""
    return np.log(prices[1:] / prices[:-1])

def portfolio_returns(
    holding_returns: np.ndarray,  # shape (n_days, n_holdings)
    weights: np.ndarray,          # shape (n_holdings,) — beginning-of-day weights
) -> np.ndarray:
    """Weighted portfolio return series."""
    return holding_returns @ weights
```

---

## 1. Portfolio Beta

The sensitivity of portfolio returns to a benchmark index.

### Formula

$$\beta = \frac{\text{Cov}(R_p, R_m)}{\text{Var}(R_m)}$$

**Weighted portfolio beta** (alternative — faster, no portfolio return series needed):

$$\beta_p = \sum_{i=1}^{n} w_i \cdot \beta_i$$

### Benchmarks

| Benchmark | Ticker | Use Case |
|-----------|--------|----------|
| MSCI World | `URTH` or `IWDA.AS` | Default for global portfolio |
| OMXH25 | `^OMXH25` | Finnish stock holdings |
| S&P 500 | `^GSPC` | US stock holdings |

The system calculates beta against all three benchmarks. The primary beta displayed on the dashboard uses MSCI World.

### Parameters

| Parameter | Default | Range |
|-----------|---------|-------|
| Lookback period | 252 trading days (1 year) | 30–1260 days |
| Return frequency | Daily | Daily only |

### Python Pseudocode

```python
def calculate_beta(
    portfolio_returns: np.ndarray,
    benchmark_returns: np.ndarray,
) -> float:
    """
    Calculate portfolio beta against a benchmark.
    Both inputs are daily log return arrays of equal length.
    """
    covariance = np.cov(portfolio_returns, benchmark_returns)[0, 1]
    benchmark_variance = np.var(benchmark_returns, ddof=1)
    return covariance / benchmark_variance

def weighted_portfolio_beta(
    holding_betas: np.ndarray,  # beta of each holding vs benchmark
    weights: np.ndarray,        # portfolio weight of each holding
) -> float:
    """Sum-of-weighted-betas approach."""
    return float(np.dot(weights, holding_betas))
```

### Worked Example

A portfolio with 3 holdings:

| Holding | Weight | Beta (vs MSCI World) |
|---------|--------|---------------------|
| IWDA.AS (World ETF) | 0.60 | 1.00 |
| NOKIA.HE | 0.25 | 1.35 |
| BTC | 0.15 | 1.80 |

$$\beta_p = 0.60 \times 1.00 + 0.25 \times 1.35 + 0.15 \times 1.80 = 0.60 + 0.3375 + 0.27 = 1.2075$$

Portfolio beta = **1.21** — the portfolio is 21% more volatile than the benchmark.

---

## 2. Sharpe Ratio

Risk-adjusted return: excess return per unit of total volatility.

### Formula

$$\text{Sharpe} = \frac{R_p - R_f}{\sigma_p}$$

**Annualized from daily returns:**

$$\text{Sharpe}_{\text{annual}} = \frac{\bar{r}_{\text{daily}} - r_{f,\text{daily}}}{\sigma_{\text{daily}}} \times \sqrt{252}$$

### Risk-Free Rate Sources

| Source | Identifier | Description |
|--------|------------|-------------|
| ECB deposit facility rate | ECB SDW series `FM.D.U2.EUR.4F.KR.DFR.LEV` | Current short-term risk-free proxy |
| German 10Y bund yield | FRED series `IRLTLT01DEM156N` | Long-term risk-free proxy |

Default: ECB deposit facility rate, converted to daily rate as `r_f_daily = (1 + r_f_annual)^(1/252) - 1`.

### Parameters

| Parameter | Default | Range |
|-----------|---------|-------|
| Lookback period | 252 trading days | 30–1260 days |
| Risk-free rate | ECB deposit facility rate | Configurable |
| Minimum observations | 30 trading days | — |

### Python Pseudocode

```python
def calculate_sharpe(
    portfolio_returns: np.ndarray,
    risk_free_annual: float,
    trading_days: int = 252,
) -> float:
    """
    Annualized Sharpe ratio from daily log returns.
    risk_free_annual: e.g., 0.04 for 4%.
    """
    rf_daily = (1 + risk_free_annual) ** (1 / trading_days) - 1
    excess_returns = portfolio_returns - rf_daily
    return float(
        np.mean(excess_returns) / np.std(excess_returns, ddof=1) * np.sqrt(trading_days)
    )
```

### Worked Example

- Portfolio mean daily return: 0.04% (0.0004)
- Daily std deviation: 0.95% (0.0095)
- ECB deposit facility rate: 3.50% annual -> daily rate: 0.0137% (0.000137)

$$\text{Sharpe} = \frac{0.0004 - 0.000137}{0.0095} \times \sqrt{252} = \frac{0.000263}{0.0095} \times 15.875 = 0.0277 \times 15.875 = \mathbf{0.44}$$

Interpretation: 0.44 units of excess return per unit of risk. Generally: < 0.5 poor, 0.5–1.0 acceptable, > 1.0 good, > 2.0 exceptional.

---

## 3. Sortino Ratio

Like Sharpe, but penalizes only downside volatility. Better for portfolios with asymmetric return distributions (e.g., those including crypto or concentrated positions).

### Formula

$$\text{Sortino} = \frac{R_p - R_f}{\sigma_{\text{downside}}}$$

Where:

$$\sigma_{\text{downside}} = \sqrt{\frac{1}{n} \sum_{i=1}^{n} \min(R_i - R_f, 0)^2}$$

### Python Pseudocode

```python
def calculate_sortino(
    portfolio_returns: np.ndarray,
    risk_free_annual: float,
    trading_days: int = 252,
) -> float:
    """Annualized Sortino ratio from daily log returns."""
    rf_daily = (1 + risk_free_annual) ** (1 / trading_days) - 1
    excess_returns = portfolio_returns - rf_daily
    downside_returns = np.minimum(excess_returns, 0)
    downside_std = np.sqrt(np.mean(downside_returns ** 2))
    return float(np.mean(excess_returns) / downside_std * np.sqrt(trading_days))
```

### Worked Example

Using the same portfolio as the Sharpe example, but now 60% of daily returns are positive (asymmetric):

- Mean daily excess return: 0.000263
- Downside deviation (daily): 0.0068 (lower than full std of 0.0095 because upside volatility is excluded)

$$\text{Sortino} = \frac{0.000263}{0.0068} \times \sqrt{252} = 0.0387 \times 15.875 = \mathbf{0.61}$$

The Sortino (0.61) is higher than the Sharpe (0.44), indicating the portfolio's volatility is skewed to the upside — a favorable asymmetry.

---

## 4. Value at Risk (VaR)

The maximum expected loss at a given confidence level over a given time horizon.

### 4a. Parametric VaR (Normal Distribution)

#### Formula

$$\text{VaR}_{\alpha} = \mu - z_{\alpha} \cdot \sigma$$

| Confidence Level | z-score ($z_\alpha$) |
|-----------------|----------------------|
| 95% | 1.645 |
| 99% | 2.326 |

**Time-horizon scaling** (square-root-of-time rule for parametric):

$$\text{VaR}_{t\text{-day}} = \text{VaR}_{1\text{-day}} \times \sqrt{t}$$

### 4b. Historical Simulation VaR

Sort actual daily returns and take the percentile cutoff directly. No distribution assumption.

$$\text{VaR}_{95\%}^{\text{hist}} = -\text{Percentile}(R, 5)$$
$$\text{VaR}_{99\%}^{\text{hist}} = -\text{Percentile}(R, 1)$$

### Reporting Matrix

| Method | Confidence | Horizon | Output |
|--------|-----------|---------|--------|
| Parametric | 95% | 1-day | % loss and EUR amount |
| Parametric | 99% | 1-day | % loss and EUR amount |
| Parametric | 95% | 1-month (21 days) | % loss and EUR amount |
| Parametric | 99% | 1-month (21 days) | % loss and EUR amount |
| Historical | 95% | 1-day | % loss and EUR amount |
| Historical | 99% | 1-day | % loss and EUR amount |
| Historical | 95% | 1-month (21 days) | % loss and EUR amount |
| Historical | 99% | 1-month (21 days) | % loss and EUR amount |

EUR amount = VaR percentage x current portfolio market value. Stored as integer cents.

### Python Pseudocode

```python
def parametric_var(
    portfolio_returns: np.ndarray,
    confidence: float = 0.95,
    horizon_days: int = 1,
) -> float:
    """
    Parametric (normal) VaR as a positive percentage loss.
    Returns: e.g., 0.023 meaning 2.3% loss.
    """
    mu = np.mean(portfolio_returns)
    sigma = np.std(portfolio_returns, ddof=1)
    z = stats.norm.ppf(1 - confidence)  # negative
    var_1d = -(mu + z * sigma)          # flip sign: positive = loss
    return float(var_1d * np.sqrt(horizon_days))

def historical_var(
    portfolio_returns: np.ndarray,
    confidence: float = 0.95,
    horizon_days: int = 1,
) -> float:
    """
    Historical simulation VaR as a positive percentage loss.
    For multi-day horizon, uses rolling sum of daily returns.
    """
    if horizon_days == 1:
        returns = portfolio_returns
    else:
        # Rolling t-day returns via convolution
        returns = np.convolve(
            portfolio_returns, np.ones(horizon_days), mode="valid"
        )
    percentile = (1 - confidence) * 100  # e.g., 5 for 95% confidence
    return float(-np.percentile(returns, percentile))

def var_eur_amount(var_pct: float, portfolio_value_cents: int) -> int:
    """Convert VaR percentage to EUR cents."""
    return int(round(var_pct * portfolio_value_cents))
```

### Worked Example

Portfolio value: 250,000 EUR. Daily returns: mean 0.04%, std 0.95%.

**Parametric VaR (95%, 1-day):**

$$\text{VaR} = -(0.0004 + (-1.645) \times 0.0095) = -(0.0004 - 0.01563) = 0.01523 = 1.52\%$$

Loss = 1.52% x 250,000 EUR = **3,808 EUR**

**Parametric VaR (95%, 1-month / 21 days):**

$$\text{VaR}_{21} = 0.01523 \times \sqrt{21} = 0.01523 \times 4.583 = 0.0698 = 6.98\%$$

Loss = 6.98% x 250,000 EUR = **17,450 EUR**

---

## 5. Maximum Drawdown

The largest peak-to-trough decline in portfolio value over a given period.

### Formula

$$\text{MDD} = \frac{\text{Peak} - \text{Trough}}{\text{Peak}}$$

Where Peak is the running maximum of the cumulative return series, and Trough is the subsequent minimum before a new peak is reached.

### Reporting Windows

| Window | Description |
|--------|-------------|
| Rolling 1Y | Max drawdown over trailing 252 trading days |
| Rolling 3Y | Max drawdown over trailing 756 trading days |
| Rolling 5Y | Max drawdown over trailing 1260 trading days |
| Since inception | Max drawdown over the entire portfolio history |
| Current drawdown | Distance from current all-time high to current value |

For each window, track:
- **Drawdown percentage** (e.g., -15.3%)
- **Peak date** (when the high was reached)
- **Trough date** (when the low was reached)
- **Recovery date** (when the portfolio regained the peak level, or `null` if not yet recovered)

### Python Pseudocode

```python
from dataclasses import dataclass
from datetime import date
from typing import Optional

@dataclass
class DrawdownResult:
    drawdown_pct: float          # e.g., 0.153 for 15.3%
    peak_date: date
    trough_date: date
    recovery_date: Optional[date]

def calculate_max_drawdown(
    cumulative_values: np.ndarray,  # portfolio value series (e.g., in cents)
    dates: list[date],
) -> DrawdownResult:
    """
    Calculate maximum drawdown from a portfolio value series.
    cumulative_values and dates must have the same length.
    """
    running_max = np.maximum.accumulate(cumulative_values)
    drawdowns = (cumulative_values - running_max) / running_max

    trough_idx = int(np.argmin(drawdowns))
    peak_idx = int(np.argmax(cumulative_values[:trough_idx + 1]))

    # Find recovery: first index after trough where value >= peak value
    recovery_idx = None
    peak_value = cumulative_values[peak_idx]
    for i in range(trough_idx + 1, len(cumulative_values)):
        if cumulative_values[i] >= peak_value:
            recovery_idx = i
            break

    return DrawdownResult(
        drawdown_pct=float(-drawdowns[trough_idx]),
        peak_date=dates[peak_idx],
        trough_date=dates[trough_idx],
        recovery_date=dates[recovery_idx] if recovery_idx is not None else None,
    )

def current_drawdown(cumulative_values: np.ndarray) -> float:
    """Distance from all-time high as a positive fraction."""
    ath = np.max(cumulative_values)
    current = cumulative_values[-1]
    return float((ath - current) / ath)
```

### Worked Example

Portfolio value series over 1 year:
- Peak: 280,000 EUR on 2025-09-15
- Trough: 237,200 EUR on 2025-12-20
- Current: 260,000 EUR (not yet recovered)

$$\text{MDD} = \frac{280{,}000 - 237{,}200}{280{,}000} = \frac{42{,}800}{280{,}000} = \mathbf{15.29\%}$$

Current drawdown from ATH: (280,000 - 260,000) / 280,000 = **7.14%**

---

## 6. Volatility

Annualized standard deviation of returns, the most fundamental measure of portfolio risk.

### Formula

$$\sigma_{\text{annual}} = \sigma_{\text{daily}} \times \sqrt{N}$$

Where $N$ = 252 for stocks/bonds/ETFs or 365 for crypto.

### Rolling Windows

| Window | Days | Description |
|--------|------|-------------|
| 30-day | 30 | Short-term / recent volatility |
| 90-day | 90 | Medium-term volatility |
| 1-year | 252 | Standard annual volatility |

Calculated at both per-holding and portfolio level.

### Python Pseudocode

```python
def annualized_volatility(
    daily_returns: np.ndarray,
    trading_days: int = 252,
) -> float:
    """Annualized volatility from daily log returns."""
    return float(np.std(daily_returns, ddof=1) * np.sqrt(trading_days))

def rolling_volatility(
    daily_returns: np.ndarray,
    window: int,
    trading_days: int = 252,
) -> np.ndarray:
    """Rolling annualized volatility. Output length = len(daily_returns) - window + 1."""
    result = np.empty(len(daily_returns) - window + 1)
    for i in range(len(result)):
        result[i] = np.std(daily_returns[i : i + window], ddof=1) * np.sqrt(trading_days)
    return result
```

### Worked Example

A holding with daily return std of 1.8%:

$$\sigma_{\text{annual}} = 0.018 \times \sqrt{252} = 0.018 \times 15.875 = \mathbf{28.58\%}$$

For context: S&P 500 long-term annual volatility is roughly 15–17%. A 28.58% reading suggests a high-volatility holding (individual growth stock or crypto).

---

## 7. Correlation Matrix

Pairwise Pearson correlation between all holdings' return series, used for diversification analysis.

### Formula

$$\rho_{i,j} = \frac{\text{Cov}(R_i, R_j)}{\sigma_i \cdot \sigma_j}$$

### Rules

| Rule | Threshold | Action |
|------|-----------|--------|
| High correlation | $\rho > 0.8$ | Flag as diversification concern (red highlight in UI) |
| Moderate correlation | $0.5 < \rho \leq 0.8$ | Informational (yellow) |
| Low correlation | $-0.3 \leq \rho \leq 0.5$ | Normal (no highlight) |
| Negative correlation | $\rho < -0.3$ | Flag as good diversifier (green highlight in UI) |
| Minimum overlap | 30 days | Do not compute correlation for pairs with fewer overlapping observations |

### Python Pseudocode

```python
@dataclass
class CorrelationMatrix:
    matrix: np.ndarray           # shape (n, n)
    labels: list[str]            # security tickers, length n
    observation_counts: np.ndarray  # shape (n, n) — pairwise overlap counts

def calculate_correlation_matrix(
    returns_dict: dict[str, np.ndarray],  # ticker -> daily returns (may differ in length)
    min_overlap: int = 30,
) -> CorrelationMatrix:
    """
    Compute pairwise Pearson correlation for all holdings.
    Handles different-length series by aligning on dates.
    Returns NaN for pairs with < min_overlap observations.
    """
    tickers = sorted(returns_dict.keys())
    n = len(tickers)
    matrix = np.full((n, n), np.nan)
    counts = np.zeros((n, n), dtype=int)

    for i in range(n):
        matrix[i, i] = 1.0
        counts[i, i] = len(returns_dict[tickers[i]])
        for j in range(i + 1, n):
            # Align series on overlapping dates (handled by caller)
            ri, rj = _align_returns(returns_dict[tickers[i]], returns_dict[tickers[j]])
            overlap = len(ri)
            counts[i, j] = counts[j, i] = overlap
            if overlap >= min_overlap:
                corr = float(np.corrcoef(ri, rj)[0, 1])
                matrix[i, j] = matrix[j, i] = corr

    return CorrelationMatrix(matrix=matrix, labels=tickers, observation_counts=counts)
```

### Visualization Data

The API returns the correlation matrix as a JSON structure for the frontend heatmap:

```json
{
  "labels": ["IWDA.AS", "NOKIA.HE", "BTC", "VGEA.DE", "SAMPO.HE"],
  "matrix": [
    [1.00, 0.62, 0.35, -0.15, 0.71],
    [0.62, 1.00, 0.28, -0.08, 0.85],
    [0.35, 0.28, 1.00, -0.22, 0.30],
    [-0.15, -0.08, -0.22, 1.00, -0.10],
    [0.71, 0.85, 0.30, -0.10, 1.00]
  ],
  "flags": [
    {"i": 1, "j": 4, "type": "high_correlation", "value": 0.85}
  ]
}
```

In this example, NOKIA.HE and SAMPO.HE have correlation 0.85 — flagged as a diversification concern (both are Finnish large-caps).

---

## 8. Stress Testing

Predefined shock scenarios applied to current portfolio weights to estimate potential losses.

### Scenario Definitions

| Scenario | Equity Shock | Bond Shock | Crypto Shock | FX (EUR/USD) | Description |
|----------|-------------|------------|-------------|---------------|-------------|
| 2008 GFC | -50% | +10% | N/A | -15% | Global financial crisis replay |
| Rate Shock | -15% | -20% | -10% | +5% | Sudden rate hike (+300bps) |
| Crypto Winter | 0% | 0% | -80% | 0% | Crypto-specific crash |
| Stagflation | -25% | -15% | -30% | -10% | High inflation + recession |
| Nordic Housing | -20% | -5% | -15% | -5% | Nordic-specific downturn |
| EUR Crisis | -30% | -25% | +10% | -20% | Eurozone sovereign debt crisis |
| Black Monday | -22% | +5% | -30% | -5% | Single-day flash crash |

**N/A handling**: Crypto did not exist during the 2008 GFC. For that scenario, apply -50% to crypto (assume it would behave as a high-beta risk asset).

**FX shock**: applies to all non-EUR denominated holdings. A -15% EUR/USD shock means EUR weakens — USD holdings gain 15% in EUR terms (partially offsetting equity losses).

### Calculation Method

For each scenario:

1. Classify each holding by asset class (`securities.asset_class`).
2. Apply the corresponding shock percentage to the holding's current market value.
3. For non-EUR holdings, apply the FX shock on top.
4. Sum the shocked values to get the post-scenario portfolio value.
5. Report: total portfolio loss (% and EUR cents), per-holding loss, worst-affected holdings (top 5).

### Python Pseudocode

```python
@dataclass
class ScenarioShocks:
    equity: float    # e.g., -0.50 for -50%
    bond: float
    crypto: float
    fx_eur_usd: float

SCENARIOS: dict[str, ScenarioShocks] = {
    "2008_gfc":        ScenarioShocks(equity=-0.50, bond=0.10,  crypto=-0.50, fx_eur_usd=-0.15),
    "rate_shock":      ScenarioShocks(equity=-0.15, bond=-0.20, crypto=-0.10, fx_eur_usd=0.05),
    "crypto_winter":   ScenarioShocks(equity=0.00,  bond=0.00,  crypto=-0.80, fx_eur_usd=0.00),
    "stagflation":     ScenarioShocks(equity=-0.25, bond=-0.15, crypto=-0.30, fx_eur_usd=-0.10),
    "nordic_housing":  ScenarioShocks(equity=-0.20, bond=-0.05, crypto=-0.15, fx_eur_usd=-0.05),
    "eur_crisis":      ScenarioShocks(equity=-0.30, bond=-0.25, crypto=0.10,  fx_eur_usd=-0.20),
    "black_monday":    ScenarioShocks(equity=-0.22, bond=0.05,  crypto=-0.30, fx_eur_usd=-0.05),
}

@dataclass
class StressTestResult:
    scenario_name: str
    portfolio_loss_pct: float          # positive = loss
    portfolio_loss_cents: int          # EUR cents
    holding_impacts: list[dict]        # [{security_id, ticker, loss_pct, loss_cents}, ...]
    worst_affected: list[dict]         # top 5 by absolute loss

def run_stress_test(
    holdings: list[dict],  # [{security_id, ticker, asset_class, currency, market_value_cents}, ...]
    scenario: ScenarioShocks,
    scenario_name: str,
) -> StressTestResult:
    """Apply a shock scenario to current holdings."""
    total_value = sum(h["market_value_cents"] for h in holdings)
    total_loss = 0
    impacts = []

    for h in holdings:
        # Select shock by asset class
        shock_map = {"stock": scenario.equity, "etf": scenario.equity,
                     "bond": scenario.bond, "crypto": scenario.crypto}
        asset_shock = shock_map[h["asset_class"]]

        # FX adjustment for non-EUR holdings
        fx_adjustment = 0.0
        if h["currency"] != "EUR":
            # EUR weakening = foreign holdings gain value in EUR terms
            fx_adjustment = -scenario.fx_eur_usd  # flip sign: EUR weakness is positive for foreign assets

        combined_shock = asset_shock + fx_adjustment + (asset_shock * fx_adjustment)
        loss_cents = int(round(h["market_value_cents"] * -combined_shock))
        total_loss += loss_cents

        impacts.append({
            "security_id": h["security_id"],
            "ticker": h["ticker"],
            "loss_pct": -combined_shock,
            "loss_cents": loss_cents,
        })

    # Sort by absolute loss descending
    impacts.sort(key=lambda x: abs(x["loss_cents"]), reverse=True)

    return StressTestResult(
        scenario_name=scenario_name,
        portfolio_loss_pct=total_loss / total_value if total_value > 0 else 0,
        portfolio_loss_cents=total_loss,
        holding_impacts=impacts,
        worst_affected=impacts[:5],
    )
```

### Worked Example

Portfolio: 250,000 EUR total.

| Holding | Asset Class | Currency | Weight | Value (EUR) |
|---------|------------|----------|--------|-------------|
| IWDA.AS | ETF | EUR | 50% | 125,000 |
| AAPL | Stock | USD | 20% | 50,000 |
| VGEA.DE | Bond ETF | EUR | 15% | 37,500 |
| BTC | Crypto | USD | 10% | 25,000 |
| SAMPO.HE | Stock | EUR | 5% | 12,500 |

**Scenario: 2008 GFC** (equity -50%, bond +10%, crypto -50%, FX EUR/USD -15%):

| Holding | Asset Shock | FX Effect | Combined | Loss (EUR) |
|---------|------------|-----------|----------|------------|
| IWDA.AS | -50% | 0% (EUR) | -50% | -62,500 |
| AAPL | -50% | +15% (EUR weakens) | -42.5% | -21,250 |
| VGEA.DE | +10% | 0% (EUR) | +10% | +3,750 |
| BTC | -50% | +15% | -42.5% | -10,625 |
| SAMPO.HE | -50% | 0% (EUR) | -50% | -6,250 |
| **Total** | | | | **-96,875** |

Portfolio loss: **38.75%** / **96,875 EUR**

---

## 9. Concentration Risk

Measures how concentrated the portfolio is across individual positions, sectors, geographies, and asset classes.

### 9a. Herfindahl-Hirschman Index (HHI)

$$\text{HHI} = \sum_{i=1}^{n} w_i^2$$

Where $w_i$ is the portfolio weight of holding $i$ (as a decimal, not percentage).

| HHI Range | Interpretation |
|-----------|---------------|
| < 0.10 | Well diversified |
| 0.10 – 0.25 | Moderately concentrated |
| > 0.25 | Highly concentrated |

A perfectly equal-weighted portfolio of 20 holdings: HHI = 20 x (0.05)^2 = 0.05.

### 9b. Position Limit Checks

| Check | Threshold | Alert Level |
|-------|-----------|-------------|
| Single position | > 5% of portfolio | Warning |
| Single position | > 10% of portfolio | Critical |
| Single sector | > 20% of portfolio | Warning |
| Single sector | > 30% of portfolio | Critical |
| Single country | > 40% of portfolio | Warning |
| Asset class vs glidepath | > 5% drift from target | Warning (see [AGENTS.md](../../AGENTS.md) glidepath schedule) |
| Crypto allocation | > 10% of portfolio | Critical (per policy) |

### Python Pseudocode

```python
@dataclass
class ConcentrationAlert:
    level: str       # "warning" or "critical"
    category: str    # "position", "sector", "country", "asset_class"
    name: str        # e.g., "AAPL", "Technology", "US"
    weight_pct: float
    threshold_pct: float

def calculate_hhi(weights: np.ndarray) -> float:
    """Herfindahl-Hirschman Index."""
    return float(np.sum(weights ** 2))

def check_concentration_limits(
    holdings: list[dict],  # [{ticker, weight, sector, country, asset_class}, ...]
    glidepath_targets: dict[str, float],  # {"stock": 0.45, "etf": 0.30, ...}
) -> list[ConcentrationAlert]:
    """Check all concentration limits and return alerts."""
    alerts = []

    # Single position checks
    for h in holdings:
        if h["weight"] > 0.10:
            alerts.append(ConcentrationAlert("critical", "position", h["ticker"],
                                             h["weight"] * 100, 10.0))
        elif h["weight"] > 0.05:
            alerts.append(ConcentrationAlert("warning", "position", h["ticker"],
                                             h["weight"] * 100, 5.0))

    # Sector aggregation
    sector_weights: dict[str, float] = {}
    for h in holdings:
        sector_weights[h["sector"]] = sector_weights.get(h["sector"], 0) + h["weight"]
    for sector, weight in sector_weights.items():
        if weight > 0.30:
            alerts.append(ConcentrationAlert("critical", "sector", sector,
                                             weight * 100, 30.0))
        elif weight > 0.20:
            alerts.append(ConcentrationAlert("warning", "sector", sector,
                                             weight * 100, 20.0))

    # Asset class vs glidepath
    class_weights: dict[str, float] = {}
    for h in holdings:
        class_weights[h["asset_class"]] = class_weights.get(h["asset_class"], 0) + h["weight"]
    for ac, target in glidepath_targets.items():
        actual = class_weights.get(ac, 0)
        if abs(actual - target) > 0.05:
            alerts.append(ConcentrationAlert("warning", "asset_class", ac,
                                             actual * 100, target * 100))

    return alerts
```

### Worked Example

Using the 5-holding portfolio from the stress test example:

$$\text{HHI} = 0.50^2 + 0.20^2 + 0.15^2 + 0.10^2 + 0.05^2 = 0.25 + 0.04 + 0.0225 + 0.01 + 0.0025 = \mathbf{0.325}$$

HHI = 0.325 — **highly concentrated**. The 50% IWDA.AS position dominates. Alerts:
- CRITICAL: IWDA.AS at 50% (> 10% threshold)
- WARNING: AAPL at 20% (> 5% threshold)
- WARNING: VGEA.DE at 15% (> 5% threshold)
- WARNING: BTC at 10% (> 5% threshold)

Note: IWDA.AS is a broad world index ETF, so the high concentration is less concerning than it would be for a single stock. The UI should distinguish between diversified ETFs and individual securities in its concentration warnings.

---

## 10. Risk-Adjusted Return Metrics

Additional ratios that complement Sharpe and Sortino.

### 10a. Information Ratio

Measures active return relative to tracking error (the volatility of the difference between portfolio and benchmark returns).

$$\text{IR} = \frac{R_p - R_b}{\sigma_{R_p - R_b}}$$

Where $R_b$ is the benchmark return and $\sigma_{R_p - R_b}$ is the tracking error.

### 10b. Treynor Ratio

Excess return per unit of systematic risk (beta).

$$\text{Treynor} = \frac{R_p - R_f}{\beta_p}$$

### 10c. Calmar Ratio

Annualized return divided by maximum drawdown. Useful for evaluating long-term risk-adjusted performance.

$$\text{Calmar} = \frac{R_{\text{annualized}}}{\text{MDD}}$$

### Python Pseudocode

```python
def information_ratio(
    portfolio_returns: np.ndarray,
    benchmark_returns: np.ndarray,
    trading_days: int = 252,
) -> float:
    """Annualized information ratio."""
    active_returns = portfolio_returns - benchmark_returns
    return float(
        np.mean(active_returns) / np.std(active_returns, ddof=1) * np.sqrt(trading_days)
    )

def treynor_ratio(
    portfolio_return_annual: float,
    risk_free_annual: float,
    portfolio_beta: float,
) -> float:
    """Treynor ratio. Undefined if beta = 0."""
    if portfolio_beta == 0:
        return float("inf") if portfolio_return_annual > risk_free_annual else float("-inf")
    return (portfolio_return_annual - risk_free_annual) / portfolio_beta

def calmar_ratio(
    annualized_return: float,
    max_drawdown: float,
) -> float:
    """Calmar ratio. max_drawdown is a positive fraction (e.g., 0.15 for 15%)."""
    if max_drawdown == 0:
        return float("inf") if annualized_return > 0 else 0.0
    return annualized_return / max_drawdown
```

### Worked Example

Portfolio: 12% annualized return, 15.29% max drawdown, beta 1.21, risk-free 3.5%.

- **Treynor**: (0.12 - 0.035) / 1.21 = 0.085 / 1.21 = **0.070** (7.0% excess return per unit of beta)
- **Calmar**: 0.12 / 0.1529 = **0.785** (generally: > 1.0 is good, > 3.0 is excellent)
- **Information Ratio**: assuming 10% benchmark return and 5% tracking error: (0.12 - 0.10) / 0.05 = **0.40** (generally: > 0.5 is good, > 1.0 is exceptional)

---

## API Endpoints

All risk metrics are served via the FastAPI backend. See API: `getRiskMetrics`, `getCorrelationMatrix`, `getStressTests`, `getConcentrationAlerts`.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/risk/summary` | GET | All key metrics (beta, Sharpe, Sortino, VaR, MDD, volatility) |
| `/api/v1/risk/var` | GET | Detailed VaR (both methods, all confidence/horizon combos) |
| `/api/v1/risk/drawdown` | GET | Drawdown history with peak/trough/recovery dates |
| `/api/v1/risk/correlation` | GET | NxN correlation matrix with labels and flags |
| `/api/v1/risk/stress-test` | GET | All scenario results; query param `?scenario=2008_gfc` for single |
| `/api/v1/risk/concentration` | GET | HHI, position/sector/country/asset-class alerts |
| `/api/v1/risk/volatility` | GET | Rolling volatility series (30d, 90d, 1y) per holding and portfolio |

### Common Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `lookbackDays` | int | 252 | Number of trading days for calculation window |
| `benchmark` | string | `msci_world` | Benchmark for beta/IR: `msci_world`, `omxh25`, `sp500` |
| `confidenceLevel` | float | 0.95 | For VaR: 0.95 or 0.99 |

### Response Format

All responses follow the standard envelope:

```json
{
  "data": { ... },
  "meta": {
    "calculatedAt": "2026-03-19T14:30:00Z",
    "lookbackDays": 252,
    "tradingDaysAvailable": 248,
    "benchmark": "msci_world"
  }
}
```

---

## Caching and Refresh

- Risk metrics are recalculated **once daily** after market close (triggered by the nightly `holdings_snapshot` rebuild).
- Cached in Redis with key pattern `risk:{metric}:{params_hash}`.
- TTL: until next market close + 1 hour grace.
- On-demand recalculation available via query param `?refresh=true` (rate-limited to 1 per minute).

---

## Edge Cases

1. **Insufficient data**: If a holding has fewer than 30 days of price history, exclude it from correlation matrix and per-holding risk metrics. Include its weight in portfolio-level calculations using available data. Return a `dataQuality` warning in the API response.

2. **New holding (zero history)**: Use the holding's market value for concentration and stress test calculations but mark all return-based metrics as `null` with reason `"insufficient_history"`.

3. **Delisted security**: Use the last available price. Flag as stale in the response. The holding still contributes its frozen market value to concentration metrics.

4. **Crypto weekends**: Crypto trades 365 days/year. When mixing crypto and traditional holdings in portfolio returns, align on calendar days and fill non-trading days for stocks/bonds with the previous close (zero return).

5. **Missing price data (gaps)**: Forward-fill the last known price for up to 5 trading days. Beyond 5 days, mark the security as stale and exclude from return-based calculations.

6. **Division by zero in ratios**: If the denominator is zero (e.g., beta with zero benchmark variance, Sharpe with zero volatility), return `null` with reason `"zero_denominator"`. Do not return infinity.

7. **Single-holding portfolio**: Beta and correlation are computable but degenerate. HHI = 1.0 (maximum concentration). Flag as critical concentration alert.

8. **Negative Sharpe/Sortino**: Report as-is. A negative Sharpe means the portfolio underperformed the risk-free rate. Do not clamp to zero.

9. **VaR exceedance**: When actual daily loss exceeds VaR estimate, log it for backtesting purposes. Track the VaR exceedance rate: at 95% confidence, expect roughly 5% of days to exceed. If exceedance rate is significantly higher, flag the model as unreliable.

10. **Currency conversion timing**: Use the same-day FX rate for return calculations. If the FX rate is missing for a given day, use the most recent available rate.

11. **ETF classification in stress tests**: ETFs are classified by their underlying asset class — a bond ETF (e.g., VGEA.DE) receives the bond shock, not the equity shock. Classification is based on `securities.asset_class`, where bond ETFs should be stored as `etf` with sector indicating fixed income. The stress test engine must handle this mapping explicitly.

---

## Open Questions

- Should we implement Conditional VaR (CVaR / Expected Shortfall) alongside VaR? CVaR gives the expected loss beyond the VaR threshold and is considered a more coherent risk measure.
- Should stress test scenarios be user-customizable, or only the predefined set?
- Should we add a Monte Carlo VaR method in addition to parametric and historical?

---

## Changelog

| Date | Change |
|------|--------|
| 2026-03-19 | Initial draft |
