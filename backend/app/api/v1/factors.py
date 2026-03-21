"""Factor analysis endpoints — Fama-French 5-factor exposure, attribution,
style analysis, and rolling factor loadings."""

from datetime import date, datetime, timedelta, timezone

import numpy as np
import structlog
from fastapi import APIRouter, Query
from sqlalchemy import select, func

from app.db.engine import async_session
from app.db.models.prices import Price, MacroIndicator
from app.db.models.securities import Security
from app.db.models.transactions import Transaction
from app.db.models.accounts import Account
from app.api.v1.portfolio import _get_fx_rates, _get_latest_prices
from app.services.factor_analysis import (
    FACTOR_NAMES,
    InsufficientDataError,
    OptimizationError,
    run_factor_regression,
    rolling_factor_exposure,
    compute_factor_attribution,
    style_analysis,
    detect_factor_drift,
    select_factor_region,
    select_portfolio_factor_region,
)

logger = structlog.get_logger()

router = APIRouter()

SIGNIFICANCE_LEVEL = 0.05


# ── Helpers ──────────────────────────────────────────────────────────────


async def _get_holdings_with_values() -> list[dict]:
    """Get current holdings with EUR market values."""
    from app.api.v1.portfolio import get_holdings

    resp = await get_holdings(account_id=None)
    return resp["data"]


async def _get_daily_returns(
    security_ids: list[int], days: int
) -> dict[int, tuple[list[date], np.ndarray]]:
    """Get daily simple returns for securities.

    Returns {security_id: (dates, returns_array)}.
    Uses simple returns (not log) to match French Data Library convention.
    """
    buffer_days = int(days * 1.7)  # extra buffer for weekends/holidays
    from_date = date.today() - timedelta(days=buffer_days)
    result_map: dict[int, tuple[list[date], np.ndarray]] = {}

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

            dates_list = [r.date for r in rows]
            closes = np.array([float(r.close_cents) for r in rows])
            # Simple returns: (P_t - P_{t-1}) / P_{t-1}
            simple_ret = np.diff(closes) / closes[:-1]
            ret_dates = dates_list[1:]

            # Trim to requested number of trading days
            if len(simple_ret) > days:
                simple_ret = simple_ret[-days:]
                ret_dates = ret_dates[-days:]

            result_map[sid] = (ret_dates, simple_ret)

    return result_map


async def _get_factor_returns(
    region: str, dates: list[date]
) -> tuple[np.ndarray, np.ndarray, date]:
    """Get Fama-French factor returns for the given dates and region.

    Parameters
    ----------
    region : "us" or "europe"
    dates : list of dates to match against

    Returns
    -------
    (factor_matrix, rf_array, max_factor_date)
    factor_matrix: shape (n, 5) — MKT, SMB, HML, RMW, CMA
    rf_array: shape (n,) — risk-free rate
    max_factor_date: latest date with factor data
    """
    prefix = "ff5_us" if region == "us" else "ff5_eu"
    factor_codes = [
        f"{prefix}_mkt_rf",
        f"{prefix}_smb",
        f"{prefix}_hml",
        f"{prefix}_rmw",
        f"{prefix}_cma",
        f"{prefix}_rf",
    ]

    min_date = min(dates)
    max_date = max(dates)

    # Fetch all factor data in the date range
    async with async_session() as session:
        result = await session.execute(
            select(
                MacroIndicator.indicator_code,
                MacroIndicator.date,
                MacroIndicator.value,
            )
            .where(
                MacroIndicator.indicator_code.in_(factor_codes),
                MacroIndicator.date >= min_date,
                MacroIndicator.date <= max_date,
            )
            .order_by(MacroIndicator.date)
        )
        rows = result.all()

    if not rows:
        return np.array([]), np.array([]), min_date

    # Build lookup: {(code, date): value}
    lookup: dict[tuple[str, date], float] = {}
    max_factor_date = min_date
    for row in rows:
        lookup[(row.indicator_code, row.date)] = float(row.value)
        if row.date > max_factor_date:
            max_factor_date = row.date

    # Align with requested dates — only keep dates where ALL factors are available
    factor_matrix_rows: list[list[float]] = []
    rf_values: list[float] = []
    aligned_dates: list[date] = []

    for d in dates:
        values = []
        all_found = True
        for code in factor_codes[:5]:
            val = lookup.get((code, d))
            if val is None:
                all_found = False
                break
            values.append(val)

        rf_val = lookup.get((factor_codes[5], d))
        if not all_found or rf_val is None:
            continue

        factor_matrix_rows.append(values)
        rf_values.append(rf_val)
        aligned_dates.append(d)

    if not factor_matrix_rows:
        return np.array([]), np.array([]), max_factor_date

    return (
        np.array(factor_matrix_rows),
        np.array(rf_values),
        max_factor_date,
    )


