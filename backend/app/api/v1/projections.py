"""Projection endpoints — Monte Carlo retirement simulation and sensitivity analysis."""

from datetime import date, datetime, timezone

import structlog
from fastapi import APIRouter, Query

from app.db.engine import async_session
from app.services.monte_carlo import (
    SimulationParams,
    run_simulation,
    run_sensitivity,
    estimate_safe_withdrawal_rate,
    DEFAULT_RETURNS,
    DEFAULT_VOLATILITIES,
    DEFAULT_CORRELATION,
    SENSITIVITY_CONFIG,
    OUTPUT_METRICS,
)

logger = structlog.get_logger()

router = APIRouter()


async def _get_portfolio_value_cents() -> int:
    """Get current total portfolio value in EUR cents from holdings."""
    from app.api.v1.portfolio import get_holdings
    resp = await get_holdings(account_id=None)
    holdings = resp["data"]
    if not holdings:
        return 0
    return sum(h["marketValueEurCents"] or 0 for h in holdings)


@router.get("/monte-carlo")
async def get_monte_carlo_projection(
    annual_contribution: int = Query(0, alias="annualContribution", description="Annual contribution in EUR cents"),
    contribution_growth: float = Query(0.0, alias="contributionGrowth", description="Annual % increase in contributions"),
    withdrawal_rate: float = Query(0.04, alias="withdrawalRate", description="Annual withdrawal rate (e.g. 0.04 for 4%)"),
    retirement_age: int = Query(60, alias="retirementAge", description="Target retirement age"),
    num_paths: int = Query(10_000, alias="numPaths", description="Number of simulation paths"),
    seed: int | None = Query(None, description="Random seed for reproducibility"),
):
    """Monte Carlo retirement projection.

    Runs a GBM simulation with correlated asset classes, glidepath rebalancing,
    tax drag, and inflation-adjusted withdrawals. Returns fan chart data
    (percentile bands per year) and summary metrics.
    """
    logger.info(
        "projections.monte_carlo.request",
        annual_contribution=annual_contribution,
        withdrawal_rate=withdrawal_rate,
        retirement_age=retirement_age,
        num_paths=num_paths,
    )

    # Fetch current portfolio value from database
    portfolio_value_cents = await _get_portfolio_value_cents()
    logger.info("projections.monte_carlo.portfolio_value", value_cents=portfolio_value_cents)

    params = SimulationParams(
        current_portfolio_value_cents=portfolio_value_cents,
        annual_contribution_cents=annual_contribution,
        contribution_growth_rate=contribution_growth,
        birth_date=date(1981, 3, 19),
        retirement_age=retirement_age,
        death_age=95,
        expected_returns=dict(DEFAULT_RETURNS),
        volatilities=dict(DEFAULT_VOLATILITIES),
        correlation_matrix=DEFAULT_CORRELATION.copy(),
        tax_drag=0.003,
        inflation_rate=0.02,
        withdrawal_rate=withdrawal_rate,
        num_paths=num_paths,
        seed=seed,
    )

    # Run simulation (CPU-bound, but vectorized NumPy — typically <3s)
    result = run_simulation(params)

    # Build camelCase response
    fan_chart = [
        {
            "age": point.age,
            "year": point.year,
            "p5": point.p5,
            "p25": point.p25,
            "p50": point.p50,
            "p75": point.p75,
            "p95": point.p95,
        }
        for point in result.fan_chart
    ]

    summary = {
        "medianAtRetirement": result.summary.median_at_retirement,
        "meanAtRetirement": result.summary.mean_at_retirement,
        "p5AtRetirement": result.summary.p5_at_retirement,
        "p25AtRetirement": result.summary.p25_at_retirement,
        "p75AtRetirement": result.summary.p75_at_retirement,
        "p95AtRetirement": result.summary.p95_at_retirement,
        "probabilityOfTarget": result.summary.probability_of_target,
        "targetValue": result.summary.target_value,
        "safeWithdrawalRate": result.summary.safe_withdrawal_rate,
        "probabilityLastingTo85": result.summary.probability_lasting_to_85,
        "probabilityLastingTo90": result.summary.probability_lasting_to_90,
        "probabilityLastingTo95": result.summary.probability_lasting_to_95,
    }

    return {
        "params": {
            "currentPortfolioValue": portfolio_value_cents,
            "annualContribution": annual_contribution,
            "contributionGrowth": contribution_growth,
            "retirementAge": retirement_age,
            "withdrawalRate": withdrawal_rate,
            "numPaths": num_paths,
            "expectedReturns": {
                "equities": params.expected_returns["equity"],
                "fixedIncome": params.expected_returns["fixed_income"],
                "crypto": params.expected_returns["crypto"],
                "cash": params.expected_returns["cash"],
            },
        },
        "fanChart": fan_chart,
        "summary": summary,
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("/sensitivity")
async def get_sensitivity_analysis(
    variable: str = Query(..., description="Variable to vary: equityReturn, annualContribution, retirementAge, withdrawalRate, cryptoAllocation"),
    output_metric: str = Query("medianAtRetirement", alias="outputMetric", description="Output metric to measure"),
):
    """Sensitivity analysis — vary one parameter and measure effect on an output metric.

    Runs multiple reduced simulations (2,000 paths each) to show how changing
    one input affects the selected output.
    """
    # Validate inputs
    if variable not in SENSITIVITY_CONFIG:
        valid = ", ".join(SENSITIVITY_CONFIG.keys())
        return {
            "error": f"Unknown variable '{variable}'. Valid options: {valid}",
        }
    if output_metric not in OUTPUT_METRICS:
        valid = ", ".join(OUTPUT_METRICS.keys())
        return {
            "error": f"Unknown outputMetric '{output_metric}'. Valid options: {valid}",
        }

    logger.info(
        "projections.sensitivity.request",
        variable=variable, output_metric=output_metric,
    )

    # Get current portfolio value
    portfolio_value_cents = await _get_portfolio_value_cents()

    params = SimulationParams(
        current_portfolio_value_cents=portfolio_value_cents,
        annual_contribution_cents=2_400_000,  # 24,000 EUR default
        contribution_growth_rate=0.02,
        birth_date=date(1981, 3, 19),
        retirement_age=60,
        death_age=95,
        expected_returns=dict(DEFAULT_RETURNS),
        volatilities=dict(DEFAULT_VOLATILITIES),
        correlation_matrix=DEFAULT_CORRELATION.copy(),
        tax_drag=0.003,
        inflation_rate=0.02,
        withdrawal_rate=0.04,
        num_paths=2_000,
        seed=42,  # Fixed seed for reproducible sensitivity results
    )

    # Get baseline value
    baseline_input = SENSITIVITY_CONFIG[variable]["baseline_get"](params)
    baseline_result = run_simulation(params)
    baseline_output = OUTPUT_METRICS[output_metric](baseline_result)

    # Run sensitivity
    data_points = run_sensitivity(params, variable, output_metric)

    return {
        "variable": variable,
        "outputMetric": output_metric,
        "baseline": {
            "inputValue": baseline_input,
            "outputValue": baseline_output,
        },
        "dataPoints": data_points,
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }
