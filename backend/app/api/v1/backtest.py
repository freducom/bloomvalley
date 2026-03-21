"""Backtesting endpoints — run, compare, what-if, and rolling analysis."""

from datetime import date, datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.backtester import (
    BacktestResult,
    StrategyConfig,
    compare_strategies,
    rolling_backtest,
    run_backtest,
)

logger = structlog.get_logger()

router = APIRouter()

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class StrategyRequest(BaseModel):
    """JSON body for a single strategy configuration."""

    name: str = "Custom Strategy"
    startDate: str = "2011-03-21"
    endDate: str = "2026-03-21"
    initialCapitalCents: int = 20_000_00  # 200 EUR default
    monthlyContributionCents: int = 0
    contributionGrowthRate: float = 0.0
    rebalanceFrequency: str = "quarterly"
    driftThresholdPct: float = 5.0
    allocation: dict[str, float] = Field(default_factory=dict)
    securityTickers: dict[str, list[str]] = Field(default_factory=dict)
    useGlidepath: bool = True
    birthDate: str = "1981-03-19"
    transactionCostPct: float = 0.001
    taxRate: float = 0.30
    reinvestDividends: bool = True


class CompareRequest(BaseModel):
    """JSON body for strategy comparison."""

    strategies: list[StrategyRequest]


# ---------------------------------------------------------------------------
# Default strategy
# ---------------------------------------------------------------------------

DEFAULT_SECURITY_TICKERS: dict[str, list[str]] = {
    "equity": ["IWDA.AS", "EUNL.DE"],
    "fixed_income": ["VGEA.DE"],
    "crypto": ["BTC-EUR"],
}

DEFAULT_ALLOCATION: dict[str, float] = {
    "equity": 0.75,
    "fixed_income": 0.15,
    "crypto": 0.07,
    "cash": 0.03,
}


def _to_strategy_config(req: StrategyRequest) -> StrategyConfig:
    """Convert a camelCase request model to a StrategyConfig dataclass."""
    tickers = req.securityTickers if req.securityTickers else DEFAULT_SECURITY_TICKERS
    allocation = req.allocation if req.allocation else DEFAULT_ALLOCATION

    return StrategyConfig(
        name=req.name,
        start_date=date.fromisoformat(req.startDate),
        end_date=date.fromisoformat(req.endDate),
        initial_capital_cents=req.initialCapitalCents,
        monthly_contribution_cents=req.monthlyContributionCents,
        contribution_growth_rate=req.contributionGrowthRate,
        rebalance_frequency=req.rebalanceFrequency,
        drift_threshold_pct=req.driftThresholdPct,
        allocation=allocation,
        security_tickers=tickers,
        use_glidepath=req.useGlidepath,
        birth_date=date.fromisoformat(req.birthDate),
        transaction_cost_pct=req.transactionCostPct,
        tax_rate=req.taxRate,
        reinvest_dividends=req.reinvestDividends,
    )