async def _compute_portfolio_returns(
    holdings: list[dict], lookback_days: int
) -> tuple[list[date], np.ndarray, int]:
    """Compute weighted portfolio daily returns.

    Returns (dates, portfolio_returns, n_securities_used).
    """
    security_ids = list({h["securityId"] for h in holdings})
    returns_data = await _get_daily_returns(security_ids, lookback_days)

    sids_with_returns = [sid for sid in security_ids if sid in returns_data]
    if not sids_with_returns:
        return [], np.array([]), 0

    # Compute weights
    total_value = sum(h.get("marketValueEurCents", 0) or 0 for h in holdings)
    if total_value == 0:
        return [], np.array([]), 0

    weights: dict[int, float] = {}
    for h in holdings:
        sid = h["securityId"]
        w = (h.get("marketValueEurCents", 0) or 0) / total_value
        weights[sid] = weights.get(sid, 0) + w

    # Find common date range across all securities with returns
    date_sets = [set(returns_data[sid][0]) for sid in sids_with_returns]
    common_dates = sorted(set.intersection(*date_sets)) if date_sets else []

    if len(common_dates) < 5:
        # Fallback: use the security with the most data and available dates
        max_sid = max(sids_with_returns, key=lambda s: len(returns_data[s][0]))
        common_dates = returns_data[max_sid][0]

    if not common_dates:
        return [], np.array([]), 0

    # Build date-indexed returns per security
    date_to_idx: dict[date, int] = {d: i for i, d in enumerate(common_dates)}
    port_returns = np.zeros(len(common_dates))
    total_w_used = 0.0

    for sid in sids_with_returns:
        dates_s, rets_s = returns_data[sid]
        w = weights.get(sid, 0)
        total_w_used += w

        for i, d in enumerate(dates_s):
            idx = date_to_idx.get(d)
            if idx is not None:
                port_returns[idx] += rets_s[i] * w

    # Normalize if not all holdings have return data
    if total_w_used > 0 and total_w_used < 0.99:
        port_returns /= total_w_used

    return common_dates, port_returns, len(sids_with_returns)


def _resolve_region(
    region_param: str, holdings: list[dict]
) -> str:
    """Resolve the factor region from the query parameter and holdings."""
    if region_param in ("us", "europe"):
        return region_param

    # Auto-detect from holdings
    enriched = []
    for h in holdings:
        enriched.append({
            "exchange": h.get("exchange"),
            "assetClass": h.get("assetClass"),
            "marketValueEurCents": h.get("marketValueEurCents", 0),
        })
    return select_portfolio_factor_region(enriched)


