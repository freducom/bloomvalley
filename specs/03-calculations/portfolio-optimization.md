# Portfolio Optimization

Mean-variance portfolio optimization, Black-Litterman blending, risk parity, and tax-aware rebalancing recommendations. This spec defines how the system computes optimal portfolio allocations given the investor's constraints (glidepath bounds, position limits, account-type restrictions) and generates actionable trade recommendations that minimize tax drag. All optimization runs server-side in Python using scipy.optimize and numpy, with a strict <5 second computation budget.

**Status: DRAFT**

## Dependencies

- [Spec Conventions](../00-meta/spec-conventions.md) — monetary format (cents), date handling, naming rules
- [Data Model](../01-system/data-model.md) — `prices`, `securities`, `holdings_snapshot`, `accounts`, `tax_lots`, `fx_rates` tables
- [Portfolio Math](../03-calculations/portfolio-math.md) — daily return series, portfolio valuation, cost basis, FX handling
- [Risk Metrics](../03-calculations/risk-metrics.md) — covariance matrix, correlation matrix, volatility, Sharpe ratio
- [Glidepath](../03-calculations/glidepath.md) — target allocation by age, drift thresholds, asset class mapping, osakesaastotili constraints
- [Finnish Tax](../03-calculations/tax-finnish.md) — capital gains rates (30%/34%), deemed cost of acquisition, account-type tax treatment
- [AGENTS.md](../../AGENTS.md) — Portfolio Manager role, position limits, investment policy

---

## General Conventions

- **Return series**: daily log returns, FX-adjusted to EUR, from the `prices` hypertable.
- **Trading days per year**: 252 (stocks/bonds/ETFs), 365 (crypto).
- **Base currency**: EUR. All weights and monetary values are EUR-denominated.
- **Risk-free rate**: ECB deposit facility rate (same source as [risk-metrics.md](../03-calculations/risk-metrics.md) Section 2).
- **Minimum history**: 252 trading days (1 year) for covariance estimation. Securities with less history are excluded from optimization and their current weight is treated as fixed.
- **All monetary outputs**: integers in EUR cents, paired with `currency: "EUR"`.
- **Computation budget**: all optimization endpoints must return within 5 seconds. For portfolios with >50 holdings, reduce frontier resolution or use approximate methods.

```python
import numpy as np
from scipy import optimize
from dataclasses import dataclass
from decimal import Decimal

TRADING_DAYS_PER_YEAR = 252
```

---

## 1. Covariance and Expected Returns Estimation

Before any optimization can run, we need two inputs: expected returns vector $\mu$ and covariance matrix $\Sigma$.

### 1.1 Historical Covariance Matrix

Estimated from daily log returns using the Ledoit-Wolf shrinkage estimator (more stable than sample covariance for portfolios with many holdings relative to observations).

**Math:**

$$\hat{\Sigma} = \alpha \cdot F + (1 - \alpha) \cdot S$$

Where:
- $S$ = sample covariance matrix
- $F$ = structured target (constant-correlation model)
- $\alpha$ = optimal shrinkage intensity (Ledoit-Wolf)

**Python pseudocode:**

```python
from sklearn.covariance import LedoitWolf

def estimate_covariance(
    daily_returns: np.ndarray,  # shape (n_days, n_assets)
    annualize: bool = True,
) -> np.ndarray:
    """
    Ledoit-Wolf shrinkage covariance estimator.
    Returns annualized covariance matrix, shape (n_assets, n_assets).
    """
    lw = LedoitWolf().fit(daily_returns)
    cov = lw.covariance_
    if annualize:
        cov = cov * TRADING_DAYS_PER_YEAR
    return cov
```

### 1.2 Expected Returns — Historical Mean

The simplest estimator: annualized mean of daily log returns.

**Math:**

$$\mu_i = \bar{r}_{i,\text{daily}} \times 252$$

**Python pseudocode:**

```python
def expected_returns_historical(
    daily_returns: np.ndarray,  # shape (n_days, n_assets)
) -> np.ndarray:
    """Annualized expected returns from historical mean."""
    return np.mean(daily_returns, axis=0) * TRADING_DAYS_PER_YEAR
```

### 1.3 Expected Returns — CAPM Equilibrium (for Black-Litterman)

Reverse-optimized from market-cap weights — the implied returns that make the market portfolio optimal.

**Math:**

$$\Pi = \delta \cdot \Sigma \cdot w_{mkt}$$

Where:
- $\delta$ = risk aversion coefficient (market Sharpe ratio squared, typically 2.5)
- $\Sigma$ = covariance matrix
- $w_{mkt}$ = market-capitalization weights

**Python pseudocode:**

```python
def equilibrium_returns(
    cov_matrix: np.ndarray,      # shape (n, n)
    market_cap_weights: np.ndarray,  # shape (n,)
    risk_aversion: float = 2.5,
) -> np.ndarray:
    """Implied equilibrium returns (Black-Litterman prior)."""
    return risk_aversion * cov_matrix @ market_cap_weights
```

---

## 2. Classic Markowitz Efficient Frontier

Compute the set of portfolios that maximize expected return for each level of risk (standard deviation), subject to the investor's constraints.

### 2.1 Optimization Problem

**Math:**

For a target return $\mu^*$, find weights $w$ that minimize portfolio variance:

$$\min_w \quad w^T \Sigma w$$

Subject to:

$$w^T \mu = \mu^* \quad \text{(target return)}$$
$$w^T \mathbf{1} = 1 \quad \text{(fully invested)}$$
$$w_i \geq 0 \quad \forall i \quad \text{(long-only)}$$
$$w_i \leq u_i \quad \forall i \quad \text{(position limits)}$$
$$l_c \leq \sum_{i \in C} w_i \leq h_c \quad \forall c \quad \text{(asset class bounds from glidepath)}$$

Where:
- $u_i$ = upper bound for position $i$ (0.10 for individual stocks, 1.0 for broad index ETFs)
- $l_c, h_c$ = lower and upper bounds for asset class $c$ from the glidepath (with tolerance band)

### 2.2 Position Limit Rules

| Security Type | Max Weight | Rationale |
|---------------|-----------|-----------|
| Individual stock | 10% | Concentration risk limit from investment policy |
| Individual bond | 10% | Same as stocks |
| Broad index ETF (>500 holdings) | 100% | Diversified by nature; no single-position cap |
| Sector/thematic ETF (<500 holdings) | 20% | Moderately diversified |
| Crypto (any single token) | 5% | High volatility, speculative |
| Total crypto allocation | Per glidepath | 7% at age 45, declining to 2% at age 60 |

Broad vs. sector ETF classification: based on `securities.holdings_count` field (if available) or manual classification in `securities.etf_category`.

### 2.3 Glidepath Bounds

The glidepath target allocation defines the center of the allowable band. The optimization uses a +/-5% tolerance around the target:

```
For each asset class:
    lower_bound = max(0, glidepath_target[class] - 0.05)
    upper_bound = min(1, glidepath_target[class] + 0.05)
```

At age 45 with target equities = 75%:
- Equities allowed range: 70%–80%
- Fixed income allowed range: 10%–20%
- Crypto allowed range: 2%–12%
- Cash allowed range: 0%–8%

### 2.4 Python Implementation

```python
@dataclass
class EfficientFrontierPoint:
    expected_return: float     # annualized
    volatility: float          # annualized std dev
    sharpe_ratio: float        # (return - rf) / volatility
    weights: np.ndarray        # shape (n_assets,)

@dataclass
class EfficientFrontierResult:
    points: list[EfficientFrontierPoint]
    tangent_portfolio: EfficientFrontierPoint  # max Sharpe
    min_variance_portfolio: EfficientFrontierPoint
    asset_labels: list[str]   # ticker for each weight index

def compute_efficient_frontier(
    expected_returns: np.ndarray,   # shape (n,)
    cov_matrix: np.ndarray,         # shape (n, n)
    risk_free_rate: float,
    position_upper_bounds: np.ndarray,  # shape (n,) — per-asset max weight
    class_membership: dict[str, list[int]],  # {class_name: [asset_indices]}
    class_lower_bounds: dict[str, float],
    class_upper_bounds: dict[str, float],
    n_points: int = 50,
) -> EfficientFrontierResult:
    """
    Compute the efficient frontier with constraints.
    Returns n_points along the frontier plus the tangent and min-variance portfolios.
    """
    n = len(expected_returns)

    def portfolio_variance(w):
        return w @ cov_matrix @ w

    def portfolio_return(w):
        return w @ expected_returns

    # Constraints common to all optimizations
    constraints = [
        {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},  # fully invested
    ]

    # Asset class bounds
    for cls_name, indices in class_membership.items():
        lb = class_lower_bounds.get(cls_name, 0.0)
        ub = class_upper_bounds.get(cls_name, 1.0)
        constraints.append(
            {"type": "ineq", "fun": lambda w, idx=indices, lb=lb: np.sum(w[idx]) - lb}
        )
        constraints.append(
            {"type": "ineq", "fun": lambda w, idx=indices, ub=ub: ub - np.sum(w[idx])}
        )

    # Bounds: long-only + position limits
    bounds = [(0.0, ub) for ub in position_upper_bounds]

    # Initial guess: equal weight (clipped to bounds)
    w0 = np.full(n, 1.0 / n)
    w0 = np.clip(w0, [b[0] for b in bounds], [b[1] for b in bounds])
    w0 /= w0.sum()  # renormalize

    # Step 1: Find minimum variance portfolio
    result_min_var = optimize.minimize(
        portfolio_variance,
        w0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 1000, "ftol": 1e-12},
    )
    min_var_weights = result_min_var.x
    min_var_return = portfolio_return(min_var_weights)

    # Step 2: Find maximum return portfolio
    result_max_ret = optimize.minimize(
        lambda w: -portfolio_return(w),
        w0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 1000, "ftol": 1e-12},
    )
    max_return = portfolio_return(result_max_ret.x)

    # Step 3: Trace the frontier between min-variance return and max return
    target_returns = np.linspace(min_var_return, max_return, n_points)
    points = []

    for target_ret in target_returns:
        ret_constraint = {"type": "eq", "fun": lambda w, t=target_ret: portfolio_return(w) - t}
        all_constraints = constraints + [ret_constraint]

        result = optimize.minimize(
            portfolio_variance,
            w0,
            method="SLSQP",
            bounds=bounds,
            constraints=all_constraints,
            options={"maxiter": 1000, "ftol": 1e-12},
        )

        if result.success:
            w = result.x
            vol = float(np.sqrt(w @ cov_matrix @ w))
            ret = float(w @ expected_returns)
            sharpe = (ret - risk_free_rate) / vol if vol > 0 else 0.0
            points.append(EfficientFrontierPoint(
                expected_return=ret,
                volatility=vol,
                sharpe_ratio=sharpe,
                weights=w,
            ))

    # Step 4: Find tangent portfolio (max Sharpe)
    def neg_sharpe(w):
        ret = w @ expected_returns
        vol = np.sqrt(w @ cov_matrix @ w)
        return -(ret - risk_free_rate) / vol if vol > 1e-10 else 0.0

    result_tangent = optimize.minimize(
        neg_sharpe,
        w0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 1000, "ftol": 1e-12},
    )
    tangent_w = result_tangent.x
    tangent_vol = float(np.sqrt(tangent_w @ cov_matrix @ tangent_w))
    tangent_ret = float(tangent_w @ expected_returns)
    tangent_sharpe = (tangent_ret - risk_free_rate) / tangent_vol if tangent_vol > 0 else 0.0

    tangent = EfficientFrontierPoint(
        expected_return=tangent_ret,
        volatility=tangent_vol,
        sharpe_ratio=tangent_sharpe,
        weights=tangent_w,
    )

    min_var = EfficientFrontierPoint(
        expected_return=float(min_var_return),
        volatility=float(np.sqrt(min_var_weights @ cov_matrix @ min_var_weights)),
        sharpe_ratio=(float(min_var_return) - risk_free_rate) /
                     float(np.sqrt(min_var_weights @ cov_matrix @ min_var_weights)),
        weights=min_var_weights,
    )

    return EfficientFrontierResult(
        points=points,
        tangent_portfolio=tangent,
        min_variance_portfolio=min_var,
        asset_labels=[],  # filled by caller
    )
```

### 2.5 Worked Example

Portfolio with 5 assets, age 45 (glidepath: equities 70-80%, fixed income 10-20%, crypto 2-12%).

**Assets:**

| Asset | Type | Class | Expected Return | Volatility | Max Weight |
|-------|------|-------|-----------------|-----------|-----------|
| IWDA.AS | Broad ETF | Equities | 8.5% | 15.0% | 100% |
| NOKIA.HE | Stock | Equities | 12.0% | 28.0% | 10% |
| SAMPO.HE | Stock | Equities | 10.0% | 22.0% | 10% |
| VGEA.DE | Bond ETF | Fixed Income | 3.5% | 5.0% | 100% |
| BTC | Crypto | Crypto | 25.0% | 65.0% | 5% |

**Correlation matrix:**

|  | IWDA | NOKIA | SAMPO | VGEA | BTC |
|--|------|-------|-------|------|-----|
| IWDA | 1.00 | 0.62 | 0.71 | -0.15 | 0.35 |
| NOKIA | 0.62 | 1.00 | 0.85 | -0.08 | 0.28 |
| SAMPO | 0.71 | 0.85 | 1.00 | -0.10 | 0.30 |
| VGEA | -0.15 | -0.08 | -0.10 | 1.00 | -0.22 |
| BTC | 0.35 | 0.28 | 0.30 | -0.22 | 1.00 |

**Tangent portfolio result (max Sharpe, constrained):**

| Asset | Weight |
|-------|--------|
| IWDA.AS | 58.0% |
| NOKIA.HE | 7.0% |
| SAMPO.HE | 5.0% |
| VGEA.DE | 25.0% |
| BTC | 5.0% |

