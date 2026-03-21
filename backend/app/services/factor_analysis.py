"""Fama-French five-factor model analysis — regression, rolling exposure,
attribution, and Sharpe style analysis.

All computations are server-side using numpy and scipy.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional

import numpy as np
from scipy import optimize, stats as sp_stats
import structlog

logger = structlog.get_logger()

FACTOR_NAMES = ["mkt", "smb", "hml", "rmw", "cma"]

STYLE_NAMES = [
    "large_value",
    "large_growth",
    "small_value",
    "small_growth",
    "bonds",
    "cash",
]

# Expected factor profile for a Munger/Boglehead hybrid strategy
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

# US exchanges
US_EXCHANGES = {"NYSE", "NASDAQ", "AMEX", "BATS"}

# European exchanges
EU_EXCHANGES = {
    "XHEL", "XSTO", "XETR", "XAMS", "XLON", "XPAR",
    "XMIL", "XMAD", "XBRU", "XLIS", "XDUB",
}


class InsufficientDataError(Exception):
    """Raised when there are not enough observations for a regression."""


class OptimizationError(Exception):
    """Raised when constrained optimization fails to converge."""


@dataclass
class FactorRegressionResult:
    alpha: float  # Jensen's alpha (annualized)
    alpha_daily: float  # Daily alpha (raw intercept)
    alpha_t_stat: float
    alpha_p_value: float
    betas: dict[str, float]  # {"mkt": 1.05, "smb": -0.12, ...}
    beta_t_stats: dict[str, float]
    beta_p_values: dict[str, float]
    r_squared: float
    adj_r_squared: float
    residual_std: float
    n_observations: int
    start_date: Optional[date] = None
    end_date: Optional[date] = None


@dataclass
class RollingFactorPoint:
    window_end_date: date
    alpha: float
    betas: dict[str, float]
    r_squared: float


@dataclass
class FactorAttribution:
    total_excess_return: float
    alpha_contribution: float
    factor_contributions: dict[str, float]
    residual: float
    factor_pct_of_return: dict[str, float]


@dataclass
class StyleAnalysisResult:
    weights: dict[str, float]
    r_squared: float
    style_label: str
    n_observations: int


@dataclass
class FactorDriftAlert:
    factor: str
    factor_label: str
    current_beta: float
    expected_range: tuple[float, float]
    direction: str  # "above_expected", "below_expected", "sign_reversal"
    severity: str  # "info", "warning", "critical"
    message: str


def run_factor_regression(
    excess_returns: np.ndarray,
    factor_returns: np.ndarray,
    trading_days: int = 252,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> FactorRegressionResult:
    """Run OLS regression of excess returns on the five Fama-French factors.

    Parameters
    ----------
    excess_returns : shape (n,) — R_i - R_f
    factor_returns : shape (n, 5) — MKT, SMB, HML, RMW, CMA columns
    trading_days : annualization factor (252 for daily)
    start_date, end_date : date range for metadata

    Returns
    -------
    FactorRegressionResult with alpha (annualized), betas, and diagnostics.
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
    rss = float(np.sum(residuals**2))
    tss = float(np.sum((y - np.mean(y)) ** 2))

    r_squared = 1.0 - rss / tss if tss > 0 else 0.0
    k = X.shape[1]  # number of regressors including intercept
    adj_r_squared = 1.0 - (1.0 - r_squared) * (n - 1) / (n - k)

    # Standard errors
    sigma_sq = rss / (n - k)
    var_beta = sigma_sq * np.linalg.inv(XtX)
    se_beta = np.sqrt(np.diag(var_beta))

    # t-statistics and p-values
    t_stats = beta_hat / se_beta
    p_values = 2.0 * (1.0 - sp_stats.t.cdf(np.abs(t_stats), df=n - k))

    # Annualize alpha
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


def rolling_factor_exposure(
    excess_returns: np.ndarray,
    factor_returns: np.ndarray,
    dates: list[date],
    window: int = 756,
    step: int = 21,
) -> list[RollingFactorPoint]:
    """Compute factor regression over rolling windows.

    Parameters
    ----------
    excess_returns : shape (n,)
    factor_returns : shape (n, 5)
    dates : length n — corresponding dates
    window : rolling window size in trading days (default 756 = 3 years)
    step : step size in trading days (default 21 = 1 month)

    Returns
    -------
    Time series of RollingFactorPoint with factor loadings per window.
    """
    results: list[RollingFactorPoint] = []

    for end in range(window, len(excess_returns) + 1, step):
        start = end - window
        try:
            result = run_factor_regression(
                excess_returns[start:end],
                factor_returns[start:end],
                start_date=dates[start],
                end_date=dates[end - 1],
            )
            results.append(
                RollingFactorPoint(
                    window_end_date=dates[end - 1],
                    alpha=result.alpha,
                    betas=result.betas,
                    r_squared=result.r_squared,
                )
            )
        except InsufficientDataError:
            # Skip windows with insufficient data (shouldn't happen if
            # window >= 60, but be safe)
            continue

    return results