def _format_regression_response(
    reg: "run_factor_regression",  # type: ignore[name-defined]  # noqa: F821
    region: str,
    factor_data_through: date,
    lookback_days: int,
    drift_alerts: list | None = None,
    security_id: int | None = None,
    ticker: str | None = None,
) -> dict:
    """Format a FactorRegressionResult into the API response shape."""
    data: dict = {}

    if security_id is not None:
        data["securityId"] = security_id
    if ticker is not None:
        data["ticker"] = ticker

    data["regionUsed"] = region
    data["alpha"] = round(reg.alpha, 6)
    data["alphaDaily"] = round(reg.alpha_daily, 8)
    data["alphaTStat"] = round(reg.alpha_t_stat, 4)
    data["alphaPValue"] = round(reg.alpha_p_value, 6)
    data["alphaSignificant"] = reg.alpha_p_value < SIGNIFICANCE_LEVEL
    data["betas"] = {
        name: {
            "value": round(reg.betas[name], 4),
            "tStat": round(reg.beta_t_stats[name], 4),
            "pValue": round(reg.beta_p_values[name], 6),
            "significant": reg.beta_p_values[name] < SIGNIFICANCE_LEVEL,
        }
        for name in FACTOR_NAMES
    }
    data["rSquared"] = round(reg.r_squared, 4)
    data["adjRSquared"] = round(reg.adj_r_squared, 4)
    data["nObservations"] = reg.n_observations

    if drift_alerts is not None:
        data["driftAlerts"] = [
            {
                "factor": a.factor,
                "factorLabel": a.factor_label,
                "currentBeta": round(a.current_beta, 4),
                "expectedRange": list(a.expected_range),
                "direction": a.direction,
                "severity": a.severity,
                "message": a.message,
            }
            for a in drift_alerts
        ]

    meta = {
        "calculatedAt": datetime.now(timezone.utc).isoformat(),
        "lookbackDays": lookback_days,
        "tradingDaysAvailable": reg.n_observations,
        "region": region,
        "frequency": "daily",
        "factorDataThrough": factor_data_through.isoformat(),
        "significanceLevel": SIGNIFICANCE_LEVEL,
    }

    return {"data": data, "meta": meta}


def _null_response(reason: str, meta_extra: dict | None = None) -> dict:
    """Return a null data response with a reason."""
    meta = {
        "calculatedAt": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
    }
    if meta_extra:
        meta.update(meta_extra)
    return {"data": None, "meta": meta}


# ── Endpoints ────────────────────────────────────────────────────────────


@router.get("/exposure")
async def get_factor_exposure(
    lookback_days: int = Query(756, alias="lookbackDays", ge=60, le=2520),
    region: str = Query("auto", regex="^(us|europe|auto)$"),
):
    """Current Fama-French 5-factor loadings for the full portfolio."""
    holdings = await _get_holdings_with_values()
    if not holdings:
        return _null_response("no_holdings")

    resolved_region = _resolve_region(region, holdings)

    # Compute portfolio returns
    dates, port_returns, n_securities = await _compute_portfolio_returns(
        holdings, lookback_days
    )
    if len(port_returns) < 60:
        return _null_response(
            "insufficient_history",
            {"tradingDaysAvailable": len(port_returns), "minimumRequired": 60},
        )

    # Get factor data
    factor_matrix, rf_array, factor_data_through = await _get_factor_returns(
        resolved_region, dates
    )
    if len(factor_matrix) < 60:
        return _null_response(
            "insufficient_factor_data",
            {
                "factorDaysAvailable": len(factor_matrix),
                "minimumRequired": 60,
                "region": resolved_region,
            },
        )

    # Align portfolio returns with factor dates
    factor_dates_set = set(dates[: len(factor_matrix)])
    aligned_port = []
    aligned_factors = []
    aligned_rf = []

    date_to_port = dict(zip(dates, port_returns))
    # factor data is already date-aligned from _get_factor_returns
    # We need to re-align since factor data might have gaps
    factor_date_list = dates[: len(factor_matrix)]

    for i, d in enumerate(factor_date_list):
        if d in date_to_port and i < len(factor_matrix):
            aligned_port.append(date_to_port[d])
            aligned_factors.append(factor_matrix[i])
            aligned_rf.append(rf_array[i])

    if len(aligned_port) < 60:
        return _null_response(
            "insufficient_overlapping_data",
            {"overlappingDays": len(aligned_port), "minimumRequired": 60},
        )

    port_arr = np.array(aligned_port)
    factor_arr = np.array(aligned_factors)
    rf_arr = np.array(aligned_rf)

    # Excess returns: R_portfolio - R_f
    excess_returns = port_arr - rf_arr

    try:
        reg = run_factor_regression(
            excess_returns,
            factor_arr,
            start_date=dates[0],
            end_date=dates[-1],
        )
    except InsufficientDataError as e:
        return _null_response("insufficient_history", {"detail": str(e)})

    return _format_regression_response(
        reg,
        resolved_region,
        factor_data_through,
        lookback_days,
        drift_alerts=[],
    )