- Expected return: 9.2%
- Volatility: 12.8%
- Sharpe ratio: (9.2% - 3.5%) / 12.8% = 0.45

**Constraint verification:**
- Equities: 58% + 7% + 5% = 70% (within 70-80% band)
- Fixed income: 25% (within 10-20%? No — 25% exceeds the 20% upper bound)

This illustrates that the optimizer may push fixed income above the glidepath upper bound to capture the diversification benefit. The glidepath constraint would cap it at 20%, forcing more into equities:

| Asset | Weight (constrained) |
|-------|---------------------|
| IWDA.AS | 63.0% |
| NOKIA.HE | 7.0% |
| SAMPO.HE | 5.0% |
| VGEA.DE | 20.0% |
| BTC | 5.0% |

- Equities: 75%, Fixed Income: 20%, Crypto: 5% — all within bounds.

---

## 3. Constrained Optimization — Optimal Portfolio for Risk Tolerance

Given a risk tolerance parameter $\lambda$ (risk aversion), find the single optimal portfolio.

### 3.1 Optimization Problem

**Math:**

$$\max_w \quad w^T \mu - \frac{\lambda}{2} w^T \Sigma w$$

Subject to the same constraints as Section 2.1.

Where $\lambda$ controls the risk-return tradeoff:
- $\lambda = 0$: maximize return only (no risk penalty)
- $\lambda \to \infty$: minimize variance only
- Typical range: 1–10

### 3.2 Risk Tolerance Mapping

Map a user-friendly 1–10 scale to $\lambda$:

| User Scale | $\lambda$ | Description |
|-----------|-----------|-------------|
| 1 (aggressive) | 0.5 | Heavy tilt toward return maximization |
| 3 | 1.5 | Growth-oriented |
| 5 (balanced) | 3.0 | Standard risk-return tradeoff |
| 7 | 6.0 | Conservative-leaning |
| 10 (conservative) | 15.0 | Near minimum-variance |

Default for this investor profile (Munger/Boglehead hybrid, 15-year horizon): **5** ($\lambda = 3.0$).

### 3.3 Python Implementation

```python
@dataclass
class OptimalPortfolioResult:
    weights: dict[str, float]       # {ticker: weight}
    expected_return: float           # annualized
    volatility: float                # annualized
    sharpe_ratio: float
    risk_tolerance: int              # 1-10 scale
    lambda_value: float              # actual risk aversion
    glidepath_compliant: bool        # all class bounds satisfied
    constraint_violations: list[str] # empty if compliant

LAMBDA_MAP = {1: 0.5, 2: 1.0, 3: 1.5, 4: 2.0, 5: 3.0, 6: 4.0, 7: 6.0, 8: 8.0, 9: 12.0, 10: 15.0}

def compute_optimal_portfolio(
    expected_returns: np.ndarray,
    cov_matrix: np.ndarray,
    risk_free_rate: float,
    risk_tolerance: int,            # 1–10
    position_upper_bounds: np.ndarray,
    class_membership: dict[str, list[int]],
    class_lower_bounds: dict[str, float],
    class_upper_bounds: dict[str, float],
    tickers: list[str],
) -> OptimalPortfolioResult:
    """Find the optimal portfolio for a given risk tolerance."""
    n = len(expected_returns)
    lam = LAMBDA_MAP[risk_tolerance]

    def neg_utility(w):
        ret = w @ expected_returns
        var = w @ cov_matrix @ w
        return -(ret - (lam / 2) * var)

    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
    for cls_name, indices in class_membership.items():
        lb = class_lower_bounds.get(cls_name, 0.0)
        ub = class_upper_bounds.get(cls_name, 1.0)
        constraints.append({"type": "ineq", "fun": lambda w, idx=indices, lb=lb: np.sum(w[idx]) - lb})
        constraints.append({"type": "ineq", "fun": lambda w, idx=indices, ub=ub: ub - np.sum(w[idx])})

    bounds = [(0.0, ub) for ub in position_upper_bounds]
    w0 = np.full(n, 1.0 / n)
    w0 = np.clip(w0, [b[0] for b in bounds], [b[1] for b in bounds])
    w0 /= w0.sum()

    result = optimize.minimize(
        neg_utility, w0, method="SLSQP",
        bounds=bounds, constraints=constraints,
        options={"maxiter": 1000, "ftol": 1e-12},
    )

    w = result.x
    ret = float(w @ expected_returns)
    vol = float(np.sqrt(w @ cov_matrix @ w))
    sharpe = (ret - risk_free_rate) / vol if vol > 0 else 0.0

    return OptimalPortfolioResult(
        weights={tickers[i]: float(w[i]) for i in range(n)},
        expected_return=ret,
        volatility=vol,
        sharpe_ratio=sharpe,
        risk_tolerance=risk_tolerance,
        lambda_value=lam,
        glidepath_compliant=result.success,
        constraint_violations=[],
    )
```

---

## 4. Black-Litterman Model

Incorporates the investor's subjective views (bull/bear cases from research notes) into the expected returns, producing a blended posterior that is more stable than pure historical estimates.

### 4.1 Overview

1. Start with **market equilibrium returns** $\Pi$ (Section 1.3) as the prior.
2. Express **investor views** as linear combinations of expected returns with confidence levels.
3. Blend prior and views using Bayesian updating to get **posterior returns** $\mu_{BL}$.
4. Use $\mu_{BL}$ in place of $\mu$ for Markowitz optimization.

### 4.2 View Specification

**Absolute view**: "I expect NOKIA.HE to return 15% per year" with 70% confidence.

**Relative view**: "I expect NOKIA.HE to outperform SAMPO.HE by 3% per year" with 60% confidence.

**Math:**

Views are encoded as:

$$P \cdot \mu = Q + \epsilon, \quad \epsilon \sim N(0, \Omega)$$

Where:
- $P$ = pick matrix (k views x n assets) — each row defines which assets are involved
- $Q$ = view returns vector (k x 1)
- $\Omega$ = diagonal uncertainty matrix (k x k) — lower confidence = higher diagonal entry

### 4.3 Posterior Returns

**Math:**

$$\mu_{BL} = [(\tau \Sigma)^{-1} + P^T \Omega^{-1} P]^{-1} [(\tau \Sigma)^{-1} \Pi + P^T \Omega^{-1} Q]$$

Where:
- $\tau$ = scaling factor for the uncertainty of the prior (typically 0.05, reflecting that the mean is estimated less precisely than the covariance)
- $\Pi$ = equilibrium returns (prior)
- All other terms as defined above

### 4.4 Confidence-to-Uncertainty Mapping

The investor expresses confidence as a percentage (0-100%). This must be converted to the diagonal entries of $\Omega$.

**Formula:**

$$\omega_{k} = \frac{1 - c_k}{c_k} \cdot p_k^T (\tau \Sigma) p_k$$

