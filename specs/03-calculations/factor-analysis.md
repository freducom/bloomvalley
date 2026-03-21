# Fama-French Factor Analysis

Decompose portfolio and per-holding returns into systematic factor exposures using the Fama-French five-factor model. This spec covers factor data ingestion from the Kenneth French Data Library, OLS regression for factor loadings, rolling exposure analysis, return attribution by factor, Sharpe style analysis, and factor timing drift detection. All computations are server-side in Python using numpy and scipy. The goal is to answer: "How much of my return is alpha, and how much is explained by known risk factors?"

**Status: DRAFT**

## Dependencies

- [Spec Conventions](../00-meta/spec-conventions.md) — naming rules, monetary format, date format
- [Data Model](../01-system/data-model.md) — `prices`, `securities`, `holdings_snapshot`, `accounts` tables
- [Portfolio Math](../03-calculations/portfolio-math.md) — daily return series, portfolio valuation, TWR
- [Risk Metrics](../03-calculations/risk-metrics.md) — volatility, beta, Sharpe ratio (factor analysis extends these)
- [AGENTS.md](../../AGENTS.md) — Risk Manager and Quant Analyst role definitions

---

## General Conventions

- **Return series**: daily simple returns (not log returns) to match French Data Library convention: `r_t = (P_t - P_{t-1}) / P_{t-1}`
- **Factor returns**: expressed as decimals (e.g., 0.0012 for 0.12% daily return)
- **Base currency**: EUR. All portfolio/holding returns are FX-adjusted to EUR before regression.
- **Risk-free rate**: sourced from the French Data Library `RF` column (US T-bill rate) for US factor regressions, and from ECB deposit facility rate for European factor regressions.
- **Minimum observations**: 60 trading days for any regression. Rolling regressions require `window` observations.
- **All monetary outputs** follow the cents convention: integers representing EUR cents, paired with `currency: "EUR"`.

```python
import numpy as np
from scipy import optimize
from dataclasses import dataclass
from datetime import date
from typing import Optional
```

---

## 1. Data Source: Kenneth French Data Library

### 1.1 Available Factor Sets

The Kenneth French Data Library provides pre-computed factor return series. Two regional sets are relevant:

| Factor Set | URL Pattern | Description | Use Case |
|------------|-------------|-------------|----------|
| US Fama-French 5 Factors (Daily) | `F-F_Research_Data_5_Factors_2x3_daily_CSV.zip` | US market factors | US-listed holdings |
| European Fama-French 5 Factors (Daily) | `Europe_5_Factors_Daily_CSV.zip` | European market factors | Finnish/Nordic/European holdings |
| US Fama-French 5 Factors (Monthly) | `F-F_Research_Data_5_Factors_2x3_CSV.zip` | US market factors (monthly) | Long-horizon regressions |
| European Fama-French 5 Factors (Monthly) | `Europe_5_Factors_CSV.zip` | European market factors (monthly) | Long-horizon regressions |

**Base URL**: `https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/`

### 1.2 Factor Definitions

| Factor | Name | Construction | Interpretation |
|--------|------|-------------|----------------|
| MKT | Market Excess Return | $R_m - R_f$ (value-weighted market return minus risk-free rate) | Compensation for bearing market risk |
| SMB | Small Minus Big | Return of small-cap portfolio minus large-cap portfolio | Size premium: small companies tend to outperform |
| HML | High Minus Low | Return of high book-to-market portfolio minus low book-to-market portfolio | Value premium: cheap stocks tend to outperform |
| RMW | Robust Minus Weak | Return of high operating profitability portfolio minus low profitability portfolio | Profitability premium: profitable firms outperform |
| CMA | Conservative Minus Aggressive | Return of low investment firms minus high investment firms | Investment premium: conservative investors outperform |
| RF | Risk-Free Rate | US T-bill rate (daily or monthly) | Benchmark for excess returns |

### 1.3 Data Pipeline: `french_factors`

A new pipeline adapter for fetching and storing factor data from the Kenneth French Data Library.

**Pipeline name**: `french_factors`

**Fetch logic**:

```python
import io
import zipfile
import pandas as pd
import requests

FRENCH_BASE_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"

FACTOR_FILES = {
    "us_daily": "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip",
    "us_monthly": "F-F_Research_Data_5_Factors_2x3_CSV.zip",
    "europe_daily": "Europe_5_Factors_Daily_CSV.zip",
    "europe_monthly": "Europe_5_Factors_CSV.zip",
}

def fetch_french_factors(factor_set: str) -> pd.DataFrame:
    """
    Download and parse a French Data Library CSV file.
    Returns DataFrame with columns: date, mkt, smb, hml, rmw, cma, rf
    All values as decimals (the library uses percentages — divide by 100).
    """
    url = FRENCH_BASE_URL + FACTOR_FILES[factor_set]
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        # The ZIP contains a single CSV file
        csv_name = z.namelist()[0]
        with z.open(csv_name) as f:
            raw = f.read().decode("utf-8")

    # French CSVs have header rows and footer rows that need trimming
    # Find the data section (starts after a line with "Mkt-RF" or similar)
    lines = raw.split("\n")
    data_start = None
    data_end = None
    for i, line in enumerate(lines):
        if "Mkt-RF" in line and data_start is None:
            data_start = i
        if data_start is not None and i > data_start and line.strip() == "":
            data_end = i
            break

    if data_start is None:
        raise ValueError(f"Could not parse factor file: {factor_set}")

    csv_text = "\n".join(lines[data_start:data_end])
    df = pd.read_csv(io.StringIO(csv_text), skipinitialspace=True)

    # Rename columns to standard names
    df.columns = [c.strip() for c in df.columns]
    col_map = {"Mkt-RF": "mkt", "SMB": "smb", "HML": "hml",
               "RMW": "rmw", "CMA": "cma", "RF": "rf"}
    df = df.rename(columns=col_map)

    # Parse date column (first unnamed column)
    first_col = df.columns[0]
    if "daily" in factor_set:
        df["date"] = pd.to_datetime(df[first_col].astype(str), format="%Y%m%d")
    else:
        df["date"] = pd.to_datetime(df[first_col].astype(str), format="%Y%m")

    # Convert from percentages to decimals
    for col in ["mkt", "smb", "hml", "rmw", "cma", "rf"]:
        df[col] = df[col].astype(float) / 100.0

    df = df.drop(columns=[first_col])
    return df[["date", "mkt", "smb", "hml", "rmw", "cma", "rf"]]
```

