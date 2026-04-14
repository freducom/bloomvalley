"""Tests for portfolio optimization math — covariance, returns, efficient frontier."""

import numpy as np
import pytest

from app.services.optimizer import (
    GLIDEPATH,
    LAMBDA_MAP,
    TRADING_DAYS_PER_YEAR,
    _build_constraints,
    _initial_weights,
    compute_efficient_frontier,
    equilibrium_returns,
    expected_returns_historical,
    find_optimal_portfolio,
    ledoit_wolf_shrinkage,
)


# ---------------------------------------------------------------------------
# Ledoit-Wolf Shrinkage
# ---------------------------------------------------------------------------


class TestLedoitWolfShrinkage:
    def test_returns_annualized(self):
        """Output should be annualized (multiplied by 252)."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0.0005, 0.01, (100, 3))
        cov = ledoit_wolf_shrinkage(returns)
        sample_daily = np.cov(returns, rowvar=False, ddof=1)
        # Annualized cov should be roughly 252x the daily cov
        ratio = cov[0, 0] / sample_daily[0, 0]
        assert ratio == pytest.approx(TRADING_DAYS_PER_YEAR, rel=0.3)

    def test_symmetric(self):
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.01, (100, 4))
        cov = ledoit_wolf_shrinkage(returns)
        np.testing.assert_array_almost_equal(cov, cov.T)

    def test_positive_semidefinite(self):
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.01, (100, 3))
        cov = ledoit_wolf_shrinkage(returns)
        eigvals = np.linalg.eigvalsh(cov)
        assert np.all(eigvals >= -1e-10)

    def test_single_asset(self):
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.01, (50, 1))
        cov = ledoit_wolf_shrinkage(returns)
        # np.cov with 1 asset returns a scalar; verify it's a positive number
        assert float(cov) > 0

    def test_insufficient_data(self):
        with pytest.raises(ValueError, match="Insufficient data"):
            ledoit_wolf_shrinkage(np.array([[0.01]]))  # 1 day, 1 asset


# ---------------------------------------------------------------------------
# Expected Returns
# ---------------------------------------------------------------------------


class TestExpectedReturns:
    def test_annualized(self):
        """Mean daily return * 252."""
        returns = np.array([[0.001, 0.002], [0.003, 0.004], [0.002, 0.001]])
        result = expected_returns_historical(returns)
        expected = np.mean(returns, axis=0) * TRADING_DAYS_PER_YEAR
        np.testing.assert_array_almost_equal(result, expected)

    def test_shape(self):
        returns = np.random.randn(100, 5)
        result = expected_returns_historical(returns)
        assert result.shape == (5,)


# ---------------------------------------------------------------------------
# Equilibrium Returns (Black-Litterman prior)
# ---------------------------------------------------------------------------


class TestEquilibriumReturns:
    def test_formula(self):
        """pi = delta * Sigma * w_mkt"""
        cov = np.array([[0.04, 0.01], [0.01, 0.02]])
        weights = np.array([0.6, 0.4])
        delta = 2.5
        result = equilibrium_returns(cov, weights, delta)
        expected = delta * cov @ weights
        np.testing.assert_array_almost_equal(result, expected)


# ---------------------------------------------------------------------------
# Initial Weights
# ---------------------------------------------------------------------------


class TestInitialWeights:
    def test_sums_to_one(self):
        bounds = [(0.0, 0.5)] * 4
        w = _initial_weights(4, bounds)
        assert w.sum() == pytest.approx(1.0)

    def test_respects_upper_bounds(self):
        bounds = [(0.0, 0.3)] * 4
        w = _initial_weights(4, bounds)
        assert np.all(w <= 0.301)  # small tolerance

    def test_equal_weight_when_feasible(self):
        bounds = [(0.0, 1.0)] * 3
        w = _initial_weights(3, bounds)
        np.testing.assert_array_almost_equal(w, [1/3, 1/3, 1/3])


# ---------------------------------------------------------------------------
# Build Constraints
# ---------------------------------------------------------------------------


class TestBuildConstraints:
    def test_sum_to_one(self):
        constraints = _build_constraints(3, {}, {}, {})
        w = np.array([0.3, 0.3, 0.4])
        # First constraint is sum-to-one
        assert constraints[0]["fun"](w) == pytest.approx(0.0)

    def test_class_bounds(self):
        constraints = _build_constraints(
            4,
            class_membership={"equity": [0, 1], "bond": [2, 3]},
            class_lower_bounds={"equity": 0.4, "bond": 0.2},
            class_upper_bounds={"equity": 0.8, "bond": 0.6},
        )
        # Should have: 1 (sum) + 2*2 (lower+upper for 2 classes) = 5 constraints
        assert len(constraints) == 5


# ---------------------------------------------------------------------------
# Efficient Frontier
# ---------------------------------------------------------------------------


class TestEfficientFrontier:
    @pytest.fixture
    def simple_inputs(self):
        """3-asset problem with known properties."""
        mu = np.array([0.08, 0.05, 0.12])
        cov = np.array([
            [0.04, 0.005, 0.01],
            [0.005, 0.01, 0.003],
            [0.01, 0.003, 0.09],
        ])
        bounds = np.array([1.0, 1.0, 1.0])
        return mu, cov, bounds

    def test_returns_points(self, simple_inputs):
        mu, cov, bounds = simple_inputs
        result = compute_efficient_frontier(
            mu, cov, 0.03, bounds, {}, {}, {}, n_points=10,
        )
        assert len(result.points) > 0

    def test_min_variance_lower_return(self, simple_inputs):
        mu, cov, bounds = simple_inputs
        result = compute_efficient_frontier(
            mu, cov, 0.03, bounds, {}, {}, {}, n_points=10,
        )
        if result.min_variance_portfolio and result.tangent_portfolio:
            assert result.min_variance_portfolio.volatility <= result.tangent_portfolio.volatility + 0.01

    def test_no_assets_raises(self):
        with pytest.raises(ValueError, match="No assets"):
            compute_efficient_frontier(
                np.array([]), np.array([]).reshape(0, 0), 0.03,
                np.array([]), {}, {}, {},
            )

    def test_weights_sum_to_one(self, simple_inputs):
        mu, cov, bounds = simple_inputs
        result = compute_efficient_frontier(
            mu, cov, 0.03, bounds, {}, {}, {}, n_points=5,
        )
        for point in result.points:
            assert point.weights.sum() == pytest.approx(1.0, abs=0.01)


# ---------------------------------------------------------------------------
# Optimal Portfolio
# ---------------------------------------------------------------------------


class TestOptimalPortfolio:
    def test_risk_tolerance_affects_allocation(self):
        """Higher risk_tolerance number = higher lambda = more risk aversion = lower volatility."""
        mu = np.array([0.06, 0.12])
        cov = np.array([[0.01, 0.002], [0.002, 0.04]])
        bounds = np.array([1.0, 1.0])
        tickers = ["BOND_ETF", "STOCK_ETF"]

        risk_seeking = find_optimal_portfolio(
            mu, cov, 0.03, 1, bounds, {}, {}, {}, tickers,
        )
        risk_averse = find_optimal_portfolio(
            mu, cov, 0.03, 10, bounds, {}, {}, {}, tickers,
        )
        # Higher risk_tolerance (lambda) = more conservative = lower volatility
        assert risk_averse.volatility <= risk_seeking.volatility + 0.001


# ---------------------------------------------------------------------------
# Glidepath Constants
# ---------------------------------------------------------------------------


class TestGlidepathConstants:
    def test_allocations_sum_to_one(self):
        for age, alloc in GLIDEPATH.items():
            total = sum(alloc.values())
            assert total == pytest.approx(1.0), f"Age {age} sums to {total}"

    def test_equity_decreases_with_age(self):
        ages = sorted(GLIDEPATH.keys())
        for i in range(len(ages) - 1):
            assert GLIDEPATH[ages[i]]["equity"] >= GLIDEPATH[ages[i + 1]]["equity"]

    def test_fixed_income_increases_with_age(self):
        ages = sorted(GLIDEPATH.keys())
        for i in range(len(ages) - 1):
            assert GLIDEPATH[ages[i]]["fixed_income"] <= GLIDEPATH[ages[i + 1]]["fixed_income"]


class TestLambdaMap:
    def test_monotonic_increasing(self):
        for i in range(1, 10):
            assert LAMBDA_MAP[i] < LAMBDA_MAP[i + 1]

    def test_all_positive(self):
        for v in LAMBDA_MAP.values():
            assert v > 0
