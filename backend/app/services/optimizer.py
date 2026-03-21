"""Portfolio optimization — Markowitz, Black-Litterman, risk parity, rebalancing.

All optimization runs server-side using scipy.optimize and numpy.
Computation budget: <5 seconds per endpoint.
"""

from dataclasses import dataclass, field

import numpy as np
from scipy import optimize

import structlog

logger = structlog.get_logger()

TRADING_DAYS_PER_YEAR = 252

# Risk aversion mapping: user-friendly 1-10 scale to lambda
LAMBDA_MAP = {
    1: 0.5,
    2: 1.0,
    3: 1.5,
    4: 2.0,
    5: 3.0,
    6: 4.0,
    7: 6.0,
    8: 8.0,
    9: 12.0,
    10: 15.0,
}

# Glidepath targets by age
GLIDEPATH = {
    45: {"equity": 0.75, "fixed_income": 0.15, "crypto": 0.07, "cash": 0.03},
    50: {"equity": 0.65, "fixed_income": 0.22, "crypto": 0.06, "cash": 0.07},
    55: {"equity": 0.50, "fixed_income": 0.38, "crypto": 0.04, "cash": 0.08},
    60: {"equity": 0.30, "fixed_income": 0.60, "crypto": 0.02, "cash": 0.08},
}

# Glidepath tolerance band
GLIDEPATH_TOLERANCE = 0.05

# Map asset_class to glidepath categories
ASSET_CLASS_MAP = {
    "stock": "equity",
    "etf": "equity",  # Default; refined by sector for fixed income ETFs
    "bond": "fixed_income",
    "crypto": "crypto",
}

# Position limits
MAX_SINGLE_STOCK_PCT = 0.10
MAX_SECTOR_ETF_PCT = 0.20
MAX_SINGLE_CRYPTO_PCT = 0.05
MIN_POSITION_PCT = 0.01

# Rebalancing thresholds (EUR cents)
MIN_TRADE_CENTS = 50_000  # 500 EUR
MIN_TOTAL_REBALANCE_CENTS = 100_000  # 1,000 EUR
MIN_DRIFT_CENTS = 5_000  # 50 EUR

# Finnish capital gains tax rates
TAX_RATE_STANDARD = 0.30
TAX_RATE_HIGH = 0.34
TAX_HIGH_THRESHOLD_CENTS = 3_000_000  # 30,000 EUR


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class EfficientFrontierPoint:
    expected_return: float
    volatility: float
    sharpe_ratio: float
    weights: np.ndarray


@dataclass
class EfficientFrontierResult:
    points: list[EfficientFrontierPoint]
    tangent_portfolio: EfficientFrontierPoint
    min_variance_portfolio: EfficientFrontierPoint
    asset_labels: list[str]


@dataclass
class OptimalPortfolioResult:
    weights: dict[str, float]
    expected_return: float
    volatility: float
    sharpe_ratio: float
    risk_tolerance: int
    lambda_value: float
    glidepath_compliant: bool
    constraint_violations: list[str] = field(default_factory=list)


@dataclass
class BlackLittermanResult:
    posterior_returns: dict[str, float]
    prior_returns: dict[str, float]
    posterior_cov: np.ndarray
    views_applied: list[dict]
    views_rejected: list[dict]


@dataclass
class RiskParityResult:
    weights: dict[str, float]
    risk_contributions: dict[str, float]
    portfolio_volatility: float
    expected_return: float


@dataclass
class TradeRecommendation:
    action: str
    ticker: str
    security_id: int
    account_id: int | None
    account_type: str | None
    amount_eur_cents: int
    estimated_tax_cents: int
    rationale: str
    priority: int


@dataclass
class RebalanceResult:
    trades: list[TradeRecommendation]
    current_weights: dict[str, float]
    target_weights: dict[str, float]
    post_trade_weights: dict[str, float]
    total_buy_cents: int
    total_sell_cents: int
    total_estimated_tax_cents: int
    net_cash_required_cents: int
    optimization_method: str


# ---------------------------------------------------------------------------
# 1. Covariance and Expected Returns Estimation
# ---------------------------------------------------------------------------