Where:
- $c_k$ = confidence for view $k$ (e.g., 0.70 for 70%)
- $p_k$ = row $k$ of the pick matrix $P$
- Higher confidence $\to$ lower $\omega_k$ $\to$ view has more influence on posterior

**Boundaries:**
- Minimum confidence: 10% (below this, the view has almost no effect — reject it)
- Maximum confidence: 95% (above this, it overrides the market entirely — cap it)

### 4.5 Python Implementation

```python
@dataclass
class InvestorView:
    view_type: str           # "absolute" or "relative"
    asset_1: str             # ticker of the primary asset
    asset_2: str | None      # ticker of the secondary asset (relative views only)
    expected_return: float   # annualized (e.g., 0.15 for 15%)
    confidence: float        # 0.10 to 0.95

@dataclass
class BlackLittermanResult:
    posterior_returns: dict[str, float]   # {ticker: expected_return}
    prior_returns: dict[str, float]       # {ticker: equilibrium_return}
    posterior_cov: np.ndarray
    views_applied: list[InvestorView]
    views_rejected: list[tuple[InvestorView, str]]  # (view, reason)

def black_litterman(
    cov_matrix: np.ndarray,            # (n, n) annualized
    market_cap_weights: np.ndarray,    # (n,)
    views: list[InvestorView],
    tickers: list[str],
    risk_aversion: float = 2.5,
    tau: float = 0.05,
) -> BlackLittermanResult:
    """
    Compute Black-Litterman posterior expected returns.
    """
    n = len(tickers)
    ticker_idx = {t: i for i, t in enumerate(tickers)}

    # Prior: equilibrium returns
    pi = risk_aversion * cov_matrix @ market_cap_weights

    # Build P matrix and Q vector from views
    valid_views = []
    rejected_views = []
    P_rows = []
    Q_values = []
    omega_diag = []

    for v in views:
        # Validate confidence range
        if v.confidence < 0.10:
            rejected_views.append((v, "confidence_too_low"))
            continue
        if v.confidence > 0.95:
            v = InvestorView(v.view_type, v.asset_1, v.asset_2, v.expected_return, 0.95)

        if v.asset_1 not in ticker_idx:
            rejected_views.append((v, "asset_not_in_portfolio"))
            continue

        p = np.zeros(n)
        if v.view_type == "absolute":
            p[ticker_idx[v.asset_1]] = 1.0
        elif v.view_type == "relative":
            if v.asset_2 is None or v.asset_2 not in ticker_idx:
                rejected_views.append((v, "relative_view_missing_asset_2"))
                continue
            p[ticker_idx[v.asset_1]] = 1.0
            p[ticker_idx[v.asset_2]] = -1.0
        else:
            rejected_views.append((v, "unknown_view_type"))
            continue

        P_rows.append(p)
        Q_values.append(v.expected_return)

        # Confidence -> uncertainty
        omega_k = ((1 - v.confidence) / v.confidence) * (p @ (tau * cov_matrix) @ p)
        omega_diag.append(omega_k)
        valid_views.append(v)

    if len(valid_views) == 0:
        # No valid views: return equilibrium returns as-is
        return BlackLittermanResult(
            posterior_returns={tickers[i]: float(pi[i]) for i in range(n)},
            prior_returns={tickers[i]: float(pi[i]) for i in range(n)},
            posterior_cov=cov_matrix,
            views_applied=[],
            views_rejected=rejected_views,
        )

    P = np.array(P_rows)           # (k, n)
    Q = np.array(Q_values)         # (k,)
    Omega = np.diag(omega_diag)    # (k, k)

    # Posterior returns
    tau_sigma_inv = np.linalg.inv(tau * cov_matrix)
    Pt_Omega_inv = P.T @ np.linalg.inv(Omega)

    M_inv = np.linalg.inv(tau_sigma_inv + Pt_Omega_inv @ P)
    mu_bl = M_inv @ (tau_sigma_inv @ pi + Pt_Omega_inv @ Q)

    # Posterior covariance
    posterior_cov = cov_matrix + np.linalg.inv(tau_sigma_inv + Pt_Omega_inv @ P)

    return BlackLittermanResult(
        posterior_returns={tickers[i]: float(mu_bl[i]) for i in range(n)},
        prior_returns={tickers[i]: float(pi[i]) for i in range(n)},
        posterior_cov=posterior_cov,
        views_applied=valid_views,
        views_rejected=rejected_views,
    )
```

### 4.6 Worked Example

Using the 5-asset portfolio from Section 2.5. Market-cap weights (approximate):

| Asset | Market Cap Weight |
|-------|------------------|
| IWDA.AS | 0.70 |
| NOKIA.HE | 0.05 |
| SAMPO.HE | 0.05 |
| VGEA.DE | 0.15 |
| BTC | 0.05 |

**Equilibrium returns** ($\delta = 2.5$):

Computed as $\Pi = 2.5 \cdot \Sigma \cdot w_{mkt}$. Approximate results:

| Asset | Equilibrium Return |
|-------|-------------------|
| IWDA.AS | 7.8% |
| NOKIA.HE | 9.2% |
| SAMPO.HE | 8.5% |
| VGEA.DE | 1.2% |
| BTC | 12.0% |

**Investor views:**

1. Absolute: "NOKIA.HE will return 15% over the next year" — confidence 70%
2. Relative: "IWDA.AS will outperform VGEA.DE by 8%" — confidence 80%

**Posterior returns** (after blending):

| Asset | Equilibrium | Posterior | Change |
|-------|------------|-----------|--------|
| IWDA.AS | 7.8% | 8.6% | +0.8% |
| NOKIA.HE | 9.2% | 12.8% | +3.6% |
| SAMPO.HE | 8.5% | 9.4% | +0.9% |
| VGEA.DE | 1.2% | 0.4% | -0.8% |
| BTC | 12.0% | 12.3% | +0.3% |

The NOKIA bullish view raised its posterior from 9.2% to 12.8% (not fully to 15% because the 70% confidence leaves room for the equilibrium prior). The IWDA vs VGEA relative view increased the spread between them.

These posterior returns are then fed into the Markowitz optimizer (Section 2) for a Black-Litterman optimal portfolio.

---

## 5. Risk Budgeting and Risk Parity

An alternative to mean-variance that allocates risk (variance contribution) rather than capital. Avoids the sensitivity of mean-variance to expected return estimates.

### 5.1 Risk Contribution

The marginal risk contribution of asset $i$:

$$MRC_i = \frac{(\Sigma w)_i}{\sqrt{w^T \Sigma w}}$$

The total risk contribution of asset $i$:

$$RC_i = w_i \cdot MRC_i = \frac{w_i (\Sigma w)_i}{\sqrt{w^T \Sigma w}}$$

**Property**: $\sum_i RC_i = \sigma_p$ (portfolio volatility).

### 5.2 Equal Risk Contribution (ERC) Portfolio

Find weights such that each asset contributes equally to portfolio risk:

$$RC_i = \frac{\sigma_p}{n} \quad \forall i$$

