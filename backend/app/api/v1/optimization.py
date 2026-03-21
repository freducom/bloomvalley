"""Portfolio optimization endpoints — efficient frontier, optimal portfolio,
Black-Litterman, risk parity, rebalancing."""

from datetime import datetime, timezone

import numpy as np
import structlog
from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.api.v1.portfolio import _get_fx_rates
from app.api.v1.risk import _get_holdings_with_values, _get_price_returns, GLIDEPATH, ASSET_CLASS_MAP
from app.services.optimizer import (
    build_optimization_inputs,
    black_litterman,
    compute_efficient_frontier,
    equal_risk_contribution,
    expected_returns_historical,
    find_optimal_portfolio,
    generate_rebalance_trades,
    ledoit_wolf_shrinkage,
)

logger = structlog.get_logger()

router = APIRouter()

# Default risk-free rate (ECB deposit facility rate approximation)
DEFAULT_RISK_FREE_RATE = 0.035


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ViewItem(BaseModel):
    security: str
    expectedReturn: float
    confidence: float


class BlackLittermanRequest(BaseModel):
    views: list[ViewItem]
    riskAversion: float = 2.5
    lookbackDays: int = 252


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _prepare_optimization_data(
    lookback_days: int = 252,
) -> dict | None:
    """Fetch holdings, returns, and build optimization inputs.

    Returns None if insufficient data. Otherwise returns dict with:
        holdings, returns_matrix, mu, cov, opt_inputs, total_value_cents,
        cash_cents, sids_with_returns, min_len
    """
    holdings = await _get_holdings_with_values()
    if not holdings:
        return None

    total_value = sum(h.get("marketValueEurCents") or 0 for h in holdings)
    if total_value == 0:
        return None

    # Get cash balances
    from decimal import Decimal
    from sqlalchemy import select
    from app.db.engine import async_session
    from app.db.models.accounts import Account

    total_cash = 0
    fx_rates = await _get_fx_rates()
    async with async_session() as session:
        acct_ids = list({h["accountId"] for h in holdings})
        if acct_ids:
            result = await session.execute(
                select(Account).where(Account.id.in_(acct_ids))
            )
            for acct in result.scalars().all():
                if acct.cash_currency == "EUR":
                    total_cash += acct.cash_balance_cents
                else:
                    fx = fx_rates.get(acct.cash_currency, Decimal("1"))
                    total_cash += int(acct.cash_balance_cents / float(fx))

    portfolio_total = total_value + total_cash

    # Build optimization inputs (constraints, bounds, class membership)
    opt_inputs = build_optimization_inputs(holdings, current_age=45)
    tickers = opt_inputs["tickers"]
    security_ids = opt_inputs["security_ids"]

    # Deduplicate: map tickers to security IDs
    ticker_to_sid: dict[str, int] = {}
    for h in holdings:
        t = h.get("ticker", "")
        if t not in ticker_to_sid:
            ticker_to_sid[t] = h["securityId"]

    sids_for_returns = [ticker_to_sid.get(t, 0) for t in tickers]
    sids_for_returns = [s for s in sids_for_returns if s > 0]

    # Fetch price returns
    returns_dict = await _get_price_returns(sids_for_returns, lookback_days)

    # Build aligned returns matrix
    # Only include tickers that have sufficient return data
    valid_tickers: list[str] = []
    valid_indices: list[int] = []
    valid_returns: list[np.ndarray] = []

    for i, ticker in enumerate(tickers):
        sid = ticker_to_sid.get(ticker, 0)
        if sid in returns_dict and len(returns_dict[sid]) >= 20:
            valid_tickers.append(ticker)
            valid_indices.append(i)
            valid_returns.append(returns_dict[sid])

    if len(valid_tickers) < 2:
        logger.warning(
            "insufficient_data_for_optimization",
            valid_tickers=len(valid_tickers),
            required=2,
        )
        return None

    # Trim all to common length
    min_len = min(len(r) for r in valid_returns)
    if min_len < 20:
        return None

    returns_matrix = np.column_stack([r[-min_len:] for r in valid_returns])

    # Recompute opt_inputs for only the valid tickers
    valid_holdings = []
    seen = set()
    for h in holdings:
        t = h.get("ticker", "")
        if t in valid_tickers and t not in seen:
            valid_holdings.append(h)
            seen.add(t)

    opt_inputs = build_optimization_inputs(valid_holdings, current_age=45)

    # Expected returns and covariance
    mu = expected_returns_historical(returns_matrix)
    cov = ledoit_wolf_shrinkage(returns_matrix)

    return {
        "holdings": holdings,
        "valid_holdings": valid_holdings,
        "returns_matrix": returns_matrix,
        "mu": mu,
        "cov": cov,
        "opt_inputs": opt_inputs,
        "tickers": opt_inputs["tickers"],
        "total_value_cents": total_value,
        "cash_cents": total_cash,
        "portfolio_total_cents": portfolio_total,
        "min_len": min_len,
    }