def ledoit_wolf_shrinkage(returns: np.ndarray) -> np.ndarray:
    """Ledoit-Wolf shrinkage covariance estimator.

    Args:
        returns: daily log returns, shape (n_days, n_assets).

    Returns:
        Annualized covariance matrix, shape (n_assets, n_assets).
    """
    n_days, n_assets = returns.shape

    if n_days < 2 or n_assets < 1:
        raise ValueError(
            f"Insufficient data: {n_days} days, {n_assets} assets. "
            "Need at least 2 days and 1 asset."
        )

    # Sample covariance
    sample_cov = np.cov(returns, rowvar=False, ddof=1)
    if n_assets == 1:
        return sample_cov * TRADING_DAYS_PER_YEAR

    # Structured target: constant-correlation model
    std_devs = np.sqrt(np.diag(sample_cov))
    corr_matrix = sample_cov / np.outer(std_devs, std_devs)
    np.fill_diagonal(corr_matrix, 1.0)

    # Average off-diagonal correlation
    mask = ~np.eye(n_assets, dtype=bool)
    rho_bar = np.mean(corr_matrix[mask])

    # Constant-correlation target
    target = np.full((n_assets, n_assets), rho_bar)
    np.fill_diagonal(target, 1.0)
    target = target * np.outer(std_devs, std_devs)

    # Shrinkage intensity (Ledoit-Wolf analytical formula)
    # Demean returns
    X = returns - returns.mean(axis=0)

    # Compute pi_hat (sum of asymptotic variances of sample covariance entries)
    pi_hat = 0.0
    for t in range(n_days):
        x_t = X[t, :].reshape(-1, 1)
        m_t = x_t @ x_t.T - sample_cov
        pi_hat += np.sum(m_t ** 2)
    pi_hat /= n_days ** 2

    # Compute gamma_hat (misspecification of target)
    gamma_hat = np.sum((target - sample_cov) ** 2)

    # Optimal shrinkage intensity
    kappa = (pi_hat - gamma_hat) / gamma_hat if gamma_hat > 1e-14 else 1.0
    alpha = max(0.0, min(1.0, kappa / n_days))

    logger.debug(
        "ledoit_wolf_shrinkage",
        n_days=n_days,
        n_assets=n_assets,
        shrinkage_intensity=round(alpha, 4),
        avg_correlation=round(rho_bar, 4),
    )

    shrunk_cov = alpha * target + (1 - alpha) * sample_cov

    # Ensure symmetry and positive semi-definiteness
    shrunk_cov = (shrunk_cov + shrunk_cov.T) / 2

    return shrunk_cov * TRADING_DAYS_PER_YEAR


def expected_returns_historical(daily_returns: np.ndarray) -> np.ndarray:
    """Annualized expected returns from historical mean of daily log returns.

    Args:
        daily_returns: shape (n_days, n_assets).

    Returns:
        Expected returns vector, shape (n_assets,).
    """
    return np.mean(daily_returns, axis=0) * TRADING_DAYS_PER_YEAR


def equilibrium_returns(
    cov_matrix: np.ndarray,
    market_cap_weights: np.ndarray,
    risk_aversion: float = 2.5,
) -> np.ndarray:
    """Implied equilibrium returns (Black-Litterman prior).

    pi = delta * Sigma * w_mkt
    """
    return risk_aversion * cov_matrix @ market_cap_weights


# ---------------------------------------------------------------------------
# 2. Efficient Frontier
# ---------------------------------------------------------------------------


