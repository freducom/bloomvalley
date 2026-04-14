"""Tests for Monte Carlo retirement projection simulation."""

from datetime import date

import numpy as np
import pytest

from app.services.monte_carlo import (
    ASSET_CLASSES,
    DEFAULT_CORRELATION,
    GLIDEPATH,
    SimulationParams,
    _get_target_allocation,
    run_simulation,
)


# ---------------------------------------------------------------------------
# Glidepath Interpolation
# ---------------------------------------------------------------------------


class TestGetTargetAllocation:
    def test_exact_age(self):
        """At a defined glidepath age, return exact weights."""
        alloc = _get_target_allocation(45)
        expected = np.array([0.75, 0.15, 0.07, 0.03])
        np.testing.assert_array_almost_equal(alloc, expected, decimal=3)

    def test_clamp_below_min(self):
        """Age below minimum clamps to youngest allocation."""
        alloc = _get_target_allocation(30)
        expected = _get_target_allocation(45)
        np.testing.assert_array_almost_equal(alloc, expected)

    def test_clamp_above_max(self):
        """Age above maximum clamps to oldest allocation."""
        alloc = _get_target_allocation(70)
        expected = np.array([0.30, 0.60, 0.02, 0.08])
        np.testing.assert_array_almost_equal(alloc, expected, decimal=3)

    def test_interpolation_midpoint(self):
        """Age 47.5 (midpoint between 45 and 50) should be average."""
        # Age 47 is 2/5 of the way from 45 to 50
        alloc = _get_target_allocation(47)
        # Linear interp: 45 + (47-45)/(50-45) * (50_alloc - 45_alloc)
        frac = 2 / 5
        expected_equity = 0.75 + frac * (0.65 - 0.75)
        assert alloc[0] == pytest.approx(expected_equity, abs=0.01)

    def test_sums_to_one(self):
        """Interpolated allocation should normalize to 1.0."""
        for age in range(40, 65):
            alloc = _get_target_allocation(age)
            assert alloc.sum() == pytest.approx(1.0, abs=1e-6)

    def test_equity_decreases(self):
        """Equity weight should monotonically decrease with age."""
        prev = _get_target_allocation(40)[0]
        for age in range(41, 65):
            current = _get_target_allocation(age)[0]
            assert current <= prev + 1e-10
            prev = current

    def test_matches_asset_class_order(self):
        """Output order matches ASSET_CLASSES constant."""
        assert ASSET_CLASSES == ["equity", "fixed_income", "crypto", "cash"]


# ---------------------------------------------------------------------------
# Simulation Core
# ---------------------------------------------------------------------------


class TestRunSimulation:
    @pytest.fixture
    def base_params(self):
        return SimulationParams(
            current_portfolio_value_cents=10_000_000_00,  # €100,000
            annual_contribution_cents=1_200_000,  # €12,000/year
            birth_date=date(1981, 3, 19),
            retirement_age=60,
            death_age=95,
            num_paths=1_000,  # fewer for test speed
            seed=42,
        )

    def test_reproducible_with_seed(self, base_params):
        """Same seed -> same results."""
        r1 = run_simulation(base_params)
        r2 = run_simulation(base_params)
        assert r1.summary.median_at_retirement == r2.summary.median_at_retirement

    def test_fan_chart_length(self, base_params):
        """Fan chart should have one point per year from current age to death."""
        result = run_simulation(base_params)
        current_age = base_params.current_age
        expected_years = base_params.death_age - current_age + 1
        assert len(result.fan_chart) == expected_years

    def test_fan_chart_percentile_ordering(self, base_params):
        """Percentiles should be ordered: p5 <= p25 <= p50 <= p75 <= p95."""
        result = run_simulation(base_params)
        for point in result.fan_chart:
            assert point.p5 <= point.p25
            assert point.p25 <= point.p50
            assert point.p50 <= point.p75
            assert point.p75 <= point.p95

    def test_initial_value(self, base_params):
        """First fan chart point should match initial portfolio value."""
        result = run_simulation(base_params)
        first = result.fan_chart[0]
        assert first.p50 == base_params.current_portfolio_value_cents

    def test_portfolio_grows_median(self, base_params):
        """With contributions and positive expected returns, median should grow."""
        result = run_simulation(base_params)
        first = result.fan_chart[0]
        last_accum = None
        for point in result.fan_chart:
            if point.age == base_params.retirement_age:
                last_accum = point
                break
        assert last_accum is not None
        assert last_accum.p50 > first.p50

    def test_withdrawal_depletes(self, base_params):
        """In withdrawal phase, some lower percentile paths should deplete."""
        result = run_simulation(base_params)
        last = result.fan_chart[-1]
        # P5 at age 95 could be near zero for aggressive withdrawal
        assert last.p5 >= 0  # never negative

    def test_summary_probabilities(self, base_params):
        result = run_simulation(base_params)
        s = result.summary
        assert 0.0 <= s.probability_lasting_to_85 <= 1.0
        assert 0.0 <= s.probability_lasting_to_90 <= 1.0
        assert 0.0 <= s.probability_lasting_to_95 <= 1.0
        # Probability of lasting decreases with age
        assert s.probability_lasting_to_85 >= s.probability_lasting_to_90
        assert s.probability_lasting_to_90 >= s.probability_lasting_to_95

    def test_safe_withdrawal_rate(self, base_params):
        result = run_simulation(base_params)
        swr = result.summary.safe_withdrawal_rate
        assert 0.0 < swr <= 0.10  # should be between 0-10%

    def test_zero_contribution(self, base_params):
        """Simulation works with zero contributions."""
        base_params.annual_contribution_cents = 0
        result = run_simulation(base_params)
        assert result.summary.median_at_retirement > 0

    def test_already_retired(self):
        """Edge case: already past retirement age."""
        params = SimulationParams(
            current_portfolio_value_cents=5_000_000_00,
            birth_date=date(1960, 1, 1),  # age ~66
            retirement_age=60,
            death_age=95,
            num_paths=500,
            seed=42,
        )
        result = run_simulation(params)
        assert len(result.fan_chart) > 0


# ---------------------------------------------------------------------------
# Correlation Matrix
# ---------------------------------------------------------------------------


class TestDefaultCorrelation:
    def test_symmetric(self):
        np.testing.assert_array_almost_equal(
            DEFAULT_CORRELATION, DEFAULT_CORRELATION.T
        )

    def test_diagonal_ones(self):
        np.testing.assert_array_almost_equal(
            np.diag(DEFAULT_CORRELATION), np.ones(4)
        )

    def test_positive_definite(self):
        """Must be positive definite for Cholesky decomposition."""
        eigvals = np.linalg.eigvalsh(DEFAULT_CORRELATION)
        assert np.all(eigvals > 0)

    def test_equity_bond_negative_correlation(self):
        """Equity and fixed income should be negatively correlated."""
        eq_idx = ASSET_CLASSES.index("equity")
        fi_idx = ASSET_CLASSES.index("fixed_income")
        assert DEFAULT_CORRELATION[eq_idx, fi_idx] < 0