@router.get("/exposure/{security_id}")
async def get_security_factor_exposure(
    security_id: int,
    lookback_days: int = Query(756, alias="lookbackDays", ge=60, le=2520),
    region: str = Query("auto", regex="^(us|europe|auto)$"),
):
    """Per-security Fama-French 5-factor loadings."""
    # Look up security
    async with async_session() as session:
        sec = await session.get(Security, security_id)
    if not sec:
        return _null_response("security_not_found")

    # Resolve region
    if region == "auto":
        resolved_region = select_factor_region(sec.exchange, sec.asset_class)
    else:
        resolved_region = region

    # Get security returns
    returns_data = await _get_daily_returns([security_id], lookback_days)
    if security_id not in returns_data:
        return _null_response("no_price_data", {"securityId": security_id})

    dates, sec_returns = returns_data[security_id]
    if len(sec_returns) < 60:
        return _null_response(
            "insufficient_history",
            {
                "securityId": security_id,
                "tradingDaysAvailable": len(sec_returns),
                "minimumRequired": 60,
            },
        )

    # Get factor data
    factor_matrix, rf_array, factor_data_through = await _get_factor_returns(
        resolved_region, dates
    )
    if len(factor_matrix) < 60:
        return _null_response(
            "insufficient_factor_data",
            {"factorDaysAvailable": len(factor_matrix), "minimumRequired": 60},
        )

    # Align
    date_to_ret = dict(zip(dates, sec_returns))
    aligned_ret = []
    aligned_factors = []
    aligned_rf = []

    for i, d in enumerate(dates):
        if d in date_to_ret and i < len(factor_matrix):
            aligned_ret.append(date_to_ret[d])
            aligned_factors.append(factor_matrix[i])
            aligned_rf.append(rf_array[i])

    if len(aligned_ret) < 60:
        return _null_response("insufficient_overlapping_data")

    ret_arr = np.array(aligned_ret)
    factor_arr = np.array(aligned_factors)
    rf_arr = np.array(aligned_rf)
    excess_returns = ret_arr - rf_arr

    try:
        reg = run_factor_regression(
            excess_returns,
            factor_arr,
            start_date=dates[0],
            end_date=dates[-1],
        )
    except InsufficientDataError as e:
        return _null_response("insufficient_history", {"detail": str(e)})

    # Crypto warning
    warnings = []
    if sec.asset_class == "crypto" and reg.r_squared < 0.3:
        warnings.append(
            f"Fama-French factors explain only {reg.r_squared * 100:.0f}% of this "
            f"asset's return variance. Factor loadings may not be meaningful."
        )

    resp = _format_regression_response(
        reg,
        resolved_region,
        factor_data_through,
        lookback_days,
        security_id=security_id,
        ticker=sec.ticker,
    )
    if warnings:
        resp["data"]["warnings"] = warnings

    return resp