def _build_constraints(
    n: int,
    class_membership: dict[str, list[int]],
    class_lower_bounds: dict[str, float],
    class_upper_bounds: dict[str, float],
) -> list[dict]:
    """Build scipy constraints: sum-to-one + asset class bounds."""
    constraints = [
        {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
    ]
    for cls_name, indices in class_membership.items():
        lb = class_lower_bounds.get(cls_name, 0.0)
        ub = class_upper_bounds.get(cls_name, 1.0)
        constraints.append(
            {"type": "ineq", "fun": lambda w, idx=indices, lb=lb: np.sum(w[idx]) - lb}
        )
        constraints.append(
            {"type": "ineq", "fun": lambda w, idx=indices, ub=ub: ub - np.sum(w[idx])}
        )
    return constraints


def _initial_weights(n: int, bounds: list[tuple[float, float]]) -> np.ndarray:
    """Generate a feasible initial weight vector."""
    w0 = np.full(n, 1.0 / n)
    w0 = np.clip(w0, [b[0] for b in bounds], [b[1] for b in bounds])
    total = w0.sum()
    if total > 0:
        w0 /= total
    return w0


def compute_efficient_frontier(
    mu: np.ndarray,
    cov: np.ndarray,
    risk_free_rate: float,
    position_upper_bounds: np.ndarray,
    class_membership: dict[str, list[int]],
    class_lower_bounds: dict[str, float],
    class_upper_bounds: dict[str, float],
    n_points: int = 20,
) -> EfficientFrontierResult:
    """Compute the constrained efficient frontier.

    Returns n_points along the frontier plus tangent and min-variance portfolios.
    Uses scipy.optimize.minimize with SLSQP.
    """
    n = len(mu)
    if n == 0:
        raise ValueError("No assets provided for optimization.")

    # Validate covariance matrix
    if cov.shape != (n, n):
        raise ValueError(f"Covariance shape {cov.shape} does not match {n} assets.")

    # Check for singular covariance — add small ridge if needed
    try:
        eigvals = np.linalg.eigvalsh(cov)
        if np.min(eigvals) < 1e-10:
            logger.warning(
                "near_singular_covariance",
                min_eigenvalue=float(np.min(eigvals)),
                adding_ridge=True,
            )
            cov = cov + np.eye(n) * 1e-8
    except np.linalg.LinAlgError:
        logger.error("covariance_eigenvalue_check_failed")
        cov = cov + np.eye(n) * 1e-6

    constraints = _build_constraints(
        n, class_membership, class_lower_bounds, class_upper_bounds
    )
    bounds = [(0.0, float(ub)) for ub in position_upper_bounds]
    w0 = _initial_weights(n, bounds)
    opt_kwargs = {"method": "SLSQP", "options": {"maxiter": 1000, "ftol": 1e-12}}

    def portfolio_variance(w):
        return float(w @ cov @ w)

    def portfolio_return(w):
        return float(w @ mu)

    # Step 1: Minimum variance portfolio
    result_min_var = optimize.minimize(
        portfolio_variance, w0, bounds=bounds, constraints=constraints, **opt_kwargs
    )
    if not result_min_var.success:
        logger.warning("min_variance_optimization_failed", message=result_min_var.message)
    min_var_w = result_min_var.x
    min_var_ret = portfolio_return(min_var_w)

    # Step 2: Maximum return portfolio
    result_max_ret = optimize.minimize(
        lambda w: -portfolio_return(w),
        w0,
        bounds=bounds,
        constraints=constraints,
        **opt_kwargs,
    )
    max_ret = portfolio_return(result_max_ret.x)

    # Step 3: Trace frontier
    if max_ret <= min_var_ret:
        max_ret = min_var_ret + 0.01  # Prevent degenerate case

    target_returns = np.linspace(min_var_ret, max_ret, n_points)
    points: list[EfficientFrontierPoint] = []

    for target_ret in target_returns:
        ret_constraint = {
            "type": "eq",
            "fun": lambda w, t=target_ret: portfolio_return(w) - t,
        }
        all_constraints = constraints + [ret_constraint]

        result = optimize.minimize(
            portfolio_variance,
            w0,
            bounds=bounds,
            constraints=all_constraints,
            **opt_kwargs,
        )

        if result.success:
            w = result.x
            vol = float(np.sqrt(w @ cov @ w))
            ret = float(w @ mu)
            sharpe = (ret - risk_free_rate) / vol if vol > 1e-10 else 0.0
            points.append(
                EfficientFrontierPoint(
                    expected_return=ret,
                    volatility=vol,
                    sharpe_ratio=sharpe,
                    weights=w,
                )
            )

    if not points:
        raise ValueError("Efficient frontier computation failed — no feasible points found.")

    # Step 4: Tangent portfolio (max Sharpe)
    def neg_sharpe(w):
        ret = float(w @ mu)
        vol = float(np.sqrt(w @ cov @ w))
        if vol < 1e-10:
            return 0.0
        return -(ret - risk_free_rate) / vol

    result_tangent = optimize.minimize(
        neg_sharpe, w0, bounds=bounds, constraints=constraints, **opt_kwargs
    )
    tangent_w = result_tangent.x
    tangent_vol = float(np.sqrt(tangent_w @ cov @ tangent_w))
    tangent_ret = float(tangent_w @ mu)
    tangent_sharpe = (
        (tangent_ret - risk_free_rate) / tangent_vol if tangent_vol > 1e-10 else 0.0
    )

    tangent = EfficientFrontierPoint(
        expected_return=tangent_ret,
        volatility=tangent_vol,
        sharpe_ratio=tangent_sharpe,
        weights=tangent_w,
    )

    # Min variance point
    mv_vol = float(np.sqrt(min_var_w @ cov @ min_var_w))
    mv_sharpe = (min_var_ret - risk_free_rate) / mv_vol if mv_vol > 1e-10 else 0.0
    min_var = EfficientFrontierPoint(
        expected_return=min_var_ret,
        volatility=mv_vol,
        sharpe_ratio=mv_sharpe,
        weights=min_var_w,
    )

    logger.info(
        "efficient_frontier_computed",
        n_points=len(points),
        tangent_sharpe=round(tangent_sharpe, 4),
        min_var_vol=round(mv_vol, 4),
    )

    return EfficientFrontierResult(
        points=points,
        tangent_portfolio=tangent,
        min_variance_portfolio=min_var,
        asset_labels=[],
    )


# ---------------------------------------------------------------------------
# 3. Optimal Portfolio for Risk Tolerance
# ---------------------------------------------------------------------------


def find_optimal_portfolio(
    mu: np.ndarray,
    cov: np.ndarray,
    risk_free_rate: float,
    risk_tolerance: int,
    position_upper_bounds: np.ndarray,
    class_membership: dict[str, list[int]],
    class_lower_bounds: dict[str, float],
    class_upper_bounds: dict[str, float],
    tickers: list[str],
) -> OptimalPortfolioResult:
    """Find the optimal portfolio for a given risk tolerance (1-10 scale).

    Maximizes: w'mu - (lambda/2) * w'Sigma*w
    """
    n = len(mu)
    if risk_tolerance not in LAMBDA_MAP:
        risk_tolerance = max(1, min(10, risk_tolerance))
    lam = LAMBDA_MAP[risk_tolerance]

    # Add ridge for near-singular covariance
    try:
        eigvals = np.linalg.eigvalsh(cov)
        if np.min(eigvals) < 1e-10:
            cov = cov + np.eye(n) * 1e-8
    except np.linalg.LinAlgError:
        cov = cov + np.eye(n) * 1e-6

    def neg_utility(w):
        ret = float(w @ mu)
        var = float(w @ cov @ w)
        return -(ret - (lam / 2) * var)

    constraints = _build_constraints(
        n, class_membership, class_lower_bounds, class_upper_bounds
    )
    bounds = [(0.0, float(ub)) for ub in position_upper_bounds]
    w0 = _initial_weights(n, bounds)

    result = optimize.minimize(
        neg_utility,
        w0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 1000, "ftol": 1e-12},
    )

    w = result.x
    ret = float(w @ mu)
    vol = float(np.sqrt(w @ cov @ w))
    sharpe = (ret - risk_free_rate) / vol if vol > 1e-10 else 0.0

    # Check constraint violations
    violations: list[str] = []
    if not result.success:
        violations.append(f"Optimizer did not converge: {result.message}")

    for cls_name, indices in class_membership.items():
        cls_weight = float(np.sum(w[indices]))
        lb = class_lower_bounds.get(cls_name, 0.0)
        ub = class_upper_bounds.get(cls_name, 1.0)
        if cls_weight < lb - 0.001:
            violations.append(f"{cls_name} weight {cls_weight:.1%} below lower bound {lb:.1%}")
        if cls_weight > ub + 0.001:
            violations.append(f"{cls_name} weight {cls_weight:.1%} above upper bound {ub:.1%}")

    # Filter out near-zero weights below minimum position
    weights_dict: dict[str, float] = {}
    for i in range(n):
        weight = float(w[i])
        if weight >= MIN_POSITION_PCT:
            weights_dict[tickers[i]] = weight
        else:
            weights_dict[tickers[i]] = 0.0

    # Renormalize if we zeroed out small positions
    total_w = sum(weights_dict.values())
    if total_w > 0 and abs(total_w - 1.0) > 0.001:
        for t in weights_dict:
            if weights_dict[t] > 0:
                weights_dict[t] /= total_w

    logger.info(
        "optimal_portfolio_computed",
        risk_tolerance=risk_tolerance,
        lambda_value=lam,
        expected_return=round(ret, 4),
        volatility=round(vol, 4),
        sharpe=round(sharpe, 4),
        converged=result.success,
    )

    return OptimalPortfolioResult(
        weights=weights_dict,
        expected_return=ret,
        volatility=vol,
        sharpe_ratio=sharpe,
        risk_tolerance=risk_tolerance,
        lambda_value=lam,
        glidepath_compliant=len(violations) == 0,
        constraint_violations=violations,
    )


# ---------------------------------------------------------------------------
# 4. Black-Litterman
# ---------------------------------------------------------------------------


def black_litterman(
    market_caps: np.ndarray,
    cov: np.ndarray,
    views: list[dict],
    tickers: list[str],
    risk_aversion: float = 2.5,
    tau: float = 0.05,
) -> BlackLittermanResult:
    """Compute Black-Litterman posterior expected returns.

    Args:
        market_caps: market capitalization values, shape (n,). Used to derive
            market-cap weights.
        cov: annualized covariance matrix, shape (n, n).
        views: list of dicts with keys:
            - security: ticker string
            - expectedReturn: annualized return (e.g. 0.15 for 15%)
            - confidence: 0.10 to 0.95
        tickers: list of ticker strings matching the column order of cov.
        risk_aversion: market risk aversion parameter (default 2.5).
        tau: scaling factor for prior uncertainty (default 0.05).

    Returns:
        BlackLittermanResult with posterior and prior returns.
    """
    n = len(tickers)
    ticker_idx = {t: i for i, t in enumerate(tickers)}

    # Market-cap weights
    total_cap = np.sum(market_caps)
    if total_cap <= 0:
        # Fallback to equal weights
        w_mkt = np.full(n, 1.0 / n)
    else:
        w_mkt = market_caps / total_cap

    # Prior: equilibrium returns
    pi = equilibrium_returns(cov, w_mkt, risk_aversion)

    # Build P matrix and Q vector from views
    valid_views: list[dict] = []
    rejected_views: list[dict] = []
    P_rows: list[np.ndarray] = []
    Q_values: list[float] = []
    omega_diag: list[float] = []

    for v in views:
        security = v.get("security", "")
        expected_ret = v.get("expectedReturn", 0.0)
        confidence = v.get("confidence", 0.5)

        # Validate confidence range
        if confidence < 0.10:
            rejected_views.append({**v, "reason": "confidence_too_low"})
            continue
        if confidence > 0.95:
            confidence = 0.95

        if security not in ticker_idx:
            rejected_views.append({**v, "reason": "asset_not_in_portfolio"})
            continue

        # Absolute view only (relative views would need asset_2)
        p = np.zeros(n)
        p[ticker_idx[security]] = 1.0

        P_rows.append(p)
        Q_values.append(expected_ret)

        # Confidence -> uncertainty
        omega_k = ((1 - confidence) / confidence) * float(p @ (tau * cov) @ p)
        omega_diag.append(max(omega_k, 1e-14))
        valid_views.append(v)

    prior_dict = {tickers[i]: float(pi[i]) for i in range(n)}

    if len(valid_views) == 0:
        logger.info("black_litterman_no_valid_views", rejected=len(rejected_views))
        return BlackLittermanResult(
            posterior_returns=prior_dict,
            prior_returns=prior_dict,
            posterior_cov=cov,
            views_applied=[],
            views_rejected=rejected_views,
        )

    P = np.array(P_rows)
    Q = np.array(Q_values)
    Omega = np.diag(omega_diag)

    # Posterior returns: mu_BL = inv(inv(tau*Sigma) + P'*inv(Omega)*P) * (inv(tau*Sigma)*pi + P'*inv(Omega)*Q)
    tau_sigma = tau * cov

    try:
        tau_sigma_inv = np.linalg.inv(tau_sigma)
        Omega_inv = np.linalg.inv(Omega)
    except np.linalg.LinAlgError:
        logger.error("black_litterman_matrix_inversion_failed")
        return BlackLittermanResult(
            posterior_returns=prior_dict,
            prior_returns=prior_dict,
            posterior_cov=cov,
            views_applied=[],
            views_rejected=rejected_views + [{"reason": "matrix_inversion_failed"}],
        )

    Pt_Omega_inv = P.T @ Omega_inv

    try:
        M = tau_sigma_inv + Pt_Omega_inv @ P
        M_inv = np.linalg.inv(M)
    except np.linalg.LinAlgError:
        logger.error("black_litterman_posterior_inversion_failed")
        return BlackLittermanResult(
            posterior_returns=prior_dict,
            prior_returns=prior_dict,
            posterior_cov=cov,
            views_applied=[],
            views_rejected=rejected_views + [{"reason": "posterior_inversion_failed"}],
        )

    mu_bl = M_inv @ (tau_sigma_inv @ pi + Pt_Omega_inv @ Q)

    # Posterior covariance
    posterior_cov = cov + M_inv

    posterior_dict = {tickers[i]: float(mu_bl[i]) for i in range(n)}

    logger.info(
        "black_litterman_computed",
        n_views_applied=len(valid_views),
        n_views_rejected=len(rejected_views),
    )

    return BlackLittermanResult(
        posterior_returns=posterior_dict,
        prior_returns=prior_dict,
        posterior_cov=posterior_cov,
        views_applied=valid_views,
        views_rejected=rejected_views,
    )