### 1.4 Database Storage

Factor data is stored in a dedicated table:

```sql
CREATE TABLE factor_returns (
    date          DATE NOT NULL,
    region        TEXT NOT NULL,          -- 'us' or 'europe'
    frequency     TEXT NOT NULL,          -- 'daily' or 'monthly'
    mkt           DOUBLE PRECISION,       -- Market excess return (decimal)
    smb           DOUBLE PRECISION,       -- Size factor (decimal)
    hml           DOUBLE PRECISION,       -- Value factor (decimal)
    rmw           DOUBLE PRECISION,       -- Profitability factor (decimal)
    cma           DOUBLE PRECISION,       -- Investment factor (decimal)
    rf            DOUBLE PRECISION,       -- Risk-free rate (decimal)
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (date, region, frequency)
);

-- Index for efficient lookups by date range and region
CREATE INDEX idx_factor_returns_region_date
    ON factor_returns (region, frequency, date);
```

### 1.5 Pipeline Schedule

| Parameter | Value |
|-----------|-------|
| Pipeline name | `french_factors` |
| Frequency | Weekly (Sunday night) — factor data is updated monthly by French, but weekly checks ensure no lag |
| Rate limit | 1 request per file, 4 files total, 2-second delay between requests |
| Retry | 3 attempts with exponential backoff (5s, 15s, 45s) |
| Staleness threshold | 60 days — if the latest factor date is older than 60 days, raise a `data_quality` warning |
| Cache | Store full history on each fetch (idempotent upsert by primary key) |

---

## 2. Five-Factor Model Regression

### 2.1 Model Specification

The Fama-French five-factor model decomposes a security's (or portfolio's) excess return into factor exposures:

$$R_i - R_f = \alpha_i + \beta_{MKT} \cdot MKT + \beta_{SMB} \cdot SMB + \beta_{HML} \cdot HML + \beta_{RMW} \cdot RMW + \beta_{CMA} \cdot CMA + \epsilon_i$$

Where:
- $R_i$ = return of security (or portfolio) $i$
- $R_f$ = risk-free rate
- $\alpha_i$ = Jensen's alpha — the intercept; excess return unexplained by factors
- $\beta_{MKT}, \beta_{SMB}, \beta_{HML}, \beta_{RMW}, \beta_{CMA}$ = factor loadings (sensitivities)
- $\epsilon_i$ = residual (idiosyncratic return)

### 2.2 OLS Regression

**Math — ordinary least squares:**

Given $n$ observations, let:
- $\mathbf{y}$ = $(n \times 1)$ vector of excess returns $(R_i - R_f)$
- $\mathbf{X}$ = $(n \times 6)$ matrix: column of 1s (intercept) plus 5 factor return columns

$$\hat{\boldsymbol{\beta}} = (\mathbf{X}^T \mathbf{X})^{-1} \mathbf{X}^T \mathbf{y}$$

**Python pseudocode:**