def _frontier_point_to_dict(point, tickers: list[str]) -> dict:
    """Convert an EfficientFrontierPoint to a camelCase dict."""
    weights = {}
    for i, t in enumerate(tickers):
        w = float(point.weights[i])
        if w >= 0.001:
            weights[t] = round(w, 4)

    return {
        "expectedReturn": round(point.expected_return * 100, 2),
        "volatility": round(point.volatility * 100, 2),
        "sharpeRatio": round(point.sharpe_ratio, 4),
        "weights": weights,
    }


def _make_meta() -> dict:
    return {"timestamp": datetime.now(timezone.utc).isoformat()}


# ---------------------------------------------------------------------------
# GET /api/v1/optimization/efficient-frontier
# ---------------------------------------------------------------------------


@router.get("/efficient-frontier")
async def get_efficient_frontier(
    lookback_days: int = Query(252, alias="lookbackDays", ge=60, le=1260),
    risk_free_rate: float = Query(DEFAULT_RISK_FREE_RATE, alias="riskFreeRate"),
):
    """Compute the efficient frontier with constraints.

    Returns frontier points (risk, return, weights), tangent portfolio,
    and minimum variance portfolio.
    """
    data = await _prepare_optimization_data(lookback_days)
    if data is None:
        return {
            "data": None,
            "meta": _make_meta(),
            "error": "Insufficient data for optimization. Need at least 2 securities with 20+ days of price history.",
        }

    try:
        opt = data["opt_inputs"]
        result = compute_efficient_frontier(
            mu=data["mu"],
            cov=data["cov"],
            risk_free_rate=risk_free_rate,
            position_upper_bounds=opt["position_upper_bounds"],
            class_membership=opt["class_membership"],
            class_lower_bounds=opt["class_lower_bounds"],
            class_upper_bounds=opt["class_upper_bounds"],
            n_points=20,
        )
        result.asset_labels = data["tickers"]

        tickers = data["tickers"]

        return {
            "data": {
                "frontier": [_frontier_point_to_dict(p, tickers) for p in result.points],
                "tangentPortfolio": _frontier_point_to_dict(result.tangent_portfolio, tickers),
                "minVariancePortfolio": _frontier_point_to_dict(result.min_variance_portfolio, tickers),
                "assets": tickers,
                "lookbackDays": lookback_days,
                "tradingDays": data["min_len"],
                "riskFreeRate": risk_free_rate,
            },
            "meta": _make_meta(),
        }
    except (ValueError, np.linalg.LinAlgError) as exc:
        logger.error("efficient_frontier_failed", error=str(exc))
        return {
            "data": None,
            "meta": _make_meta(),
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# GET /api/v1/optimization/optimal
# ---------------------------------------------------------------------------


@router.get("/optimal")
async def get_optimal_portfolio(
    risk_tolerance: int = Query(5, alias="riskTolerance", ge=1, le=10),
    lookback_days: int = Query(252, alias="lookbackDays", ge=60, le=1260),
    risk_free_rate: float = Query(DEFAULT_RISK_FREE_RATE, alias="riskFreeRate"),
):
    """Compute the optimal portfolio for a given risk tolerance (1-10 scale).

    1 = aggressive (maximize returns), 10 = conservative (minimize variance).
    Default: 5 (balanced).
    """
    data = await _prepare_optimization_data(lookback_days)
    if data is None:
        return {
            "data": None,
            "meta": _make_meta(),
            "error": "Insufficient data for optimization.",
        }

    try:
        opt = data["opt_inputs"]
        result = find_optimal_portfolio(
            mu=data["mu"],
            cov=data["cov"],
            risk_free_rate=risk_free_rate,
            risk_tolerance=risk_tolerance,
            position_upper_bounds=opt["position_upper_bounds"],
            class_membership=opt["class_membership"],
            class_lower_bounds=opt["class_lower_bounds"],
            class_upper_bounds=opt["class_upper_bounds"],
            tickers=data["tickers"],
        )

        # Filter zero weights for cleaner output
        weights = {t: round(w, 4) for t, w in result.weights.items() if w >= 0.001}

        return {
            "data": {
                "weights": weights,
                "expectedReturn": round(result.expected_return * 100, 2),
                "volatility": round(result.volatility * 100, 2),
                "sharpeRatio": round(result.sharpe_ratio, 4),
                "riskTolerance": result.risk_tolerance,
                "lambdaValue": result.lambda_value,
                "glidepathCompliant": result.glidepath_compliant,
                "constraintViolations": result.constraint_violations,
                "assets": data["tickers"],
                "lookbackDays": lookback_days,
                "tradingDays": data["min_len"],
            },
            "meta": _make_meta(),
        }
    except (ValueError, np.linalg.LinAlgError) as exc:
        logger.error("optimal_portfolio_failed", error=str(exc))
        return {
            "data": None,
            "meta": _make_meta(),
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# POST /api/v1/optimization/black-litterman
# ---------------------------------------------------------------------------


@router.post("/black-litterman")
async def post_black_litterman(body: BlackLittermanRequest):
    """Compute Black-Litterman posterior returns blending market equilibrium
    with investor views.

    Request body:
        views: [{security, expectedReturn, confidence}, ...]
        riskAversion: float (default 2.5)
        lookbackDays: int (default 252)
    """
    data = await _prepare_optimization_data(body.lookbackDays)
    if data is None:
        return {
            "data": None,
            "meta": _make_meta(),
            "error": "Insufficient data for Black-Litterman.",
        }

    tickers = data["tickers"]

    # Build market cap proxies from current market values
    market_caps = np.zeros(len(tickers))
    ticker_idx = {t: i for i, t in enumerate(tickers)}
    for h in data["holdings"]:
        t = h.get("ticker", "")
        if t in ticker_idx:
            market_caps[ticker_idx[t]] += h.get("marketValueEurCents") or 0

    # Convert views from pydantic to dicts
    views_dicts = [
        {
            "security": v.security,
            "expectedReturn": v.expectedReturn,
            "confidence": v.confidence,
        }
        for v in body.views
    ]

    try:
        result = black_litterman(
            market_caps=market_caps,
            cov=data["cov"],
            views=views_dicts,
            tickers=tickers,
            risk_aversion=body.riskAversion,
        )

        # Also compute optimal portfolio with BL posterior returns
        opt = data["opt_inputs"]
        bl_mu = np.array([result.posterior_returns[t] for t in tickers])

        optimal = find_optimal_portfolio(
            mu=bl_mu,
            cov=result.posterior_cov,
            risk_free_rate=DEFAULT_RISK_FREE_RATE,
            risk_tolerance=5,
            position_upper_bounds=opt["position_upper_bounds"],
            class_membership=opt["class_membership"],
            class_lower_bounds=opt["class_lower_bounds"],
            class_upper_bounds=opt["class_upper_bounds"],
            tickers=tickers,
        )

        optimal_weights = {t: round(w, 4) for t, w in optimal.weights.items() if w >= 0.001}

        return {
            "data": {
                "posteriorReturns": {
                    t: round(r * 100, 2) for t, r in result.posterior_returns.items()
                },
                "priorReturns": {
                    t: round(r * 100, 2) for t, r in result.prior_returns.items()
                },
                "viewsApplied": result.views_applied,
                "viewsRejected": result.views_rejected,
                "optimalWeights": optimal_weights,
                "optimalExpectedReturn": round(optimal.expected_return * 100, 2),
                "optimalVolatility": round(optimal.volatility * 100, 2),
                "optimalSharpe": round(optimal.sharpe_ratio, 4),
                "assets": tickers,
                "riskAversion": body.riskAversion,
            },
            "meta": _make_meta(),
        }
    except (ValueError, np.linalg.LinAlgError) as exc:
        logger.error("black_litterman_failed", error=str(exc))
        return {
            "data": None,
            "meta": _make_meta(),
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# GET /api/v1/optimization/risk-parity
# ---------------------------------------------------------------------------


@router.get("/risk-parity")
async def get_risk_parity(
    lookback_days: int = Query(252, alias="lookbackDays", ge=60, le=1260),
):
    """Compute the Equal Risk Contribution (ERC) portfolio.

    Each asset contributes equally to total portfolio risk, regardless
    of expected returns.
    """
    data = await _prepare_optimization_data(lookback_days)
    if data is None:
        return {
            "data": None,
            "meta": _make_meta(),
            "error": "Insufficient data for risk parity.",
        }

    try:
        result = equal_risk_contribution(
            cov=data["cov"],
            mu=data["mu"],
            tickers=data["tickers"],
        )

        weights = {t: round(w, 4) for t, w in result.weights.items() if w >= 0.001}
        risk_contribs = {
            t: round(rc, 4) for t, rc in result.risk_contributions.items() if rc >= 0.001
        }

        return {
            "data": {
                "weights": weights,
                "riskContributions": risk_contribs,
                "portfolioVolatility": round(result.portfolio_volatility * 100, 2),
                "expectedReturn": round(result.expected_return * 100, 2),
                "assets": data["tickers"],
                "lookbackDays": lookback_days,
                "tradingDays": data["min_len"],
            },
            "meta": _make_meta(),
        }
    except (ValueError, np.linalg.LinAlgError) as exc:
        logger.error("risk_parity_failed", error=str(exc))
        return {
            "data": None,
            "meta": _make_meta(),
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# GET /api/v1/optimization/rebalance
# ---------------------------------------------------------------------------


@router.get("/rebalance")
async def get_rebalance(
    risk_tolerance: int = Query(5, alias="riskTolerance", ge=1, le=10),
    lookback_days: int = Query(252, alias="lookbackDays", ge=60, le=1260),
    risk_free_rate: float = Query(DEFAULT_RISK_FREE_RATE, alias="riskFreeRate"),
):
    """Generate tax-aware rebalancing trade recommendations.

    First computes the optimal portfolio for the given risk tolerance,
    then compares with current holdings to generate trades.
    Prefers tax-free sells (osakesaastotili), tax-loss harvesting,
    and respects minimum trade size of 500 EUR.
    """
    data = await _prepare_optimization_data(lookback_days)
    if data is None:
        return {
            "data": None,
            "meta": _make_meta(),
            "error": "Insufficient data for rebalancing.",
        }

    try:
        # Step 1: Compute optimal portfolio
        opt = data["opt_inputs"]
        optimal = find_optimal_portfolio(
            mu=data["mu"],
            cov=data["cov"],
            risk_free_rate=risk_free_rate,
            risk_tolerance=risk_tolerance,
            position_upper_bounds=opt["position_upper_bounds"],
            class_membership=opt["class_membership"],
            class_lower_bounds=opt["class_lower_bounds"],
            class_upper_bounds=opt["class_upper_bounds"],
            tickers=data["tickers"],
        )

        # Step 2: Generate rebalance trades
        result = generate_rebalance_trades(
            current_holdings=data["holdings"],
            optimal_weights=optimal.weights,
            total_portfolio_cents=data["portfolio_total_cents"],
            available_cash_cents=data["cash_cents"],
        )

        trades = [
            {
                "action": t.action,
                "ticker": t.ticker,
                "securityId": t.security_id,
                "accountId": t.account_id,
                "accountType": t.account_type,
                "amountEurCents": t.amount_eur_cents,
                "estimatedTaxCents": t.estimated_tax_cents,
                "rationale": t.rationale,
                "priority": t.priority,
            }
            for t in result.trades
        ]

        return {
            "data": {
                "trades": trades,
                "currentWeights": {
                    t: round(w, 4) for t, w in result.current_weights.items() if w >= 0.001
                },
                "targetWeights": {
                    t: round(w, 4) for t, w in result.target_weights.items() if w >= 0.001
                },
                "postTradeWeights": {
                    t: round(w, 4) for t, w in result.post_trade_weights.items() if w >= 0.001
                },
                "totalBuyCents": result.total_buy_cents,
                "totalSellCents": result.total_sell_cents,
                "totalEstimatedTaxCents": result.total_estimated_tax_cents,
                "netCashRequiredCents": result.net_cash_required_cents,
                "optimizationMethod": result.optimization_method,
                "riskTolerance": risk_tolerance,
                "optimalExpectedReturn": round(optimal.expected_return * 100, 2),
                "optimalVolatility": round(optimal.volatility * 100, 2),
                "optimalSharpe": round(optimal.sharpe_ratio, 4),
            },
            "meta": _make_meta(),
        }
    except (ValueError, np.linalg.LinAlgError) as exc:
        logger.error("rebalance_failed", error=str(exc))
        return {
            "data": None,
            "meta": _make_meta(),
            "error": str(exc),
        }