# ---------------------------------------------------------------------------
# 5. Risk Parity (Equal Risk Contribution)
# ---------------------------------------------------------------------------


def equal_risk_contribution(
    cov: np.ndarray,
    mu: np.ndarray | None = None,
    tickers: list[str] | None = None,
) -> RiskParityResult:
    """Compute the Equal Risk Contribution (ERC) portfolio.

    Each asset contributes equally to total portfolio risk.

    Args:
        cov: annualized covariance matrix, shape (n, n).
        mu: expected returns vector (optional, used for informational return calc).
        tickers: list of ticker labels.

    Returns:
        RiskParityResult with weights and risk contributions.
    """
    n = cov.shape[0]
    if tickers is None:
        tickers = [f"asset_{i}" for i in range(n)]
    if mu is None:
        mu = np.zeros(n)

    target_risk_budgets = np.full(n, 1.0 / n)

    def objective(w):
        sigma_p = float(np.sqrt(w @ cov @ w))
        if sigma_p < 1e-10:
            return 0.0
        mrc = (cov @ w) / sigma_p
        rc = w * mrc
        target_rc = target_risk_budgets * sigma_p
        return float(np.sum((rc - target_rc) ** 2))

    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
    # Small floor to avoid degenerate zero weights
    bounds = [(0.001, 1.0) for _ in range(n)]
    w0 = np.full(n, 1.0 / n)

    result = optimize.minimize(
        objective,
        w0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 1000, "ftol": 1e-14},
    )

    if not result.success:
        logger.warning("risk_parity_optimization_warning", message=result.message)

    w = result.x
    sigma_p = float(np.sqrt(w @ cov @ w))

    # Compute risk contributions
    if sigma_p > 1e-10:
        mrc = (cov @ w) / sigma_p
        rc = w * mrc
        rc_pct = rc / sigma_p
    else:
        rc_pct = np.full(n, 1.0 / n)

    exp_ret = float(w @ mu)

    logger.info(
        "risk_parity_computed",
        portfolio_volatility=round(sigma_p, 4),
        expected_return=round(exp_ret, 4),
        max_weight=round(float(np.max(w)), 4),
        min_weight=round(float(np.min(w)), 4),
    )

    return RiskParityResult(
        weights={tickers[i]: float(w[i]) for i in range(n)},
        risk_contributions={tickers[i]: float(rc_pct[i]) for i in range(n)},
        portfolio_volatility=sigma_p,
        expected_return=exp_ret,
    )