Equivalently, solve:

$$\min_w \sum_{i=1}^{n} \left( w_i (\Sigma w)_i - \frac{w^T \Sigma w}{n} \right)^2$$

Subject to: $w_i \geq 0$, $\sum w_i = 1$.

### 5.3 Python Implementation

```python
@dataclass
class RiskParityResult:
    weights: dict[str, float]         # {ticker: weight}
    risk_contributions: dict[str, float]  # {ticker: pct of total risk}
    portfolio_volatility: float        # annualized
    expected_return: float             # annualized (informational)

def compute_risk_parity(
    cov_matrix: np.ndarray,
    expected_returns: np.ndarray,
    tickers: list[str],
    target_risk_budgets: np.ndarray | None = None,  # None = equal risk
) -> RiskParityResult:
    """
    Compute the Equal Risk Contribution (or custom risk budget) portfolio.
    """
    n = len(tickers)

    if target_risk_budgets is None:
        target_risk_budgets = np.full(n, 1.0 / n)

    def objective(w):
        sigma_p = np.sqrt(w @ cov_matrix @ w)
        if sigma_p < 1e-10:
            return 0.0
        mrc = (cov_matrix @ w) / sigma_p
        rc = w * mrc
        # Minimize squared difference between actual and target risk contributions
        target_rc = target_risk_budgets * sigma_p
        return float(np.sum((rc - target_rc) ** 2))

    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
    bounds = [(0.01, 1.0) for _ in range(n)]  # small floor to avoid zero weights
    w0 = np.full(n, 1.0 / n)

    result = optimize.minimize(
        objective, w0, method="SLSQP",
        bounds=bounds, constraints=constraints,
        options={"maxiter": 1000, "ftol": 1e-14},
    )

    w = result.x
    sigma_p = float(np.sqrt(w @ cov_matrix @ w))
    mrc = (cov_matrix @ w) / sigma_p if sigma_p > 1e-10 else np.zeros(n)
    rc = w * mrc
    rc_pct = rc / sigma_p if sigma_p > 1e-10 else np.full(n, 1.0 / n)

    return RiskParityResult(
        weights={tickers[i]: float(w[i]) for i in range(n)},
        risk_contributions={tickers[i]: float(rc_pct[i]) for i in range(n)},
        portfolio_volatility=sigma_p,
        expected_return=float(w @ expected_returns),
    )
```

### 5.4 Worked Example

Using the 5-asset covariance matrix from Section 2.5:

**ERC portfolio weights:**

| Asset | Volatility | MV Weight (from Markowitz) | ERC Weight | Risk Contribution |
|-------|-----------|---------------------------|-----------|-------------------|
| IWDA.AS | 15.0% | 63.0% | 28.0% | 20.0% |
| NOKIA.HE | 28.0% | 7.0% | 10.0% | 20.0% |
| SAMPO.HE | 22.0% | 5.0% | 13.0% | 20.0% |
| VGEA.DE | 5.0% | 20.0% | 42.0% | 20.0% |
| BTC | 65.0% | 5.0% | 7.0% | 20.0% |

Key insight: the ERC portfolio gives VGEA.DE (bond ETF) the largest weight (42%) because its low volatility means it needs more capital to contribute the same risk as the volatile assets. BTC gets only 7% capital weight but contributes the same 20% risk as every other asset.

This contrasts with the Markowitz tangent portfolio where weights are driven by expected returns. Risk parity is useful as a "model-free" comparison that does not depend on return estimates.

---

## 6. Rebalancing Recommendations

Given the current portfolio and the optimal allocation (from any method above), generate specific trade recommendations that are tax-aware and respect account constraints.

### 6.1 Rebalancing Logic

The rebalancing engine from [glidepath.md](../03-calculations/glidepath.md) is extended here with optimization-aware logic.

**Priority order for executing trades:**

1. **Cash-flow rebalancing**: direct new deposits to underweight positions (no sells needed)
2. **Tax-free rebalancing**: sell overweight positions inside osakesaastotili (no tax impact)
3. **Tax-loss harvesting**: sell overweight positions with unrealized losses in regular accounts (creates deductible loss)
4. **Low-gain sells**: sell overweight positions with the smallest unrealized gains
5. **High-gain sells**: sell overweight positions with large gains only as last resort

### 6.2 Minimum Trade Size

To avoid excessive transaction costs (Nordnet commission structure):

| Condition | Threshold |
|-----------|-----------|
| Minimum individual trade | 500 EUR (50,000 cents) |
| Minimum total rebalancing | 1,000 EUR (100,000 cents) |
| Ignore drift below | 50 EUR per position |

If the optimal rebalancing involves trades below these thresholds, defer the rebalancing and continue monitoring.

### 6.3 Account Routing

Each buy/sell must be routed to the correct account:

| Instrument Type | Preferred Account | Fallback |
|----------------|-------------------|----------|
| Finnish/EU stocks | Osakesaastotili (OST) | Regular (AOT) |
| Equity ETFs (EU UCITS) | Osakesaastotili (OST) | Regular (AOT) |
| Bond ETFs | Regular (AOT) | — |
| US stocks | Regular (AOT) | — |
| Crypto | Crypto wallet | — |
| Bonds (direct) | Regular (AOT) | — |

**OST constraints:**
- Lifetime deposit limit: 50,000 EUR. Check remaining capacity before routing buys to OST.
- Can only hold stocks and equity ETFs.
- Sells inside OST are tax-free (but withdrawals from OST are taxed at capital gains rate on the entire gain since inception).

### 6.4 Python Implementation