def compute_factor_attribution(
    excess_returns: np.ndarray,
    factor_returns: np.ndarray,
    regression: FactorRegressionResult,
) -> FactorAttribution:
    """Decompose cumulative excess return into factor contributions.

    Parameters
    ----------
    excess_returns : shape (T,)
    factor_returns : shape (T, 5)
    regression : pre-computed FactorRegressionResult

    Returns
    -------
    FactorAttribution with per-factor contributions.
    """
    total_excess = float(np.sum(excess_returns))

    # Cumulative factor returns over the period
    cum_factors = {
        name: float(np.sum(factor_returns[:, i]))
        for i, name in enumerate(FACTOR_NAMES)
    }

    # Factor contributions = beta * cumulative factor return
    contributions = {
        name: regression.betas[name] * cum_factors[name] for name in FACTOR_NAMES
    }

    # Alpha contribution = daily alpha * number of days
    alpha_contrib = regression.alpha_daily * len(excess_returns)

    # Residual = total - alpha - sum(factor contributions)
    explained = alpha_contrib + sum(contributions.values())
    residual = total_excess - explained

    # Percentage of total return explained by each factor
    abs_total = abs(total_excess) if total_excess != 0 else 1.0
    pct_contributions = {
        name: contributions[name] / abs_total for name in FACTOR_NAMES
    }

    return FactorAttribution(
        total_excess_return=total_excess,
        alpha_contribution=alpha_contrib,
        factor_contributions=contributions,
        residual=residual,
        factor_pct_of_return=pct_contributions,
    )