# ---------------------------------------------------------------------------
# 6. Rebalancing Recommendations
# ---------------------------------------------------------------------------


def generate_rebalance_trades(
    current_holdings: list[dict],
    optimal_weights: dict[str, float],
    total_portfolio_cents: int,
    available_cash_cents: int = 0,
    min_trade_cents: int = MIN_TRADE_CENTS,
) -> RebalanceResult:
    """Generate tax-aware rebalancing trade recommendations.

    Args:
        current_holdings: list of dicts with keys:
            ticker, securityId, accountId, accountType, marketValueEurCents,
            costBasisEurCents, unrealizedPnlCents, assetClass
        optimal_weights: {ticker: target_weight}
        total_portfolio_cents: total portfolio value in EUR cents.
        available_cash_cents: available cash for purchases.
        min_trade_cents: minimum trade size in EUR cents (default 500 EUR).

    Returns:
        RebalanceResult with trade recommendations.
    """
    if total_portfolio_cents <= 0:
        return RebalanceResult(
            trades=[],
            current_weights={},
            target_weights=optimal_weights,
            post_trade_weights={},
            total_buy_cents=0,
            total_sell_cents=0,
            total_estimated_tax_cents=0,
            net_cash_required_cents=0,
            optimization_method="markowitz",
        )

    # Aggregate current holdings by ticker
    current_by_ticker: dict[str, dict] = {}
    for h in current_holdings:
        ticker = h.get("ticker", "")
        if ticker not in current_by_ticker:
            current_by_ticker[ticker] = {
                "ticker": ticker,
                "securityId": h.get("securityId", 0),
                "totalValueCents": 0,
                "totalCostCents": 0,
                "accounts": [],
            }
        val = h.get("marketValueEurCents") or 0
        cost = h.get("costBasisEurCents") or 0
        current_by_ticker[ticker]["totalValueCents"] += val
        current_by_ticker[ticker]["totalCostCents"] += cost
        current_by_ticker[ticker]["accounts"].append({
            "accountId": h.get("accountId"),
            "accountType": h.get("accountType"),
            "valueCents": val,
            "costCents": cost,
            "pnlCents": h.get("unrealizedPnlCents") or 0,
        })

    # Current weights
    current_weights: dict[str, float] = {}
    for ticker, data in current_by_ticker.items():
        current_weights[ticker] = data["totalValueCents"] / total_portfolio_cents

    # Compute deltas
    all_tickers = set(list(optimal_weights.keys()) + list(current_weights.keys()))
    deltas: dict[str, int] = {}

    for ticker in all_tickers:
        target_value = int(optimal_weights.get(ticker, 0.0) * total_portfolio_cents)
        current_value = current_by_ticker.get(ticker, {}).get("totalValueCents", 0)
        delta = target_value - current_value
        if abs(delta) >= min_trade_cents:
            deltas[ticker] = delta

    # Check total rebalancing is worthwhile
    total_abs_delta = sum(abs(d) for d in deltas.values())
    if total_abs_delta < MIN_TOTAL_REBALANCE_CENTS:
        logger.info(
            "rebalance_deferred",
            total_delta_cents=total_abs_delta,
            threshold_cents=MIN_TOTAL_REBALANCE_CENTS,
        )
        return RebalanceResult(
            trades=[],
            current_weights=current_weights,
            target_weights=optimal_weights,
            post_trade_weights=current_weights,
            total_buy_cents=0,
            total_sell_cents=0,
            total_estimated_tax_cents=0,
            net_cash_required_cents=0,
            optimization_method="markowitz",
        )

    trades: list[TradeRecommendation] = []
    priority = 1

    # Step 1: Generate sell trades for overweight positions
    # Sort sells by tax efficiency: osakesaastotili first, then losses, then smallest gains
    sell_tickers = sorted(
        [t for t in deltas if deltas[t] < 0],
        key=lambda t: _sell_priority(t, current_by_ticker),
    )

    total_sell_proceeds = 0
    for ticker in sell_tickers:
        sell_amount = abs(deltas[ticker])
        data = current_by_ticker.get(ticker, {})
        accounts = data.get("accounts", [])

        # Sort accounts: OST first (tax-free sells), then losses, then low gains
        sorted_accounts = sorted(accounts, key=lambda a: _account_sell_priority(a))

        remaining = sell_amount
        for acct in sorted_accounts:
            if remaining < min_trade_cents:
                break
            lot_sell = min(acct["valueCents"], remaining)
            if lot_sell < min_trade_cents:
                continue

            # Estimate tax impact
            tax_cents = _estimate_tax(acct, lot_sell)

            trades.append(TradeRecommendation(
                action="sell",
                ticker=ticker,
                security_id=data.get("securityId", 0),
                account_id=acct["accountId"],
                account_type=acct["accountType"],
                amount_eur_cents=lot_sell,
                estimated_tax_cents=tax_cents,
                rationale=_sell_rationale(ticker, acct),
                priority=priority,
            ))
            remaining -= lot_sell
            total_sell_proceeds += lot_sell
            priority += 1

    # Step 2: Generate buy trades for underweight positions
    # Buy with available cash + sell proceeds
    buy_budget = available_cash_cents + total_sell_proceeds
    buy_tickers = sorted(
        [t for t in deltas if deltas[t] > 0],
        key=lambda t: -deltas[t],  # Largest underweight first
    )

    total_buy = 0
    for ticker in buy_tickers:
        buy_amount = min(deltas[ticker], buy_budget)
        if buy_amount < min_trade_cents:
            continue

        # Determine account for buy
        data = current_by_ticker.get(ticker, {})
        account_id = None
        account_type = None
        if data and data.get("accounts"):
            # Use same account type as existing holding
            acct = data["accounts"][0]
            account_id = acct["accountId"]
            account_type = acct["accountType"]

        trades.append(TradeRecommendation(
            action="buy",
            ticker=ticker,
            security_id=data.get("securityId", 0) if data else 0,
            account_id=account_id,
            account_type=account_type,
            amount_eur_cents=buy_amount,
            estimated_tax_cents=0,
            rationale=f"Rebalance: buy {ticker} to close underweight gap",
            priority=priority,
        ))
        buy_budget -= buy_amount
        total_buy += buy_amount
        priority += 1

    # Compute post-trade projected weights
    post_trade_weights: dict[str, float] = {}
    for ticker in all_tickers:
        current_val = current_by_ticker.get(ticker, {}).get("totalValueCents", 0)
        buys = sum(
            t.amount_eur_cents for t in trades
            if t.ticker == ticker and t.action == "buy"
        )
        sells = sum(
            t.amount_eur_cents for t in trades
            if t.ticker == ticker and t.action == "sell"
        )
        projected = current_val + buys - sells
        if total_portfolio_cents > 0:
            post_trade_weights[ticker] = projected / total_portfolio_cents

    total_est_tax = sum(t.estimated_tax_cents for t in trades)
    total_sell = sum(t.amount_eur_cents for t in trades if t.action == "sell")
    total_buy_actual = sum(t.amount_eur_cents for t in trades if t.action == "buy")
    net_cash = max(0, total_buy_actual - total_sell - available_cash_cents)

    logger.info(
        "rebalance_trades_generated",
        n_trades=len(trades),
        total_buy_cents=total_buy_actual,
        total_sell_cents=total_sell,
        estimated_tax_cents=total_est_tax,
        net_cash_required_cents=net_cash,
    )

    return RebalanceResult(
        trades=trades,
        current_weights=current_weights,
        target_weights=optimal_weights,
        post_trade_weights=post_trade_weights,
        total_buy_cents=total_buy_actual,
        total_sell_cents=total_sell,
        total_estimated_tax_cents=total_est_tax,
        net_cash_required_cents=net_cash,
        optimization_method="markowitz",
    )