```python
@dataclass
class FactorRegressionResult:
    alpha: float                    # Jensen's alpha (annualized)
    alpha_daily: float              # Daily alpha (raw intercept)
    alpha_t_stat: float             # t-statistic for alpha
    alpha_p_value: float            # p-value for alpha
    betas: dict[str, float]         # {"mkt": 1.05, "smb": -0.12, ...}
    beta_t_stats: dict[str, float]  # t-statistics for each beta
    beta_p_values: dict[str, float] # p-values for each beta
    r_squared: float                # R-squared
    adj_r_squared: float            # Adjusted R-squared
    residual_std: float             # Standard deviation of residuals
    n_observations: int             # Number of data points used
    start_date: date
    end_date: date

FACTOR_NAMES = ["mkt", "smb", "hml", "rmw", "cma"]

def run_factor_regression(
    excess_returns: np.ndarray,       # shape (n,) — R_i - R_f
    factor_returns: np.ndarray,       # shape (n, 5) — MKT, SMB, HML, RMW, CMA columns
    trading_days: int = 252,
    start_date: date = None,
    end_date: date = None,
) -> FactorRegressionResult:
    """
    Run OLS regression of excess returns on the five Fama-French factors.
    Returns alpha (annualized), factor loadings, and diagnostic statistics.
    """
    n = len(excess_returns)
    if n < 60:
        raise InsufficientDataError(f"Need at least 60 observations, got {n}")

    # Add intercept column
    X = np.column_stack([np.ones(n), factor_returns])  # shape (n, 6)
    y = excess_returns  # shape (n,)

    # OLS: beta_hat = (X'X)^{-1} X'y
    XtX = X.T @ X
    Xty = X.T @ y
    beta_hat = np.linalg.solve(XtX, Xty)  # shape (6,)

    # Residuals and diagnostics
    y_hat = X @ beta_hat
    residuals = y - y_hat
    rss = float(np.sum(residuals ** 2))
    tss = float(np.sum((y - np.mean(y)) ** 2))

    r_squared = 1 - rss / tss if tss > 0 else 0.0
    k = X.shape[1]  # number of regressors including intercept
    adj_r_squared = 1 - (1 - r_squared) * (n - 1) / (n - k)

    # Standard errors
    sigma_sq = rss / (n - k)
    var_beta = sigma_sq * np.linalg.inv(XtX)
    se_beta = np.sqrt(np.diag(var_beta))

    # t-statistics and p-values
    from scipy import stats as sp_stats
    t_stats = beta_hat / se_beta
    p_values = 2 * (1 - sp_stats.t.cdf(np.abs(t_stats), df=n - k))

    # Annualize alpha: alpha_annual = alpha_daily * trading_days
    alpha_daily = float(beta_hat[0])
    alpha_annual = alpha_daily * trading_days

    betas = {name: float(beta_hat[i + 1]) for i, name in enumerate(FACTOR_NAMES)}
    beta_t = {name: float(t_stats[i + 1]) for i, name in enumerate(FACTOR_NAMES)}
    beta_p = {name: float(p_values[i + 1]) for i, name in enumerate(FACTOR_NAMES)}

    return FactorRegressionResult(
        alpha=alpha_annual,
        alpha_daily=alpha_daily,
        alpha_t_stat=float(t_stats[0]),
        alpha_p_value=float(p_values[0]),
        betas=betas,
        beta_t_stats=beta_t,
        beta_p_values=beta_p,
        r_squared=r_squared,
        adj_r_squared=adj_r_squared,
        residual_std=float(np.sqrt(sigma_sq)),
        n_observations=n,
        start_date=start_date,
        end_date=end_date,
    )
```

### 2.3 Worked Example: Portfolio Factor Regression

**Scenario:** A portfolio with 60% MSCI World ETF, 25% Finnish value stocks, 15% BTC. Regression over 252 trading days (1 year) against European five-factor model.

Regression output:

| Coefficient | Estimate | t-stat | p-value | Interpretation |
|------------|----------|--------|---------|----------------|
| Alpha (daily) | 0.000085 | 1.42 | 0.157 | +2.14% annualized, but not statistically significant (p > 0.05) |
| Beta MKT | 1.08 | 24.5 | < 0.001 | Slightly more market-sensitive than the market |
| Beta SMB | -0.15 | -2.1 | 0.037 | Tilted toward large caps (negative = big bias) |
| Beta HML | 0.28 | 3.4 | 0.001 | Value tilt — consistent with Munger satellite |
| Beta RMW | 0.19 | 2.0 | 0.047 | Profitability tilt — quality companies |
| Beta CMA | 0.05 | 0.6 | 0.550 | No meaningful investment factor exposure |

- **R-squared**: 0.82 — 82% of portfolio variance explained by the five factors
- **Adjusted R-squared**: 0.816

**Interpretation:** The portfolio has a market beta slightly above 1 (expected given the BTC allocation), a value tilt (HML = 0.28), and a quality/profitability tilt (RMW = 0.19). The alpha of +2.14% is economically meaningful but not statistically significant at the 5% level with only one year of data. The negative SMB loading reflects the large-cap core (MSCI World ETF).

---

## 3. Rolling Factor Exposure

### 3.1 Specification

Run the five-factor regression over a rolling window to observe how factor exposures evolve over time. This detects style drift, changing factor bets, and whether the portfolio's character has shifted.

### 3.2 Parameters

| Parameter | Default | Range |
|-----------|---------|-------|
| Window | 36 months (756 trading days) | 12–60 months |
| Step | 1 month (21 trading days) | 1–3 months |
| Minimum observations per window | 60 trading days | — |
| Frequency | Monthly (use monthly factor data for windows >= 36 months) | Daily or monthly |

### 3.3 Python Pseudocode

```python
@dataclass
class RollingFactorPoint:
    window_end_date: date
    alpha: float
    betas: dict[str, float]
    r_squared: float

def rolling_factor_exposure(
    excess_returns: np.ndarray,      # shape (n,)
    factor_returns: np.ndarray,      # shape (n, 5)
    dates: list[date],               # length n
    window: int = 756,               # trading days (36 months)
    step: int = 21,                  # trading days (1 month)
) -> list[RollingFactorPoint]:
    """
    Compute factor regression over rolling windows.
    Returns a time series of factor exposures.
    """
    results = []
    for end in range(window, len(excess_returns) + 1, step):
        start = end - window
        result = run_factor_regression(
            excess_returns[start:end],
            factor_returns[start:end],
            start_date=dates[start],
            end_date=dates[end - 1],
        )
        results.append(RollingFactorPoint(
            window_end_date=dates[end - 1],
            alpha=result.alpha,
            betas=result.betas,
            r_squared=result.r_squared,
        ))
    return results
```