def style_analysis(
    portfolio_returns: np.ndarray,
    factor_returns: np.ndarray,
) -> StyleAnalysisResult:
    """Sharpe (1992) constrained style analysis.

    Uses the five Fama-French factors plus risk-free rate as style indices.
    Weights are constrained to sum to 1 and be non-negative.

    Parameters
    ----------
    portfolio_returns : shape (T,) — total returns (not excess)
    factor_returns : shape (T, 5) — MKT, SMB, HML, RMW, CMA

    Returns
    -------
    StyleAnalysisResult with style weights and classification.

    Raises
    ------
    InsufficientDataError if fewer than 60 observations.
    OptimizationError if the optimizer does not converge.
    """
    n = len(portfolio_returns)
    if n < 60:
        raise InsufficientDataError(f"Need at least 60 observations, got {n}")

    # Use factor returns as style proxies (K = 5 factors)
    K = factor_returns.shape[1]

    def objective(w: np.ndarray) -> float:
        predicted = factor_returns @ w
        residuals = portfolio_returns - predicted
        return float(np.sum(residuals**2))

    # Constraints: weights sum to 1
    constraints = [{"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)}]
    # Bounds: each weight between 0 and 1
    bounds = [(0.0, 1.0)] * K
    # Initial guess: equal weights
    w0 = np.ones(K) / K

    result = optimize.minimize(
        objective,
        w0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 1000},
    )

    if not result.success:
        raise OptimizationError(
            f"Style analysis did not converge: {result.message}"
        )

    weights = result.x
    predicted = factor_returns @ weights
    ss_res = float(np.sum((portfolio_returns - predicted) ** 2))
    ss_tot = float(np.sum((portfolio_returns - np.mean(portfolio_returns)) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # Map factor weights to style labels
    weight_dict = {name: float(weights[i]) for i, name in enumerate(FACTOR_NAMES)}
    style_label = _classify_style(weight_dict)

    return StyleAnalysisResult(
        weights=weight_dict,
        r_squared=r_squared,
        style_label=style_label,
        n_observations=n,
    )


def _classify_style(weights: dict[str, float]) -> str:
    """Classify into a Morningstar-style label based on factor loadings.

    Uses HML (value vs growth) and SMB (small vs large) weights to
    determine the style box placement.
    """
    # Determine value vs growth tilt from HML weight
    hml_w = weights.get("hml", 0)
    smb_w = weights.get("smb", 0)
    mkt_w = weights.get("mkt", 0)

    # Size: negative SMB = large cap bias, positive = small cap
    total_equity = sum(abs(v) for v in weights.values())
    if total_equity < 0.01:
        return "Undefined"

    # Size classification based on SMB relative weight
    smb_share = smb_w / total_equity if total_equity > 0 else 0
    if smb_share > 0.25:
        size = "Small"
    elif smb_share < 0.10:
        size = "Large"
    else:
        size = "Mid"

    # Style classification based on HML relative weight
    hml_share = hml_w / total_equity if total_equity > 0 else 0
    if hml_share > 0.25:
        style = "Value"
    elif hml_share < 0.10:
        style = "Growth"
    else:
        style = "Blend"

    return f"{size} {style}"


def detect_factor_drift(
    rolling_results: list[RollingFactorPoint],
    expected_ranges: Optional[dict[str, tuple[float, float]]] = None,
) -> list[FactorDriftAlert]:
    """Compare the most recent rolling factor exposures against expected ranges.

    Parameters
    ----------
    rolling_results : list of RollingFactorPoint from rolling_factor_exposure
    expected_ranges : optional override; defaults to EXPECTED_RANGES

    Returns
    -------
    List of FactorDriftAlert for factors outside expected ranges.
    """
    if not rolling_results:
        return []

    if expected_ranges is None:
        expected_ranges = EXPECTED_RANGES

    latest = rolling_results[-1]
    alerts: list[FactorDriftAlert] = []

    for factor in FACTOR_NAMES:
        beta = latest.betas[factor]
        low, high = expected_ranges[factor]

        if beta < low:
            severity = "critical" if beta < low - 0.3 else "warning"
            alerts.append(
                FactorDriftAlert(
                    factor=factor,
                    factor_label=FACTOR_LABELS[factor],
                    current_beta=beta,
                    expected_range=(low, high),
                    direction="below_expected",
                    severity=severity,
                    message=(
                        f"{FACTOR_LABELS[factor]} loading is {beta:.2f}, "
                        f"below expected range [{low:.2f}, {high:.2f}]."
                    ),
                )
            )
        elif beta > high:
            severity = "critical" if beta > high + 0.3 else "warning"
            alerts.append(
                FactorDriftAlert(
                    factor=factor,
                    factor_label=FACTOR_LABELS[factor],
                    current_beta=beta,
                    expected_range=(low, high),
                    direction="above_expected",
                    severity=severity,
                    message=(
                        f"{FACTOR_LABELS[factor]} loading is {beta:.2f}, "
                        f"above expected range [{low:.2f}, {high:.2f}]."
                    ),
                )
            )

    # Check for sign reversals on factors with expected positive sign
    for factor in ["hml", "rmw"]:
        if latest.betas[factor] < 0:
            alerts.append(
                FactorDriftAlert(
                    factor=factor,
                    factor_label=FACTOR_LABELS[factor],
                    current_beta=latest.betas[factor],
                    expected_range=expected_ranges[factor],
                    direction="sign_reversal",
                    severity="critical",
                    message=(
                        f"{FACTOR_LABELS[factor]} loading has reversed to "
                        f"{latest.betas[factor]:.2f}. Expected positive for a "
                        f"Munger value/quality strategy."
                    ),
                )
            )

    return alerts


def select_factor_region(exchange: Optional[str], asset_class: Optional[str]) -> str:
    """Determine which factor set to use for a given security.

    Parameters
    ----------
    exchange : exchange code (e.g. "NYSE", "XHEL")
    asset_class : asset class string (e.g. "stock", "crypto")

    Returns
    -------
    "us" or "europe"
    """
    if exchange and exchange in US_EXCHANGES:
        return "us"
    if exchange and exchange in EU_EXCHANGES:
        return "europe"
    if asset_class == "crypto":
        return "us"
    # Default to European factors for a Finnish investor
    return "europe"


def select_portfolio_factor_region(
    holdings: list[dict],
) -> str:
    """For portfolio-level regressions, use the region with the largest allocation.

    If European holdings >= 50% of portfolio value, use European factors.
    Otherwise use US factors.
    """
    total_value = sum(h.get("marketValueEurCents", 0) or 0 for h in holdings)
    if total_value == 0:
        return "europe"

    eu_value = 0
    for h in holdings:
        region = select_factor_region(h.get("exchange"), h.get("assetClass"))
        if region == "europe":
            eu_value += h.get("marketValueEurCents", 0) or 0

    return "europe" if eu_value >= total_value * 0.50 else "us"