def _format_result(result: BacktestResult, config_name: str) -> dict:
    """Format a BacktestResult into a camelCase JSON response."""
    return {
        "name": config_name,
        "metrics": result.metrics,
        "equityCurve": result.daily_values,
        "annualReturns": result.annual_returns,
        "summary": {
            "taxPaidCents": result.tax_paid_cents,
            "dividendsReceivedCents": result.dividends_received_cents,
            "transactionCostsCents": result.transaction_costs_cents,
            "totalTrades": len(result.trades),
        },
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/run")
async def run_single_backtest(body: StrategyRequest):
    """Run a single backtest with the given strategy configuration."""
    try:
        config = _to_strategy_config(body)
        result = await run_backtest(config)
        return {
            "data": _format_result(result, config.name),
            "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("backtest.run.error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Backtest failed: {exc}")


@router.post("/compare")
async def compare_backtest_strategies(body: CompareRequest):
    """Compare multiple strategies side-by-side."""
    if len(body.strategies) < 2:
        raise HTTPException(status_code=400, detail="At least 2 strategies required")
    if len(body.strategies) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 strategies")

    try:
        configs = [_to_strategy_config(s) for s in body.strategies]
        result = await compare_strategies(configs)

        strategies_out = []
        for s in result.strategies:
            strategies_out.append({
                "name": s["name"],
                "metrics": s["metrics"],
                "equityCurve": s["equityCurve"],
                "annualReturns": s["annualReturns"],
                "summary": {
                    "taxPaidCents": s["taxPaidCents"],
                    "dividendsReceivedCents": s["dividendsReceivedCents"],
                    "transactionCostsCents": s["transactionCostsCents"],
                },
            })

        return {
            "data": {
                "strategies": strategies_out,
                "comparisonTable": result.comparison_table,
            },
            "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("backtest.compare.error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Comparison failed: {exc}")


@router.get("/what-if")
async def what_if_scenarios(
    scenario: str = Query(
        ...,
        description="Scenario: earlier_start, more_bonds, quarterly_rebalance, "
        "no_crypto, higher_contributions, no_glidepath",
    ),
):
    """Run predefined what-if scenarios comparing baseline vs alternative."""
    # Baseline: default Munger-Boglehead strategy
    baseline_req = StrategyRequest(
        name="Baseline",
        startDate="2011-03-21",
        endDate="2026-03-21",
        initialCapitalCents=2_000_000,  # 20,000 EUR
        monthlyContributionCents=50_000,  # 500 EUR/month
        rebalanceFrequency="quarterly",
        useGlidepath=True,
    )

    # Build alternative based on scenario
    alt_req = baseline_req.model_copy()
    alt_req.name = scenario

    if scenario == "earlier_start":
        alt_req.name = "Earlier Start (2006)"
        alt_req.startDate = "2006-03-21"
    elif scenario == "more_bonds":
        alt_req.name = "More Bonds (40% FI)"
        alt_req.useGlidepath = False
        alt_req.allocation = {
            "equity": 0.50,
            "fixed_income": 0.40,
            "crypto": 0.05,
            "cash": 0.05,
        }
    elif scenario == "quarterly_rebalance":
        alt_req.name = "Monthly Rebalance"
        alt_req.rebalanceFrequency = "monthly"
    elif scenario == "no_crypto":
        alt_req.name = "No Crypto"
        alt_req.useGlidepath = False
        alt_req.allocation = {
            "equity": 0.80,
            "fixed_income": 0.17,
            "crypto": 0.0,
            "cash": 0.03,
        }
        alt_req.securityTickers = {
            "equity": ["IWDA.AS", "EUNL.DE"],
            "fixed_income": ["VGEA.DE"],
        }
    elif scenario == "higher_contributions":
        alt_req.name = "Higher Contributions (1000 EUR/mo)"
        alt_req.monthlyContributionCents = 100_000  # 1000 EUR/month
    elif scenario == "no_glidepath":
        alt_req.name = "No Glidepath (Static 75/15/7/3)"
        alt_req.useGlidepath = False
        alt_req.allocation = DEFAULT_ALLOCATION
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown scenario: {scenario}. "
            f"Options: earlier_start, more_bonds, quarterly_rebalance, "
            f"no_crypto, higher_contributions, no_glidepath",
        )

    try:
        baseline_config = _to_strategy_config(baseline_req)
        alt_config = _to_strategy_config(alt_req)

        baseline_result = await run_backtest(baseline_config)
        alt_result = await run_backtest(alt_config)

        # Compute differences
        diff_metrics: dict[str, float] = {}
        for key in baseline_result.metrics:
            bv = baseline_result.metrics.get(key)
            av = alt_result.metrics.get(key)
            if isinstance(bv, (int, float)) and isinstance(av, (int, float)):
                diff_metrics[key] = round(av - bv, 2)

        return {
            "data": {
                "baseline": _format_result(baseline_result, "Baseline"),
                "alternative": _format_result(alt_result, alt_req.name),
                "difference": diff_metrics,
            },
            "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("backtest.whatif.error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail=f"What-if analysis failed: {exc}")


@router.get("/rolling")
async def rolling_window_analysis(
    windowYears: int = Query(10, ge=1, le=30, description="Rolling window size in years"),
    stepMonths: int = Query(1, ge=1, le=12, description="Step size in months"),
):
    """Rolling window backtest — slide a fixed window across all history."""
    # Use default strategy
    config = StrategyConfig(
        name="Rolling Analysis",
        start_date=date(2006, 1, 1),
        end_date=date(2026, 3, 21),
        initial_capital_cents=2_000_000,
        monthly_contribution_cents=50_000,
        rebalance_frequency="quarterly",
        allocation=DEFAULT_ALLOCATION,
        security_tickers=DEFAULT_SECURITY_TICKERS,
        use_glidepath=True,
        birth_date=date(1981, 3, 19),
    )

    try:
        result = await rolling_backtest(config, windowYears, stepMonths)
        return {
            "data": {
                "distribution": result.distribution,
                "periods": result.periods,
            },
            "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("backtest.rolling.error", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Rolling analysis failed: {exc}")