### 3.4 Worked Example: Rolling Beta Drift

A portfolio tracked over 5 years with 36-month rolling windows:

| Window End | Beta MKT | Beta HML | Beta RMW | Interpretation |
|-----------|----------|----------|----------|----------------|
| 2023-12 | 0.95 | 0.35 | 0.22 | Strong value/quality tilt |
| 2024-06 | 1.02 | 0.30 | 0.20 | Market beta increased, value tilt stable |
| 2024-12 | 1.12 | 0.18 | 0.15 | Value tilt declining — crypto or growth additions? |
| 2025-06 | 1.08 | 0.28 | 0.19 | Value tilt recovering after rebalance |
| 2025-12 | 1.10 | 0.25 | 0.21 | Stable factor profile |

If HML loading dropped from 0.35 to 0.18, the system flags this as style drift: "Value factor exposure has declined by 49% over the past 18 months."

---

## 4. Factor Attribution

### 4.1 Return Decomposition

Decompose total portfolio return into factor-explained and unexplained (alpha) components:

$$R_i - R_f = \underbrace{\hat{\alpha}}_{\text{alpha}} + \underbrace{\hat{\beta}_{MKT} \cdot MKT}_{\text{market}} + \underbrace{\hat{\beta}_{SMB} \cdot SMB}_{\text{size}} + \underbrace{\hat{\beta}_{HML} \cdot HML}_{\text{value}} + \underbrace{\hat{\beta}_{RMW} \cdot RMW}_{\text{profitability}} + \underbrace{\hat{\beta}_{CMA} \cdot CMA}_{\text{investment}} + \underbrace{\epsilon_i}_{\text{residual}}$$

For a given period, the contribution of each factor to total return:

$$\text{Factor Contribution}_k = \hat{\beta}_k \times \sum_{t=1}^{T} F_{k,t}$$

Where $F_{k,t}$ is the return of factor $k$ on day $t$.

### 4.2 Python Pseudocode

```python
@dataclass
class FactorAttribution:
    total_excess_return: float            # R_portfolio - R_f over the period
    alpha_contribution: float             # alpha * T (cumulative alpha)
    factor_contributions: dict[str, float]  # {"mkt": 0.082, "smb": -0.005, ...}
    residual: float                       # unexplained portion
    factor_pct_of_return: dict[str, float]  # {"mkt": 0.65, "hml": 0.12, ...} as fractions

def compute_factor_attribution(
    excess_returns: np.ndarray,     # shape (T,)
    factor_returns: np.ndarray,     # shape (T, 5)
    regression: FactorRegressionResult,
) -> FactorAttribution:
    """
    Decompose the cumulative excess return into factor contributions.
    Uses the factor loadings from a pre-computed regression.
    """
    total_excess = float(np.sum(excess_returns))

    # Cumulative factor returns over the period
    cum_factors = {
        name: float(np.sum(factor_returns[:, i]))
        for i, name in enumerate(FACTOR_NAMES)
    }

    # Factor contributions = beta * cumulative factor return
    contributions = {
        name: regression.betas[name] * cum_factors[name]
        for name in FACTOR_NAMES
    }

    # Alpha contribution = daily alpha * number of days
    alpha_contrib = regression.alpha_daily * len(excess_returns)

    # Residual = total - alpha - sum(factor contributions)
    explained = alpha_contrib + sum(contributions.values())
    residual = total_excess - explained

    # Percentage of total return explained by each factor
    abs_total = abs(total_excess) if total_excess != 0 else 1.0
    pct_contributions = {
        name: contributions[name] / abs_total
        for name in FACTOR_NAMES
    }

    return FactorAttribution(
        total_excess_return=total_excess,
        alpha_contribution=alpha_contrib,
        factor_contributions=contributions,
        residual=residual,
        factor_pct_of_return=pct_contributions,
    )
```

### 4.3 Worked Example: Annual Return Decomposition

**Scenario:** Portfolio excess return over 1 year = +9.5%. Factor loadings from regression above.

Cumulative factor returns over the year (European factors):

| Factor | Cumulative Return | Beta | Contribution | % of Return |
|--------|-------------------|------|-------------|-------------|
| MKT | +8.2% | 1.08 | +8.86% | 93.2% |
| SMB | -1.5% | -0.15 | +0.23% | 2.4% |
| HML | +3.1% | 0.28 | +0.87% | 9.1% |
| RMW | +2.0% | 0.19 | +0.38% | 4.0% |
| CMA | +0.8% | 0.05 | +0.04% | 0.4% |
| **Alpha** | — | — | **+2.14%** | **22.5%** |
| **Residual** | — | — | **-3.02%** | **-31.8%** |
| **Total** | — | — | **+9.50%** | **100%** |

**Interpretation:** "Your portfolio's 9.5% excess return is primarily driven by market exposure (93%). Your value tilt (HML) contributed 0.87%, and your quality tilt (RMW) added 0.38%. The negative SMB contribution (+0.23%) means your large-cap bias actually helped because small caps underperformed. Alpha of +2.14% suggests stock selection added value, but the large residual indicates the five-factor model does not fully capture your portfolio's return drivers (likely due to the crypto allocation, which is not well-modeled by Fama-French factors)."

---

## 5. Sharpe Style Analysis

### 5.1 Model Specification