def _sell_priority(ticker: str, current_by_ticker: dict) -> tuple:
    """Lower value = sell first. Prefer tax-free and loss positions."""
    data = current_by_ticker.get(ticker, {})
    accounts = data.get("accounts", [])
    has_ost = any(a.get("accountType") == "osakesaastotili" for a in accounts)
    total_pnl = sum(a.get("pnlCents", 0) for a in accounts)
    return (0 if has_ost else 1, 0 if total_pnl < 0 else 1, total_pnl)


def _account_sell_priority(acct: dict) -> tuple:
    """Lower = sell first. OST first, then losses, then smallest gains."""
    is_ost = 0 if acct.get("accountType") == "osakesaastotili" else 1
    pnl = acct.get("pnlCents", 0)
    is_loss = 0 if pnl < 0 else 1
    return (is_ost, is_loss, pnl)


def _estimate_tax(acct: dict, sell_amount_cents: int) -> int:
    """Estimate capital gains tax for a sell.

    OST sells are tax-free. Regular account sells use Finnish rates.
    """
    if acct.get("accountType") == "osakesaastotili":
        return 0

    value = acct.get("valueCents", 0)
    cost = acct.get("costCents", 0)
    if value <= 0:
        return 0

    # Pro-rata gain for partial sell
    proportion = sell_amount_cents / value if value > 0 else 0
    gain = int((value - cost) * proportion)

    if gain <= 0:
        return 0  # Loss — no tax (may be deductible)

    # Finnish tax: 30% up to 30k, 34% above
    if gain <= TAX_HIGH_THRESHOLD_CENTS:
        return int(gain * TAX_RATE_STANDARD)
    else:
        tax = int(TAX_HIGH_THRESHOLD_CENTS * TAX_RATE_STANDARD)
        tax += int((gain - TAX_HIGH_THRESHOLD_CENTS) * TAX_RATE_HIGH)
        return tax