@router.get("/attribution")
async def get_factor_attribution(
    start_date: date | None = Query(None, alias="startDate"),
    end_date: date | None = Query(None, alias="endDate"),
    region: str = Query("auto", regex="^(us|europe|auto)$"),
):
    """Return attribution decomposed by Fama-French factor."""
    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=365)

    holdings = await _get_holdings_with_values()
    if not holdings:
        return _null_response("no_holdings")

    resolved_region = _resolve_region(region, holdings)

    # Compute portfolio returns for the attribution period
    lookback_days = (end_date - start_date).days
    dates, port_returns, n_sec = await _compute_portfolio_returns(
        holdings, lookback_days
    )
    if len(port_returns) < 60:
        return _null_response(
            "insufficient_history",
            {"tradingDaysAvailable": len(port_returns), "minimumRequired": 60},
        )

    # Get factor data
    factor_matrix, rf_array, factor_data_through = await _get_factor_returns(
        resolved_region, dates
    )
    if len(factor_matrix) < 60:
        return _null_response("insufficient_factor_data")

    # Align
    date_to_ret = dict(zip(dates, port_returns))
    aligned_port = []
    aligned_factors = []
    aligned_rf = []

    for i, d in enumerate(dates):
        if d in date_to_ret and i < len(factor_matrix):
            aligned_port.append(date_to_ret[d])
            aligned_factors.append(factor_matrix[i])
            aligned_rf.append(rf_array[i])

    if len(aligned_port) < 60:
        return _null_response("insufficient_overlapping_data")

    port_arr = np.array(aligned_port)
    factor_arr = np.array(aligned_factors)
    rf_arr = np.array(aligned_rf)
    excess_returns = port_arr - rf_arr

    try:
        reg = run_factor_regression(excess_returns, factor_arr)
    except InsufficientDataError as e:
        return _null_response("insufficient_history", {"detail": str(e)})

    attribution = compute_factor_attribution(excess_returns, factor_arr, reg)

    # Build response
    factor_contribs = {}
    total_factor_explained = 0.0
    for name in FACTOR_NAMES:
        contrib = attribution.factor_contributions[name]
        pct = attribution.factor_pct_of_return[name]
        factor_contribs[name] = {
            "return": round(contrib, 6),
            "pctOfTotal": round(pct, 4),
        }
        total_factor_explained += contrib

    abs_total = abs(attribution.total_excess_return) if attribution.total_excess_return != 0 else 1.0

    return {
        "data": {
            "totalExcessReturn": round(attribution.total_excess_return, 6),
            "alphaContribution": round(attribution.alpha_contribution, 6),
            "factorContributions": factor_contribs,
            "residual": round(attribution.residual, 6),
            "totalFactorExplained": round(total_factor_explained, 6),
            "totalFactorExplainedPct": round(
                total_factor_explained / abs_total, 4
            ),
        },
        "meta": {
            "calculatedAt": datetime.now(timezone.utc).isoformat(),
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "region": resolved_region,
            "factorDataThrough": factor_data_through.isoformat(),
        },
    }


@router.get("/style")
async def get_style_analysis(
    lookback_days: int = Query(756, alias="lookbackDays", ge=60, le=2520),
):
    """Sharpe style analysis — constrained regression to classify portfolio style."""
    holdings = await _get_holdings_with_values()
    if not holdings:
        return _null_response("no_holdings")

    region = _resolve_region("auto", holdings)

    dates, port_returns, n_sec = await _compute_portfolio_returns(
        holdings, lookback_days
    )
    if len(port_returns) < 60:
        return _null_response(
            "insufficient_history",
            {"tradingDaysAvailable": len(port_returns), "minimumRequired": 60},
        )

    factor_matrix, rf_array, factor_data_through = await _get_factor_returns(
        region, dates
    )
    if len(factor_matrix) < 60:
        return _null_response("insufficient_factor_data")

    # Align
    date_to_ret = dict(zip(dates, port_returns))
    aligned_port = []
    aligned_factors = []

    for i, d in enumerate(dates):
        if d in date_to_ret and i < len(factor_matrix):
            aligned_port.append(date_to_ret[d])
            aligned_factors.append(factor_matrix[i])

    if len(aligned_port) < 60:
        return _null_response("insufficient_overlapping_data")

    port_arr = np.array(aligned_port)
    factor_arr = np.array(aligned_factors)

    try:
        result = style_analysis(port_arr, factor_arr)
    except InsufficientDataError as e:
        return _null_response("insufficient_history", {"detail": str(e)})
    except OptimizationError as e:
        return _null_response("optimization_failed", {"detail": str(e)})

    # Compute additional style metrics
    equity_value = result.weights.get("hml", 0) + result.weights.get("rmw", 0)
    equity_growth = result.weights.get("mkt", 0) + result.weights.get("cma", 0)
    total_equity = sum(result.weights.values())
    value_tilt = equity_value / total_equity if total_equity > 0 else 0.5
    size_tilt = result.weights.get("smb", 0) / total_equity if total_equity > 0 else 0

    return {
        "data": {
            "styleLabel": result.style_label,
            "weights": {k: round(v, 4) for k, v in result.weights.items()},
            "rSquared": round(result.r_squared, 4),
            "nObservations": result.n_observations,
            "equityPct": round(total_equity, 4),
            "valueTilt": round(value_tilt, 4),
            "sizeTilt": round(size_tilt, 4),
        },
        "meta": {
            "calculatedAt": datetime.now(timezone.utc).isoformat(),
            "lookbackDays": lookback_days,
            "region": region,
            "factorDataThrough": factor_data_through.isoformat(),
        },
    }