Sharpe (1992) style analysis uses constrained regression to classify a portfolio's effective investment style. Unlike standard OLS, the factor weights are constrained to:

1. **Sum to 1**: $\sum_{k} w_k = 1$ (portfolio is fully invested)
2. **Non-negative**: $w_k \geq 0$ for all $k$ (no short selling of styles)

This transforms factor loadings into interpretable "style weights" — the portfolio behaves as if it were X% large-value, Y% small-growth, etc.

### 5.2 Style Indices

For style analysis, use broader style indices rather than long-short factors:

| Index | Description | Proxy |
|-------|-------------|-------|
| Large Value | Large-cap value stocks | MSCI Europe Large Value or FF Large-High BtM |
| Large Growth | Large-cap growth stocks | MSCI Europe Large Growth or FF Large-Low BtM |
| Small Value | Small-cap value stocks | MSCI Europe Small Value or FF Small-High BtM |
| Small Growth | Small-cap growth stocks | MSCI Europe Small Growth or FF Small-Low BtM |
| Bonds | Investment-grade bonds | Bloomberg Euro Aggregate or VGEA proxy |
| Cash | Risk-free rate | ECB deposit facility rate |

### 5.3 Constrained Optimization

$$\min_{\mathbf{w}} \sum_{t=1}^{T} \left( R_{p,t} - \sum_{k=1}^{K} w_k \cdot R_{k,t} \right)^2$$

Subject to:

$$\sum_{k=1}^{K} w_k = 1, \quad w_k \geq 0 \;\forall\; k$$

**Python pseudocode:**

```python
@dataclass
class StyleAnalysisResult:
    weights: dict[str, float]    # {"large_value": 0.35, "large_growth": 0.40, ...}
    r_squared: float             # How well the style indices explain portfolio returns
    style_label: str             # "Large Blend" / "Large Value" / etc.
    n_observations: int

STYLE_NAMES = [
    "large_value", "large_growth",
    "small_value", "small_growth",
    "bonds", "cash",
]

def sharpe_style_analysis(
    portfolio_returns: np.ndarray,   # shape (T,)
    style_returns: np.ndarray,       # shape (T, K) — K style index return series
) -> StyleAnalysisResult:
    """
    Constrained regression: weights sum to 1, non-negative.
    Uses scipy.optimize.minimize with SLSQP.
    """
    T, K = style_returns.shape

    def objective(w):
        predicted = style_returns @ w
        residuals = portfolio_returns - predicted
        return float(np.sum(residuals ** 2))

    # Constraints: weights sum to 1
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
    # Bounds: each weight between 0 and 1
    bounds = [(0.0, 1.0)] * K
    # Initial guess: equal weights
    w0 = np.ones(K) / K

    result = optimize.minimize(
        objective, w0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
    )

    if not result.success:
        raise OptimizationError(f"Style analysis did not converge: {result.message}")

    weights = result.x
    predicted = style_returns @ weights
    ss_res = np.sum((portfolio_returns - predicted) ** 2)
    ss_tot = np.sum((portfolio_returns - np.mean(portfolio_returns)) ** 2)
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # Determine style label from dominant weights
    style_label = _classify_style(dict(zip(STYLE_NAMES, weights)))

    return StyleAnalysisResult(
        weights=dict(zip(STYLE_NAMES, [float(w) for w in weights])),
        r_squared=r_squared,
        style_label=style_label,
        n_observations=T,
    )


def _classify_style(weights: dict[str, float]) -> str:
    """
    Classify into a Morningstar-style label based on dominant weights.
    """
    equity_value = weights.get("large_value", 0) + weights.get("small_value", 0)
    equity_growth = weights.get("large_growth", 0) + weights.get("small_growth", 0)
    large_cap = weights.get("large_value", 0) + weights.get("large_growth", 0)
    small_cap = weights.get("small_value", 0) + weights.get("small_growth", 0)

    # Size classification
    if large_cap > 0.6:
        size = "Large"
    elif small_cap > 0.4:
        size = "Small"
    else:
        size = "Mid"

    # Style classification
    total_equity = equity_value + equity_growth
    if total_equity < 0.2:
        return "Fixed Income / Cash"
    value_tilt = equity_value / total_equity if total_equity > 0 else 0.5
    if value_tilt > 0.6:
        style = "Value"
    elif value_tilt < 0.4:
        style = "Growth"
    else:
        style = "Blend"

    return f"{size} {style}"
```

### 5.4 Worked Example: Style Classification

**Scenario:** The Munger/Boglehead hybrid portfolio.

Style analysis output:

| Style Index | Weight | Interpretation |
|-------------|--------|----------------|
| Large Value | 0.35 | Finnish value stocks + value-tilted portion of MSCI World |
| Large Growth | 0.40 | Broad MSCI World index exposure |
| Small Value | 0.05 | Minimal small-cap value |
| Small Growth | 0.02 | Minimal small-cap growth |
| Bonds | 0.12 | Bond ETF allocation |
| Cash | 0.06 | Cash reserves |

- **R-squared**: 0.91 — style indices explain 91% of return variation
- **Style label**: "Large Blend" (40% growth + 35% value = blend, 75% large-cap = large)

**Interpretation:** Despite a Munger value philosophy, the portfolio's effective style is "Large Blend" because the 60% MSCI World core dilutes the value satellite. If the investor wants a stronger value tilt, the satellite allocation or ETF selection should be adjusted.