```python
@dataclass
class TradeRecommendation:
    action: str                    # "buy" or "sell"
    ticker: str
    security_id: int
    account_id: int
    account_type: str              # "regular", "osakesaastotili", "crypto_wallet"
    amount_eur_cents: int          # trade value in EUR cents
    estimated_quantity: Decimal     # approximate shares/units
    tax_lot_id: int | None         # for sells: specific lot to close
    estimated_tax_cents: int       # estimated capital gains tax impact
    rationale: str                 # human-readable explanation
    priority: int                  # execution order (1 = first)

@dataclass
class RebalanceResult:
    trades: list[TradeRecommendation]
    current_weights: dict[str, float]
    target_weights: dict[str, float]
    post_trade_weights: dict[str, float]   # projected weights after all trades
    total_buy_cents: int
    total_sell_cents: int
    total_estimated_tax_cents: int
    net_cash_required_cents: int           # >0 if additional cash needed
    optimization_method: str               # "markowitz", "black_litterman", "risk_parity"

def generate_rebalance_trades(
    current_holdings: list[dict],    # [{security_id, ticker, account_id, account_type, market_value_cents, ...}]
    target_weights: dict[str, float],
    total_portfolio_cents: int,
    available_cash_cents: int,
    tax_lots: list[dict],            # [{lot_id, security_id, account_id, cost_basis_cents, market_value_cents, ...}]
    ost_deposit_remaining_cents: int,
    min_trade_cents: int = 50_000,   # 500 EUR
) -> RebalanceResult:
    """
    Generate tax-aware rebalancing trades to move from current to target weights.
    """
    # Step 1: Compute deltas (target value - current value) per security
    deltas = {}
    for ticker, target_w in target_weights.items():
        target_value = int(target_w * total_portfolio_cents)
        current_value = sum(
            h["market_value_cents"] for h in current_holdings if h["ticker"] == ticker
        )
        delta = target_value - current_value
        if abs(delta) >= min_trade_cents:
            deltas[ticker] = delta

    trades = []
    priority = 1

    # Step 2: Allocate available cash to underweight positions first
    remaining_cash = available_cash_cents
    for ticker in sorted(deltas, key=lambda t: deltas[t], reverse=True):
        if deltas[ticker] <= 0:
            continue
        buy_amount = min(deltas[ticker], remaining_cash)
        if buy_amount >= min_trade_cents:
            trades.append(TradeRecommendation(
                action="buy",
                ticker=ticker,
                security_id=_lookup_security_id(ticker),
                account_id=_select_buy_account(ticker, ost_deposit_remaining_cents),
                account_type=_select_buy_account_type(ticker),
                amount_eur_cents=buy_amount,
                estimated_quantity=_estimate_quantity(ticker, buy_amount),
                tax_lot_id=None,
                estimated_tax_cents=0,
                rationale=f"Cash-flow rebalancing: buy {ticker} to close underweight gap",
                priority=priority,
            ))
            remaining_cash -= buy_amount
            deltas[ticker] -= buy_amount
            priority += 1

    # Step 3: For remaining underweight positions, generate sell trades from overweight
    sells_needed = sum(-d for d in deltas.values() if d < 0)

    for ticker in sorted(deltas, key=lambda t: deltas[t]):
        if deltas[ticker] >= 0:
            continue
        sell_amount = -deltas[ticker]

        # Select lots in priority order (tax-free first, then losses, then low gains)
        lots_for_ticker = sorted(
            [lot for lot in tax_lots if lot["ticker"] == ticker],
            key=lambda l: _sell_priority_score(l),
        )

        remaining_sell = sell_amount
        for lot in lots_for_ticker:
            if remaining_sell < min_trade_cents:
                break
            lot_sell = min(lot["market_value_cents"], remaining_sell)
            tax_impact = _estimate_tax(lot, lot_sell)

            trades.append(TradeRecommendation(
                action="sell",
                ticker=ticker,
                security_id=lot["security_id"],
                account_id=lot["account_id"],
                account_type=lot["account_type"],
                amount_eur_cents=lot_sell,
                estimated_quantity=_estimate_sell_quantity(lot, lot_sell),
                tax_lot_id=lot["lot_id"],
                estimated_tax_cents=tax_impact,
                rationale=_sell_rationale(lot, lot_sell),
                priority=priority,
            ))
            remaining_sell -= lot_sell
            priority += 1

    return RebalanceResult(
        trades=trades,
        current_weights=_compute_current_weights(current_holdings, total_portfolio_cents),
        target_weights=target_weights,
        post_trade_weights=_project_post_trade_weights(current_holdings, trades, total_portfolio_cents),
        total_buy_cents=sum(t.amount_eur_cents for t in trades if t.action == "buy"),
        total_sell_cents=sum(t.amount_eur_cents for t in trades if t.action == "sell"),
        total_estimated_tax_cents=sum(t.estimated_tax_cents for t in trades),
        net_cash_required_cents=max(0, sum(
            t.amount_eur_cents for t in trades if t.action == "buy"
        ) - sum(
            t.amount_eur_cents for t in trades if t.action == "sell"
        ) - available_cash_cents),
        optimization_method="markowitz",
    )

def _sell_priority_score(lot: dict) -> tuple:
    """
    Lower score = sell first.
    Priority: OST lots > loss lots > lots held >10y > smallest gain lots.
    """
    is_ost = 0 if lot["account_type"] == "osakesaastotili" else 1
    gain = lot["market_value_cents"] - lot["cost_basis_cents"]
    is_loss = 0 if gain < 0 else 1
    return (is_ost, is_loss, gain)
```

### 6.5 Worked Example: Tax-Aware Rebalancing

Portfolio: 200,000 EUR. Current vs optimal (Markowitz, risk tolerance 5):

| Ticker | Current Weight | Current Value | Optimal Weight | Optimal Value | Delta |
|--------|---------------|---------------|----------------|---------------|-------|
| IWDA.AS | 55% | 110,000 | 63% | 126,000 | +16,000 |
| NOKIA.HE | 15% | 30,000 | 7% | 14,000 | -16,000 |
| SAMPO.HE | 8% | 16,000 | 5% | 10,000 | -6,000 |
| VGEA.DE | 15% | 30,000 | 20% | 40,000 | +10,000 |
| BTC | 7% | 14,000 | 5% | 10,000 | -4,000 |

Available cash: 2,000 EUR. OST deposit remaining: 15,000 EUR.

**Tax lots for NOKIA.HE (in regular account):**

| Lot | Cost Basis | Market Value | Unrealized P&L | Held Since |
|-----|-----------|-------------|----------------|-----------|
| A | 18,000 EUR | 20,000 EUR | +2,000 EUR | 2023-05-10 |
| B | 12,000 EUR | 10,000 EUR | -2,000 EUR | 2024-11-01 |

**Generated trades (in execution order):**

1. **BUY** 2,000 EUR of IWDA.AS in OST — cash-flow rebalancing (use available cash)
2. **SELL** 10,000 EUR of NOKIA.HE (Lot B) in regular account — tax-loss harvesting. Estimated tax: 0 EUR (it is a loss). Realized loss: -2,000 EUR (can offset other gains).
3. **SELL** 6,000 EUR of NOKIA.HE (Lot A) in regular account — smallest gain first. Estimated gain: 6,000 * (2,000/20,000) = 600 EUR. Tax: 600 * 0.30 = 180 EUR.
4. **SELL** 6,000 EUR of SAMPO.HE — per lot analysis.
5. **SELL** 4,000 EUR of BTC — per lot analysis.
6. **BUY** 14,000 EUR of IWDA.AS in OST — uses sell proceeds. (Total IWDA buy = 16,000.)
7. **BUY** 10,000 EUR of VGEA.DE in regular account — bonds cannot go in OST.

**Post-trade verification:**
- Total sells: 26,000 EUR. Total buys: 26,000 EUR (16,000 + 10,000). Cash required: 0 EUR (2,000 cash + 26,000 sell proceeds fund the 26,000 + 2,000 buys).
- Estimated total tax: 180 EUR (from NOKIA Lot A partial sell) minus 2,000 EUR loss harvested = net tax benefit.

---

## 7. API Endpoints

### 7.1 Efficient Frontier

```
GET /api/v1/optimization/efficient-frontier
```

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `lookbackDays` | int | 252 | Historical window for return/covariance estimation |
| `nPoints` | int | 50 | Number of points along the frontier |
| `includeWeights` | bool | false | Include full weight vectors (large response) |