@router.get("/rolling")
async def get_rolling_factor_exposure(
    window: int = Query(756, ge=60, le=2520),
    step: int = Query(21, ge=1, le=63),
    region: str = Query("auto", regex="^(us|europe|auto)$"),
):
    """Rolling factor exposure time series."""
    holdings = await _get_holdings_with_values()
    if not holdings:
        return _null_response("no_holdings")

    resolved_region = _resolve_region(region, holdings)

    # Need extra data for the rolling window
    total_days_needed = window + 1260  # window + ~5 years of stepping room
    dates, port_returns, n_sec = await _compute_portfolio_returns(
        holdings, total_days_needed
    )
    if len(port_returns) < window:
        return _null_response(
            "insufficient_history",
            {
                "tradingDaysAvailable": len(port_returns),
                "minimumRequired": window,
            },
        )

    factor_matrix, rf_array, factor_data_through = await _get_factor_returns(
        resolved_region, dates
    )
    if len(factor_matrix) < window:
        return _null_response(
            "insufficient_factor_data",
            {"factorDaysAvailable": len(factor_matrix), "minimumRequired": window},
        )

    # Align
    date_to_ret = dict(zip(dates, port_returns))
    aligned_dates: list[date] = []
    aligned_port: list[float] = []
    aligned_factors: list[list[float]] = []
    aligned_rf: list[float] = []

    for i, d in enumerate(dates):
        if d in date_to_ret and i < len(factor_matrix):
            aligned_dates.append(d)
            aligned_port.append(date_to_ret[d])
            aligned_factors.append(factor_matrix[i].tolist())
            aligned_rf.append(rf_array[i])

    if len(aligned_port) < window:
        return _null_response("insufficient_overlapping_data")

    port_arr = np.array(aligned_port)
    factor_arr = np.array(aligned_factors)
    rf_arr = np.array(aligned_rf)
    excess_returns = port_arr - rf_arr

    rolling_results = rolling_factor_exposure(
        excess_returns, factor_arr, aligned_dates, window=window, step=step
    )

    if not rolling_results:
        return _null_response("no_rolling_results")

    # Detect drift
    drift_alerts = detect_factor_drift(rolling_results)

    series = [
        {
            "date": rp.window_end_date.isoformat(),
            "alpha": round(rp.alpha, 6),
            "betas": {k: round(v, 4) for k, v in rp.betas.items()},
            "rSquared": round(rp.r_squared, 4),
        }
        for rp in rolling_results
    ]

    return {
        "data": {
            "series": series,
            "driftAlerts": [
                {
                    "factor": a.factor,
                    "factorLabel": a.factor_label,
                    "currentBeta": round(a.current_beta, 4),
                    "expectedRange": list(a.expected_range),
                    "direction": a.direction,
                    "severity": a.severity,
                    "message": a.message,
                }
                for a in drift_alerts
            ],
        },
        "meta": {
            "calculatedAt": datetime.now(timezone.utc).isoformat(),
            "window": window,
            "step": step,
            "nPoints": len(series),
            "region": resolved_region,
            "factorDataThrough": factor_data_through.isoformat(),
        },
    }