---

## 6. Factor Timing Analysis

### 6.1 Specification

Track how factor exposures change over rolling windows and flag unintended factor bets or significant drift from expected positioning.

### 6.2 Expected Factor Profile

Based on the Munger/Boglehead hybrid strategy, the expected factor profile is:

| Factor | Expected Sign | Expected Range | Rationale |
|--------|--------------|----------------|-----------|
| MKT | Positive | 0.8 – 1.2 | Fully invested, market-like exposure |
| SMB | Neutral to negative | -0.3 – 0.1 | Core is large-cap index; satellite may add some small-cap |
| HML | Positive | 0.1 – 0.5 | Munger value tilt in satellite |
| RMW | Positive | 0.05 – 0.4 | Quality/profitability focus |
| CMA | Neutral | -0.1 – 0.2 | No strong investment-factor bet expected |

### 6.3 Drift Detection

```python
@dataclass
class FactorDriftAlert:
    factor: str               # e.g., "hml"
    factor_label: str         # e.g., "Value (HML)"
    current_beta: float       # Current rolling beta
    expected_range: tuple[float, float]  # (low, high)
    direction: str            # "above_expected" or "below_expected" or "sign_reversal"
    severity: str             # "info", "warning", "critical"
    message: str

EXPECTED_RANGES = {
    "mkt": (0.8, 1.2),
    "smb": (-0.3, 0.1),
    "hml": (0.1, 0.5),
    "rmw": (0.05, 0.4),
    "cma": (-0.1, 0.2),
}

FACTOR_LABELS = {
    "mkt": "Market (MKT)",
    "smb": "Size (SMB)",
    "hml": "Value (HML)",
    "rmw": "Profitability (RMW)",
    "cma": "Investment (CMA)",
}

def detect_factor_drift(
    rolling_results: list[RollingFactorPoint],
    expected_ranges: dict[str, tuple[float, float]] = EXPECTED_RANGES,
) -> list[FactorDriftAlert]:
    """
    Compare the most recent rolling factor exposures against expected ranges.
    """
    if not rolling_results:
        return []

    latest = rolling_results[-1]
    alerts = []

    for factor in FACTOR_NAMES:
        beta = latest.betas[factor]
        low, high = expected_ranges[factor]

        if beta < low:
            severity = "critical" if beta < low - 0.3 else "warning"
            alerts.append(FactorDriftAlert(
                factor=factor,
                factor_label=FACTOR_LABELS[factor],
                current_beta=beta,
                expected_range=(low, high),
                direction="below_expected",
                severity=severity,
                message=f"{FACTOR_LABELS[factor]} loading is {beta:.2f}, "
                        f"below expected range [{low:.2f}, {high:.2f}].",
            ))
        elif beta > high:
            severity = "critical" if beta > high + 0.3 else "warning"
            alerts.append(FactorDriftAlert(
                factor=factor,
                factor_label=FACTOR_LABELS[factor],
                current_beta=beta,
                expected_range=(low, high),
                direction="above_expected",
                severity=severity,
                message=f"{FACTOR_LABELS[factor]} loading is {beta:.2f}, "
                        f"above expected range [{low:.2f}, {high:.2f}].",
            ))

    # Check for sign reversals on factors with expected positive sign
    for factor in ["hml", "rmw"]:
        if latest.betas[factor] < 0:
            alerts.append(FactorDriftAlert(
                factor=factor,
                factor_label=FACTOR_LABELS[factor],
                current_beta=latest.betas[factor],
                expected_range=expected_ranges[factor],
                direction="sign_reversal",
                severity="critical",
                message=f"{FACTOR_LABELS[factor]} loading has reversed to {latest.betas[factor]:.2f}. "
                        f"Expected positive for a Munger value/quality strategy.",
            ))

    return alerts
```

### 6.4 Worked Example: Unintended Factor Bet

After adding several AI/tech stocks to the satellite portfolio, the rolling 36-month regression shows:

| Factor | 6 Months Ago | Now | Change | Alert |
|--------|-------------|-----|--------|-------|
| MKT | 1.05 | 1.22 | +0.17 | WARNING: above expected range [0.8, 1.2] |
| SMB | -0.10 | -0.25 | -0.15 | OK (within range) |
| HML | 0.28 | -0.05 | -0.33 | CRITICAL: sign reversal — value loading gone negative |
| RMW | 0.20 | 0.08 | -0.12 | OK (within range, but declining) |
| CMA | 0.03 | -0.15 | -0.18 | WARNING: below expected range [-0.1, 0.2] |

**Alert message:** "Your Value (HML) factor loading has reversed from +0.28 to -0.05. This means your portfolio now behaves more like a growth portfolio than a value portfolio. This is inconsistent with the Munger satellite strategy. The shift coincides with recent additions of high-growth AI/tech positions. Consider rebalancing toward value stocks or reducing growth exposure."

---

## 7. Region Selection Logic

Since the portfolio holds both European and US securities, the system must select the appropriate factor set for each regression:

```python
def select_factor_region(security_id: int) -> str:
    """
    Determine which factor set to use for a given security.
    """
    security = get_security(security_id)

    # US-listed securities use US factors
    if security.exchange in ("NYSE", "NASDAQ", "AMEX", "BATS"):
        return "us"

    # European-listed securities use European factors
    if security.exchange in ("XHEL", "XSTO", "XETR", "XAMS", "XLON", "XPAR",
                             "XMIL", "XMAD", "XBRU", "XLIS", "XDUB"):
        return "europe"

    # Crypto: use US factors as default (crypto is dollar-denominated)
    if security.asset_class == "crypto":
        return "us"

    # Default to European factors for a Finnish investor
    return "europe"


def select_portfolio_factor_region(holdings: list[dict]) -> str:
    """
    For portfolio-level regressions, use the region with the largest allocation.
    If European holdings >= 50% of portfolio value, use European factors.
    Otherwise use US factors.
    """
    eur_weight = sum(h["weight"] for h in holdings if select_factor_region(h["security_id"]) == "europe")
    return "europe" if eur_weight >= 0.50 else "us"
```

---

## API Endpoints

### `GET /api/v1/factors/exposure`

Current factor loadings for the full portfolio.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `lookbackDays` | int | 756 | Trading days for regression (36 months) |
| `region` | string | `auto` | Factor region: `us`, `europe`, or `auto` (select based on portfolio composition) |
| `frequency` | string | `daily` | `daily` or `monthly` |

**Response:**

```json
{
  "data": {
    "alpha": 0.0214,
    "alpha_daily": 0.000085,
    "alpha_t_stat": 1.42,
    "alpha_p_value": 0.157,
    "alpha_significant": false,
    "betas": {
      "mkt": { "value": 1.08, "t_stat": 24.5, "p_value": 0.0001, "significant": true },
      "smb": { "value": -0.15, "t_stat": -2.1, "p_value": 0.037, "significant": true },
      "hml": { "value": 0.28, "t_stat": 3.4, "p_value": 0.001, "significant": true },
      "rmw": { "value": 0.19, "t_stat": 2.0, "p_value": 0.047, "significant": true },
      "cma": { "value": 0.05, "t_stat": 0.6, "p_value": 0.550, "significant": false }
    },
    "r_squared": 0.82,
    "adj_r_squared": 0.816,
    "n_observations": 756,
    "drift_alerts": []
  },
  "meta": {
    "calculatedAt": "2026-03-21T14:30:00Z",
    "lookbackDays": 756,
    "tradingDaysAvailable": 740,
    "region": "europe",
    "frequency": "daily",
    "factorDataThrough": "2026-02-28",
    "significanceLevel": 0.05
  }
}
```

### `GET /api/v1/factors/exposure/{securityId}`

Per-security factor loadings.

**Query parameters:** Same as portfolio endpoint.

**Response:** Same shape as portfolio endpoint, plus:

```json
{
  "data": {
    "security_id": 42,
    "ticker": "NOKIA.HE",
    "region_used": "europe",
    "alpha": -0.015,
    "betas": { ... },
    ...
  },
  ...
}
```

### `GET /api/v1/factors/attribution`

Return attribution decomposed by factor.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `startDate` | date | 1 year ago | Start of attribution period |
| `endDate` | date | today | End of attribution period |
| `region` | string | `auto` | Factor region |

**Response:**

```json
{
  "data": {
    "total_excess_return": 0.095,
    "alpha_contribution": 0.0214,
    "factor_contributions": {
      "mkt": { "return": 0.0886, "pct_of_total": 0.932 },
      "smb": { "return": 0.0023, "pct_of_total": 0.024 },
      "hml": { "return": 0.0087, "pct_of_total": 0.091 },
      "rmw": { "return": 0.0038, "pct_of_total": 0.040 },
      "cma": { "return": 0.0004, "pct_of_total": 0.004 }
    },
    "residual": -0.0302,
    "total_factor_explained": 0.1038,
    "total_factor_explained_pct": 0.775
  },
  "meta": {
    "calculatedAt": "2026-03-21T14:30:00Z",
    "startDate": "2025-03-21",
    "endDate": "2026-03-21",
    "region": "europe"
  }
}
```

### `GET /api/v1/factors/style`

Sharpe style analysis classification.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `lookbackDays` | int | 756 | Trading days for style analysis window |

**Response:**

```json
{
  "data": {
    "style_label": "Large Blend",
    "weights": {
      "large_value": 0.35,
      "large_growth": 0.40,
      "small_value": 0.05,
      "small_growth": 0.02,
      "bonds": 0.12,
      "cash": 0.06
    },
    "r_squared": 0.91,
    "n_observations": 756,
    "equity_pct": 0.82,
    "value_tilt": 0.49,
    "size_tilt": 0.07
  },
  "meta": {
    "calculatedAt": "2026-03-21T14:30:00Z",
    "lookbackDays": 756
  }
}
```

### `GET /api/v1/factors/rolling`

Rolling factor exposure time series.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `window` | int | 756 | Rolling window in trading days |
| `step` | int | 21 | Step size in trading days |
| `factor` | string | all | Specific factor to return (`mkt`, `smb`, `hml`, `rmw`, `cma`, `alpha`), or `all` |

**Response:**