def _sell_rationale(ticker: str, acct: dict) -> str:
    """Generate human-readable rationale for a sell trade."""
    acct_type = acct.get("accountType", "regular")
    pnl = acct.get("pnlCents", 0)

    if acct_type == "osakesaastotili":
        return f"Tax-free rebalance: sell {ticker} in osakesaastotili"
    elif pnl < 0:
        return f"Tax-loss harvest: sell {ticker} (unrealized loss {pnl / 100:.0f} EUR)"
    else:
        return f"Rebalance: sell overweight {ticker} (gain {pnl / 100:.0f} EUR)"


# ---------------------------------------------------------------------------
# Helper: build position upper bounds and class membership from holdings
# ---------------------------------------------------------------------------


def build_optimization_inputs(
    holdings: list[dict],
    current_age: int = 45,
) -> dict:
    """Prepare optimization constraint inputs from holdings data.

    Returns dict with:
        - position_upper_bounds: np.ndarray
        - class_membership: dict[str, list[int]]
        - class_lower_bounds: dict[str, float]
        - class_upper_bounds: dict[str, float]
        - tickers: list[str]
        - security_ids: list[int]
    """
    tickers: list[str] = []
    security_ids: list[int] = []
    upper_bounds: list[float] = []
    class_indices: dict[str, list[int]] = {
        "equity": [],
        "fixed_income": [],
        "crypto": [],
        "cash": [],
    }

    seen_tickers: set[str] = set()

    for i, h in enumerate(holdings):
        ticker = h.get("ticker", f"unknown_{i}")
        if ticker in seen_tickers:
            continue
        seen_tickers.add(ticker)

        idx = len(tickers)
        tickers.append(ticker)
        security_ids.append(h.get("securityId", 0))

        asset_class = h.get("assetClass", "stock")
        sector = (h.get("sector") or "").lower()

        # Determine glidepath category
        if asset_class == "etf" and "fixed income" in sector:
            gp_class = "fixed_income"
        else:
            gp_class = ASSET_CLASS_MAP.get(asset_class, "equity")

        if gp_class in class_indices:
            class_indices[gp_class].append(idx)

        # Position upper bound
        if asset_class == "crypto":
            upper_bounds.append(MAX_SINGLE_CRYPTO_PCT)
        elif asset_class == "etf":
            # Broad ETF: no cap; sector ETF: 20%
            etf_category = h.get("etfCategory", "")
            if etf_category == "broad" or "index" in (h.get("name") or "").lower():
                upper_bounds.append(1.0)
            else:
                upper_bounds.append(MAX_SECTOR_ETF_PCT)
        elif asset_class in ("stock", "bond"):
            upper_bounds.append(MAX_SINGLE_STOCK_PCT)
        else:
            upper_bounds.append(MAX_SINGLE_STOCK_PCT)

    # Glidepath bounds with tolerance
    target = GLIDEPATH.get(current_age, GLIDEPATH[45])
    class_lower = {}
    class_upper = {}
    for cls_name in class_indices:
        tgt = target.get(cls_name, 0.0)
        class_lower[cls_name] = max(0.0, tgt - GLIDEPATH_TOLERANCE)
        class_upper[cls_name] = min(1.0, tgt + GLIDEPATH_TOLERANCE)

    # Remove empty classes from membership (avoids meaningless constraints)
    class_membership = {k: v for k, v in class_indices.items() if v}

    return {
        "position_upper_bounds": np.array(upper_bounds),
        "class_membership": class_membership,
        "class_lower_bounds": class_lower,
        "class_upper_bounds": class_upper,
        "tickers": tickers,
        "security_ids": security_ids,
    }