**Response:**

```json
{
  "data": {
    "frontier": [
      {
        "expectedReturn": 0.065,
        "volatility": 0.08,
        "sharpeRatio": 0.38,
        "weights": {"IWDA.AS": 0.70, "NOKIA.HE": 0.0, "VGEA.DE": 0.30}
      }
    ],
    "tangentPortfolio": {
      "expectedReturn": 0.092,
      "volatility": 0.128,
      "sharpeRatio": 0.45,
      "weights": {"IWDA.AS": 0.63, "NOKIA.HE": 0.07, "SAMPO.HE": 0.05, "VGEA.DE": 0.20, "BTC": 0.05}
    },
    "minVariancePortfolio": {
      "expectedReturn": 0.042,
      "volatility": 0.048,
      "sharpeRatio": 0.15,
      "weights": {"IWDA.AS": 0.15, "VGEA.DE": 0.80, "SAMPO.HE": 0.05}
    },
    "currentPortfolio": {
      "expectedReturn": 0.085,
      "volatility": 0.145,
      "sharpeRatio": 0.38
    },
    "constraints": {
      "glidepathBounds": {
        "equities": {"lower": 0.70, "upper": 0.80},
        "fixedIncome": {"lower": 0.10, "upper": 0.20},
        "crypto": {"lower": 0.02, "upper": 0.12},
        "cash": {"lower": 0.0, "upper": 0.08}
      },
      "positionLimits": {
        "singleStock": 0.10,
        "broadEtf": 1.00,
        "sectorEtf": 0.20,
        "singleCrypto": 0.05
      }
    }
  },
  "meta": {
    "calculatedAt": "2026-03-21T14:30:00Z",
    "lookbackDays": 252,
    "tradingDaysAvailable": 248,
    "riskFreeRate": 0.035,
    "covarianceMethod": "ledoit_wolf",
    "computeTimeMs": 1230
  }
}
```

### 7.2 Optimal Portfolio

```
GET /api/v1/optimization/optimal
```

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `riskTolerance` | int | 5 | 1 (aggressive) to 10 (conservative) |
| `lookbackDays` | int | 252 | Historical window |
| `method` | string | `markowitz` | `markowitz` or `risk_parity` |

**Response:**

```json
{
  "data": {
    "weights": {
      "IWDA.AS": 0.63,
      "NOKIA.HE": 0.07,
      "SAMPO.HE": 0.05,
      "VGEA.DE": 0.20,
      "BTC": 0.05
    },
    "expectedReturn": 0.092,
    "volatility": 0.128,
    "sharpeRatio": 0.45,
    "riskTolerance": 5,
    "lambdaValue": 3.0,
    "glidepathCompliant": true,
    "method": "markowitz",
    "comparisonToCurrent": {
      "expectedReturnDelta": 0.007,
      "volatilityDelta": -0.017,
      "sharpeRatioDelta": 0.07
    }
  },
  "meta": {
    "calculatedAt": "2026-03-21T14:30:00Z",
    "lookbackDays": 252,
    "riskFreeRate": 0.035,
    "computeTimeMs": 450
  }
}
```

### 7.3 Black-Litterman

```
POST /api/v1/optimization/black-litterman
```

**Request Body:**

```json
{
  "views": [
    {
      "viewType": "absolute",
      "asset1": "NOKIA.HE",
      "asset2": null,
      "expectedReturn": 0.15,
      "confidence": 0.70
    },
    {
      "viewType": "relative",
      "asset1": "IWDA.AS",
      "asset2": "VGEA.DE",
      "expectedReturn": 0.08,
      "confidence": 0.80
    }
  ],
  "riskTolerance": 5,
  "lookbackDays": 252
}
```

**Response:**

```json
{
  "data": {
    "posteriorReturns": {
      "IWDA.AS": 0.086,
      "NOKIA.HE": 0.128,
      "SAMPO.HE": 0.094,
      "VGEA.DE": 0.004,
      "BTC": 0.123
    },
    "priorReturns": {
      "IWDA.AS": 0.078,
      "NOKIA.HE": 0.092,
      "SAMPO.HE": 0.085,
      "VGEA.DE": 0.012,
      "BTC": 0.120
    },
    "optimalWeights": {
      "IWDA.AS": 0.58,
      "NOKIA.HE": 0.10,
      "SAMPO.HE": 0.05,
      "VGEA.DE": 0.22,
      "BTC": 0.05
    },
    "expectedReturn": 0.098,
    "volatility": 0.135,
    "sharpeRatio": 0.47,
    "viewsApplied": 2,
    "viewsRejected": 0
  },
  "meta": {
    "calculatedAt": "2026-03-21T14:30:00Z",
    "lookbackDays": 252,
    "riskFreeRate": 0.035,
    "tau": 0.05,
    "riskAversion": 2.5,
    "computeTimeMs": 780
  }
}
```

### 7.4 Rebalance Recommendations

```
GET /api/v1/optimization/rebalance
```

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `method` | string | `markowitz` | `markowitz`, `black_litterman`, or `risk_parity` |
| `riskTolerance` | int | 5 | 1–10 scale |
| `minTradeCents` | int | 50000 | Minimum trade size (EUR cents) |
| `dryRun` | bool | true | If true, only compute — do not persist |

**Response:**

```json
{
  "data": {
    "trades": [
      {
        "action": "sell",
        "ticker": "NOKIA.HE",
        "securityId": 42,
        "accountId": 1,
        "accountType": "regular",
        "amountEurCents": 1000000,
        "estimatedQuantity": 2083.33,
        "taxLotId": 17,
        "estimatedTaxCents": 0,
        "rationale": "Tax-loss harvesting: sell NOKIA.HE lot with -2,000 EUR unrealized loss",
        "priority": 1
      },
      {
        "action": "buy",
        "ticker": "IWDA.AS",
        "securityId": 5,
        "accountId": 2,
        "accountType": "osakesaastotili",
        "amountEurCents": 1600000,
        "estimatedQuantity": 193.94,
        "taxLotId": null,
        "estimatedTaxCents": 0,
        "rationale": "Buy IWDA.AS in OST to close underweight gap (current 55%, target 63%)",
        "priority": 2
      }
    ],
    "summary": {
      "currentWeights": {"IWDA.AS": 0.55, "NOKIA.HE": 0.15, "SAMPO.HE": 0.08, "VGEA.DE": 0.15, "BTC": 0.07},
      "targetWeights": {"IWDA.AS": 0.63, "NOKIA.HE": 0.07, "SAMPO.HE": 0.05, "VGEA.DE": 0.20, "BTC": 0.05},
      "postTradeWeights": {"IWDA.AS": 0.63, "NOKIA.HE": 0.07, "SAMPO.HE": 0.05, "VGEA.DE": 0.20, "BTC": 0.05},
      "totalBuyCents": 2600000,
      "totalSellCents": 2600000,
      "totalEstimatedTaxCents": 18000,
      "netCashRequiredCents": 0,
      "optimizationMethod": "markowitz"
    }
  },
  "meta": {
    "calculatedAt": "2026-03-21T14:30:00Z",
    "riskTolerance": 5,
    "computeTimeMs": 1890
  }
}
```

