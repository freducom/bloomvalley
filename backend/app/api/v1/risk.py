"""Risk analysis endpoints — portfolio risk metrics, correlation, concentration."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import math

import numpy as np
import structlog
from fastapi import APIRouter, Query
from sqlalchemy import select, func

from app.db.engine import async_session
from app.db.models.prices import Price, FxRate
from app.db.models.securities import Security
from app.db.models.transactions import Transaction
from app.db.models.accounts import Account
from app.api.v1.portfolio import _get_fx_rates, _get_latest_prices

logger = structlog.get_logger()

router = APIRouter()

# Glidepath targets by age
GLIDEPATH = {
    45: {"equity": 0.75, "fixed_income": 0.15, "crypto": 0.07, "cash": 0.03},
    50: {"equity": 0.65, "fixed_income": 0.22, "crypto": 0.06, "cash": 0.07},
    55: {"equity": 0.50, "fixed_income": 0.38, "crypto": 0.04, "cash": 0.08},
    60: {"equity": 0.30, "fixed_income": 0.60, "crypto": 0.02, "cash": 0.08},
}

# Concentration thresholds (informational — no hard limits per investment policy)
NOTABLE_POSITION_PCT = 10.0  # Flag positions above this for awareness
NOTABLE_SECTOR_PCT = 30.0    # Flag sectors above this for awareness
MAX_CRYPTO_PCT = 10.0        # Crypto has an actual glidepath target

# Map asset_class to glidepath categories
ASSET_CLASS_MAP = {
    "stock": "equity",
    "etf": "equity",
    "bond": "fixed_income",
    "fund": "fixed_income",
    "crypto": "crypto",
}

# Stress test scenarios: name -> {description, shocks by asset_class}
STRESS_SCENARIOS = {
    "2008_crash": {
        "name": "2008 Financial Crisis",
        "description": "Equity -50%, crypto -80%, bonds +5%",
        "shocks": {"stock": -0.50, "etf": -0.50, "fund": 0.05, "bond": 0.05, "crypto": -0.80},
    },
    "rate_shock": {
        "name": "Rate Shock (+200bp)",
        "description": "Equity -15%, bonds/funds -10%, crypto -20%",
        "shocks": {"stock": -0.15, "etf": -0.15, "fund": -0.10, "bond": -0.10, "crypto": -0.20},
    },
    "crypto_winter": {
        "name": "Crypto Winter",
        "description": "Crypto -85%, equity -5%",
        "shocks": {"stock": -0.05, "etf": -0.05, "fund": 0.02, "bond": 0.02, "crypto": -0.85},
    },
    "stagflation": {
        "name": "Stagflation",
        "description": "Equity -30%, bonds/funds -15%, crypto -50%",
        "shocks": {"stock": -0.30, "etf": -0.30, "fund": -0.15, "bond": -0.15, "crypto": -0.50},
    },
    "nordic_housing": {
        "name": "Nordic Housing Crisis",
        "description": "Finnish/Nordic equities -40%, other equity -15%",
        "shocks": {"stock": -0.30, "etf": -0.20, "fund": 0.03, "bond": 0.03, "crypto": -0.10},
    },
}


async def _get_holdings_with_values():
    """Get current holdings with EUR market values. Returns list of dicts."""
    from app.api.v1.portfolio import get_holdings
    resp = await get_holdings(account_id=None)
    return resp["data"]


async def _get_price_returns(security_ids: list[int], days: int = 252) -> dict[int, np.ndarray]:
    """Get daily log returns for securities over the given period."""
    from_date = date.today() - timedelta(days=int(days * 1.5))  # Extra buffer for weekends
    returns: dict[int, np.ndarray] = {}

    async with async_session() as session:
        for sid in security_ids:
            result = await session.execute(
                select(Price.date, Price.close_cents)
                .where(Price.security_id == sid, Price.date >= from_date)
                .order_by(Price.date)
            )
            rows = result.all()
            if len(rows) < 2:
                continue
            closes = np.array([float(r.close_cents) for r in rows])
            log_ret = np.diff(np.log(closes))
            # Trim to requested number of trading days
            if len(log_ret) > days:
                log_ret = log_ret[-days:]
            returns[sid] = log_ret

    return returns


@router.get("")
async def get_risk_analysis(
    period: str = Query("1Y", description="1Y, 2Y, 5Y — lookback for risk calcs"),
):
    """Comprehensive risk analysis for the portfolio."""
    period_days = {"1Y": 252, "2Y": 504, "5Y": 1260}.get(period, 252)

    holdings = await _get_holdings_with_values()
    if not holdings:
        return {
            "data": {
                "metrics": None,
                "concentration": None,
                "correlation": None,
                "stressTests": None,
                "glidepath": None,
            },
            "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
        }

    # Total portfolio value (EUR cents)
    total_value = sum(h["marketValueEurCents"] or 0 for h in holdings)
    if total_value == 0:
        return {
            "data": {
                "metrics": None,
                "concentration": None,
                "correlation": None,
                "stressTests": None,
                "glidepath": None,
            },
            "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
        }

    # Get cash balances
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

    # ── Weights ──
    security_ids = [h["securityId"] for h in holdings]
    weights = {}
    for h in holdings:
        sid = h["securityId"]
        w = (h["marketValueEurCents"] or 0) / portfolio_total
        weights[sid] = weights.get(sid, 0) + w

    # ── Price returns ──
    returns = await _get_price_returns(security_ids, period_days)

    # ── Portfolio daily returns (weighted) ──
    # Find common date range (min length across all securities with returns)
    sids_with_returns = [sid for sid in security_ids if sid in returns]
    if not sids_with_returns:
        # No price history — return concentration only
        return _build_response_no_returns(holdings, portfolio_total, total_cash)

    min_len = min(len(returns[sid]) for sid in sids_with_returns)
    if min_len < 5:
        return _build_response_no_returns(holdings, portfolio_total, total_cash)

    # Trim all to same length and compute portfolio returns
    port_returns = np.zeros(min_len)
    total_w_with_returns = sum(weights.get(sid, 0) for sid in sids_with_returns)
    cash_w = total_cash / portfolio_total if portfolio_total > 0 else 0

    for sid in sids_with_returns:
        r = returns[sid][-min_len:]
        w = weights.get(sid, 0)
        # Normalize weight to sum of weights with returns + cash
        if total_w_with_returns > 0:
            port_returns += r * (w / (total_w_with_returns + cash_w))

    # ── Portfolio metrics ──
    ann_factor = 252
    daily_mean = float(np.mean(port_returns))
    daily_std = float(np.std(port_returns, ddof=1)) if len(port_returns) > 1 else 0.0

    annualized_return = daily_mean * ann_factor
    annualized_vol = daily_std * np.sqrt(ann_factor)

    # Risk-free rate (approximate: use 3% for EUR)
    rf = 0.03

    # Sharpe ratio
    sharpe = (annualized_return - rf) / annualized_vol if annualized_vol > 0 else 0.0

    # Sortino ratio (downside deviation)
    downside = port_returns[port_returns < 0]
    downside_std = float(np.std(downside, ddof=1)) * np.sqrt(ann_factor) if len(downside) > 1 else 0.0
    sortino = (annualized_return - rf) / downside_std if downside_std > 0 else 0.0

    # Max drawdown
    cumulative = np.cumsum(port_returns)
    cum_values = np.exp(cumulative)
    running_max = np.maximum.accumulate(cum_values)
    drawdowns = (cum_values - running_max) / running_max
    max_drawdown = float(np.min(drawdowns))

    # Value at Risk (95% parametric)
    var_95 = float(np.percentile(port_returns, 5)) * np.sqrt(1)  # 1-day VaR
    var_95_annual = var_95 * np.sqrt(ann_factor)

    # Beta vs. largest holding (proxy for market if no benchmark)
    # Use equal-weighted portfolio returns as "market" proxy
    beta = 1.0  # Default

    metrics = {
        "annualizedReturn": round(annualized_return * 100, 2),
        "annualizedVolatility": round(annualized_vol * 100, 2),
        "sharpeRatio": round(sharpe, 2),
        "sortinoRatio": round(sortino, 2),
        "maxDrawdown": round(max_drawdown * 100, 2),
        "var95Daily": round(var_95 * 100, 2),
        "var95DailyCents": int(var_95 * portfolio_total),
        "beta": round(beta, 2),
        "tradingDays": min_len,
        "holdingsWithPriceData": len(sids_with_returns),
        "holdingsTotal": len(holdings),
    }

    # ── Correlation matrix ──
    # Build for top holdings by weight
    top_sids = sorted(sids_with_returns, key=lambda s: weights.get(s, 0), reverse=True)[:15]
    sid_to_ticker = {}
    for h in holdings:
        sid_to_ticker[h["securityId"]] = h["ticker"]

    corr_matrix = None
    if len(top_sids) >= 2:
        ret_matrix = np.column_stack([returns[sid][-min_len:] for sid in top_sids])
        corr = np.corrcoef(ret_matrix, rowvar=False)
        tickers = [sid_to_ticker.get(sid, str(sid)) for sid in top_sids]
        corr_matrix = {
            "tickers": tickers,
            "matrix": [[round(float(corr[i][j]), 3) for j in range(len(top_sids))] for i in range(len(top_sids))],
        }

    # Sanitize NaN/inf values that can't be JSON-serialized
    def _clean(v):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return v

    metrics = {k: _clean(v) for k, v in metrics.items()}

    if corr_matrix is not None:
        corr_matrix = {
            k: [[_clean(c) for c in row] for row in v] if isinstance(v, list) else v
            for k, v in corr_matrix.items()
        }

    # ── Concentration ──
    concentration = _compute_concentration(holdings, portfolio_total, total_cash)

    # ── Stress tests ──
    stress_tests = _compute_stress_tests(holdings, portfolio_total, total_cash)

    # ── Glidepath ──
    glidepath = _compute_glidepath(holdings, portfolio_total, total_cash)

    return {
        "data": {
            "metrics": metrics,
            "concentration": concentration,
            "correlation": corr_matrix,
            "stressTests": stress_tests,
            "glidepath": glidepath,
        },
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


def _build_response_no_returns(holdings, portfolio_total, total_cash):
    """Build response when we have holdings but no price history."""
    return {
        "data": {
            "metrics": None,
            "concentration": _compute_concentration(holdings, portfolio_total, total_cash),
            "correlation": None,
            "stressTests": _compute_stress_tests(holdings, portfolio_total, total_cash),
            "glidepath": _compute_glidepath(holdings, portfolio_total, total_cash),
        },
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


def _compute_concentration(holdings, portfolio_total, total_cash):
    """Compute position and sector concentration."""
    if portfolio_total == 0:
        return None

    # Position concentration
    positions = []
    for h in holdings:
        val = h["marketValueEurCents"] or 0
        pct = (val / portfolio_total) * 100
        positions.append({
            "ticker": h["ticker"],
            "name": h["name"],
            "assetClass": h["assetClass"],
            "sector": h["sector"],
            "valueCents": val,
            "weight": round(pct, 2),
            "notable": pct > NOTABLE_POSITION_PCT and h["assetClass"] == "stock",
        })
    positions.sort(key=lambda p: p["weight"], reverse=True)

    # Sector concentration
    sectors: dict[str, float] = {}
    for h in holdings:
        s = h["sector"] or "Unknown"
        val = h["marketValueEurCents"] or 0
        sectors[s] = sectors.get(s, 0) + (val / portfolio_total) * 100
    sector_list = [
        {"sector": s, "weight": round(w, 2), "notable": w > NOTABLE_SECTOR_PCT}
        for s, w in sorted(sectors.items(), key=lambda x: x[1], reverse=True)
    ]

    # Asset class breakdown
    asset_classes: dict[str, float] = {}
    for h in holdings:
        ac = h["assetClass"] or "other"
        val = h["marketValueEurCents"] or 0
        asset_classes[ac] = asset_classes.get(ac, 0) + (val / portfolio_total) * 100
    if total_cash > 0:
        asset_classes["cash"] = (total_cash / portfolio_total) * 100
    ac_list = [
        {"assetClass": ac, "weight": round(w, 2)}
        for ac, w in sorted(asset_classes.items(), key=lambda x: x[1], reverse=True)
    ]

    # Crypto concentration check
    crypto_pct = asset_classes.get("crypto", 0)

    return {
        "positions": positions,
        "sectors": sector_list,
        "assetClasses": ac_list,
        "alerts": _concentration_alerts(positions, sector_list, crypto_pct),
    }


def _concentration_alerts(positions, sectors, crypto_pct):
    """Generate concentration awareness alerts (no hard limits per investment policy)."""
    alerts = []
    for p in positions:
        if p.get("notable"):
            alerts.append({
                "type": "concentration",
                "severity": "info",
                "message": f"{p['ticker']} is {p['weight']:.1f}% of portfolio — notable concentration",
            })
    for s in sectors:
        if isinstance(s, dict) and s.get("notable"):
            alerts.append({
                "type": "concentration",
                "severity": "info",
                "message": f"{s['sector']} sector is {s['weight']:.1f}% of portfolio — notable concentration",
            })
    if crypto_pct > MAX_CRYPTO_PCT:
        alerts.append({
            "type": "crypto",
            "severity": "warning",
            "message": f"Crypto allocation is {crypto_pct:.1f}% (glidepath target: {MAX_CRYPTO_PCT}%)",
        })
    return alerts


def _compute_stress_tests(holdings, portfolio_total, total_cash):
    """Apply stress scenarios to current portfolio."""
    if portfolio_total == 0:
        return None

    results = []
    for key, scenario in STRESS_SCENARIOS.items():
        impact_cents = 0
        for h in holdings:
            val = h["marketValueEurCents"] or 0
            shock = scenario["shocks"].get(h["assetClass"], 0)
            impact_cents += int(val * shock)

        results.append({
            "id": key,
            "name": scenario["name"],
            "description": scenario["description"],
            "impactCents": impact_cents,
            "impactPct": round((impact_cents / portfolio_total) * 100, 2),
            "portfolioAfterCents": portfolio_total + impact_cents,
        })

    return results


def _compute_glidepath(holdings, portfolio_total, total_cash):
    """Compare current allocation to glidepath target for age 45."""
    if portfolio_total == 0:
        return None

    current_age = 45
    target = GLIDEPATH.get(current_age, GLIDEPATH[45])

    # Current allocation by glidepath category
    current: dict[str, float] = {"equity": 0, "fixed_income": 0, "crypto": 0, "cash": 0}
    for h in holdings:
        cat = ASSET_CLASS_MAP.get(h["assetClass"], "equity")
        val = h["marketValueEurCents"] or 0
        current[cat] += val / portfolio_total

    current["cash"] += total_cash / portfolio_total if portfolio_total > 0 else 0

    categories = []
    for cat in ["equity", "fixed_income", "crypto", "cash"]:
        cur = current.get(cat, 0)
        tgt = target.get(cat, 0)
        categories.append({
            "category": cat,
            "current": round(cur * 100, 1),
            "target": round(tgt * 100, 1),
            "drift": round((cur - tgt) * 100, 1),
        })

    return {
        "currentAge": current_age,
        "targetAge": 60,
        "categories": categories,
        "schedule": [
            {"age": age, **{k: round(v * 100, 1) for k, v in alloc.items()}}
            for age, alloc in sorted(GLIDEPATH.items())
        ],
    }