```json
{
  "data": {
    "series": [
      {
        "date": "2024-12-31",
        "alpha": 0.018,
        "betas": { "mkt": 0.95, "smb": -0.10, "hml": 0.35, "rmw": 0.22, "cma": 0.03 },
        "r_squared": 0.84
      },
      {
        "date": "2025-01-31",
        "alpha": 0.020,
        "betas": { "mkt": 0.98, "smb": -0.12, "hml": 0.33, "rmw": 0.21, "cma": 0.04 },
        "r_squared": 0.83
      }
    ],
    "drift_alerts": [
      {
        "factor": "hml",
        "factor_label": "Value (HML)",
        "current_beta": -0.05,
        "expected_range": [0.1, 0.5],
        "direction": "sign_reversal",
        "severity": "critical",
        "message": "Value (HML) loading has reversed to -0.05. Expected positive for a Munger value/quality strategy."
      }
    ]
  },
  "meta": {
    "calculatedAt": "2026-03-21T14:30:00Z",
    "window": 756,
    "step": 21,
    "n_points": 24
  }
}
```

---

## Caching and Refresh

- Factor data pipeline runs weekly. Factor regression results are recalculated **daily** after market close (same trigger as risk metrics — nightly `holdings_snapshot` rebuild).
- Cached in Redis with key pattern `factors:{endpoint}:{params_hash}`.
- TTL: until next market close + 1 hour grace.
- Rolling and style analyses are more expensive; cached with 24-hour TTL.
- On-demand recalculation via `?refresh=true` (rate-limited to 1 per minute).

---

## Edge Cases

1. **Insufficient price history for regression**: If a security or portfolio has fewer than 60 trading days of return history, return `null` for all factor metrics with reason `"insufficient_history"`. Do not run a regression with fewer than 60 observations — the results would be statistically meaningless.

2. **Factor data lag**: The Kenneth French Data Library typically lags by 1-2 months. If the latest factor data is older than the portfolio return series, truncate the regression to the overlapping date range. Report `factorDataThrough` in the response metadata so the user knows factor analysis does not cover the most recent period.

3. **Crypto holdings and factor model fit**: Cryptocurrency returns are poorly explained by Fama-French factors (R-squared will be very low). For per-security regressions on crypto, report the R-squared prominently and include a warning: "Fama-French factors explain only X% of this asset's return variance. Factor loadings may not be meaningful." At the portfolio level, heavy crypto allocation will reduce overall R-squared and inflate the residual.

4. **Mixed-region portfolio**: When a portfolio contains both US and European holdings, the portfolio-level regression uses the dominant region's factors (see Section 7). Per-security regressions use the appropriate regional factors. The portfolio-level attribution will be approximate because a single factor set cannot perfectly capture both regional exposures. Flag this as a `data_quality` note when the minority-region allocation exceeds 30%.

5. **Short history with structural breaks**: If the portfolio underwent a major rebalancing (e.g., shifting from 100% equities to 60/40), a full-period regression mixes two different portfolios. The rolling analysis (Section 3) handles this correctly — use rolling results for interpretation and flag full-period R-squared drops as potential structural breaks.

6. **Multicollinearity between factors**: The five factors can exhibit correlation (especially HML and CMA). When multicollinearity is high, individual beta estimates become unstable. Monitor the condition number of $\mathbf{X}^T \mathbf{X}$; if it exceeds 30, include a warning that individual factor loadings may be unreliable (though the overall regression and alpha remain valid).

7. **Negative R-squared**: In rare cases, especially for short periods or highly unconventional portfolios, adjusted R-squared can be negative. Report as-is — this means the factor model explains the returns worse than a simple mean. Do not clamp to zero.

8. **Style analysis non-convergence**: The constrained optimization in Sharpe style analysis may fail to converge for extreme return patterns. If `scipy.optimize.minimize` does not converge within 1000 iterations, return `null` for style analysis with reason `"optimization_failed"`.

9. **Factor data gaps or missing values**: If a factor return is `NaN` or missing for certain dates, drop those dates from the regression. Report the actual number of observations used in `n_observations`. If more than 10% of the expected observations are dropped, raise a `data_quality` warning.

10. **Single-holding portfolio**: Factor regression is technically valid but degenerates to single-stock factor analysis. Style analysis requires at least 2 return series for meaningful results. Flag as `"single_holding_portfolio"` and note that results reflect the individual security, not a diversified portfolio.

11. **Zero excess return period**: If $R_i - R_f = 0$ for all observations in the window (portfolio exactly matched the risk-free rate), the regression produces all-zero coefficients. Return the result with a note that the portfolio had zero excess return over the period.

12. **Stale holdings snapshot**: If `holdings_snapshot` is not up to date, the portfolio weights used for portfolio-level regression may be inaccurate. Check that the snapshot date is within 1 trading day of the most recent market close before computing. If stale, recalculate from available data and flag in the response.

---

## Open Questions

- Should we add a momentum factor (UMD/WML) as a sixth factor? The Carhart four-factor model includes momentum, and it could help explain return patterns for portfolios with inadvertent momentum exposure. The French Data Library provides momentum factor data.
- Should the expected factor profile (Section 6.2) be user-configurable, or hardcoded based on the Munger/Boglehead strategy?
- Should we implement Bayesian shrinkage estimation (Black-Litterman) for more stable factor loadings with short histories?
- For the style analysis, should we use actual ETF return series (e.g., iShares MSCI Europe Value) instead of constructed style indices? ETFs are directly investable and more intuitive to the user.
- How should we handle the transition period when the portfolio is new and has fewer than 36 months of history for rolling analysis? Use a shorter rolling window (minimum 12 months) with a reduced-confidence flag?

---

## Changelog

| Date | Change |
|------|--------|
| 2026-03-21 | Initial draft |