### 7.5 Risk Parity

```
GET /api/v1/optimization/risk-parity
```

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `lookbackDays` | int | 252 | Historical window |

**Response:**

```json
{
  "data": {
    "weights": {
      "IWDA.AS": 0.28,
      "NOKIA.HE": 0.10,
      "SAMPO.HE": 0.13,
      "VGEA.DE": 0.42,
      "BTC": 0.07
    },
    "riskContributions": {
      "IWDA.AS": 0.200,
      "NOKIA.HE": 0.200,
      "SAMPO.HE": 0.200,
      "VGEA.DE": 0.200,
      "BTC": 0.200
    },
    "portfolioVolatility": 0.082,
    "expectedReturn": 0.061,
    "sharpeRatio": 0.32,
    "comparisonToMarkowitz": {
      "volatilityDelta": -0.046,
      "returnDelta": -0.031,
      "sharpeDelta": -0.13
    }
  },
  "meta": {
    "calculatedAt": "2026-03-21T14:30:00Z",
    "lookbackDays": 252,
    "computeTimeMs": 320
  }
}
```

---

## 8. Performance Considerations

| Concern | Mitigation |
|---------|-----------|
| Covariance estimation for 50+ assets | Ledoit-Wolf shrinkage is O(n^2 * T); for n=50, T=252, this is ~630K operations — trivial |
| Efficient frontier (50 SLSQP solves) | Each SLSQP solve takes ~10-50ms for n=50. 50 points = 0.5-2.5s. Reduce to 25 points if n > 30 |
| Black-Litterman matrix inversion | O(n^3) for n x n matrix. For n=50, this is ~125K operations — trivial |
| Risk parity convergence | SLSQP typically converges in 50-200 iterations for ERC. Budget 500ms |
| Total endpoint budget | Target <5s per request. Cache covariance matrix (recompute daily). Frontier + optimal + rebalance can share the cached covariance |
| Large portfolios (>100 holdings) | Group similar holdings (e.g., all Finnish stocks as one "Finnish equities" block) to reduce dimensionality before optimization. Expand weights back to individual holdings proportionally |

**Caching strategy:**
- Covariance matrix: recomputed daily after market close, cached in Redis with key `optimization:cov:{lookback_days}:{date}`. TTL: until next market close.
- Equilibrium returns: cached alongside covariance matrix.
- Frontier results: cached per (lookback, n_points, date). TTL: same as covariance.
- Black-Litterman: NOT cached (views are user-specific and change per request).
- Rebalance: NOT cached (depends on current holdings which may change intraday).

---

## Edge Cases

1. **Fewer than 2 assets**: Optimization is degenerate. Return the single asset with weight 1.0. Efficient frontier collapses to a point. Skip Black-Litterman.

2. **Singular covariance matrix**: Can occur when two assets are perfectly correlated or when n_assets > n_observations. Ledoit-Wolf shrinkage mitigates this; if the matrix is still singular after shrinkage, remove the redundant asset and log a warning.

3. **No feasible solution**: The combination of glidepath bounds, position limits, and long-only constraints may be infeasible (e.g., if all assets are in one class and the bounds require multiple classes). Return an error with `reason: "infeasible_constraints"` and relax the glidepath tolerance to +/-10% before retrying.

4. **Negative expected returns for all assets**: The optimizer will allocate to the least-negative return. The efficient frontier will have negative returns throughout. The tangent portfolio may not exist (no positive Sharpe). Return the minimum-variance portfolio as the "optimal" and flag `tangentPortfolio: null`.

5. **Crypto with insufficient history**: Crypto assets with <252 days of history are excluded from the covariance estimation. Their current weight is subtracted from the total, and the optimizer runs on the remaining assets. The crypto allocation is fixed at its current weight (or glidepath target if closer).

6. **OST deposit limit reached**: If `ost_deposit_remaining_cents = 0`, all equity buys are routed to the regular account. The rebalancing engine must track cumulative OST deposits to avoid exceeding the 50,000 EUR lifetime cap.

7. **All holdings in one account**: Optimization still works but rebalancing cannot use tax-free OST sells. All sells generate tax events. The engine should note this limitation in the `rationale` field.

8. **Black-Litterman with contradictory views**: Two views that oppose each other (e.g., "NOKIA up 20%" and "NOKIA down 10%") are both applied — the posterior will be a confidence-weighted blend. The system does not reject contradictory views but does flag them as `contradiction_detected` in the response.

9. **Zero cash and all positions overweight in one class**: The rebalancing engine must sell overweight positions before it can buy underweight ones. If selling triggers significant tax, it may be better to defer rebalancing. Report the `totalEstimatedTaxCents` and let the user decide.

10. **Risk parity with extreme volatility dispersion**: When one asset has 10x the volatility of another (e.g., BTC vs bonds), risk parity assigns very small weight to the volatile asset and very large weight to the stable one. If this violates glidepath bounds, apply the bounds as post-hoc constraints and note that the result is "constrained risk parity" (not pure ERC).

11. **Corporate actions between optimization and execution**: If a stock split or dividend occurs between the optimization run and trade execution, quantities may be stale. The rebalancing endpoint returns `estimatedQuantity` — actual quantities must be recalculated at execution time using the latest price.

12. **Stale price data**: If any security's price is more than 5 trading days old (per [portfolio-math.md](../03-calculations/portfolio-math.md) Section 1.5), exclude it from optimization and flag it in the response as `staleSecurities: ["TICKER"]`.

---

## Open Questions

1. **Should the optimizer support leverage?** The current spec is long-only (no shorting, no leverage). Risk parity in its pure form sometimes implies leverage to equalize risk contributions. Should we allow a "levered risk parity" mode, or always constrain to sum-to-1?

2. **Robust optimization**: Should we implement worst-case or distributionally robust optimization to guard against estimation error in expected returns? This would add computational cost but reduce sensitivity to return estimates.

3. **Transaction cost modeling**: The current rebalancing uses a flat minimum trade size. Should we model actual Nordnet commissions (percentage-based, tiered) and incorporate them into the optimization objective?

4. **Multi-period optimization**: The current spec is single-period. Should we implement a multi-period model that considers the glidepath trajectory over the next 1-5 years and optimizes a sequence of rebalancing actions?

5. **Rebalancing frequency**: Should the system recommend a rebalancing schedule (e.g., quarterly) or remain purely drift-triggered per the glidepath spec?

6. **Market-cap weights source**: The Black-Litterman model requires market-cap weights. Should these come from ETF holdings data (e.g., IWDA.AS holdings), an external API, or be user-configurable?

---

## Changelog

| Date | Change |
|------|--------|
| 2026-03-21 | Initial draft |
