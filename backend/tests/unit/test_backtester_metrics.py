"""Tests for backtester performance metrics computation.

Tests compute_metrics() with known data series where expected values
can be verified by hand.
"""

import math
from datetime import date, timedelta

import numpy as np
import pytest

from app.services.backtester import compute_metrics


def _make_daily_values(start_date: date, values_cents: list[int]) -> list[dict]:
    """Build daily_values list from a sequence of portfolio values."""
    return [
        {"date": (start_date + timedelta(days=i)).isoformat(), "valueCents": v}
        for i, v in enumerate(values_cents)
    ]


class TestComputeMetricsBasic:
    def test_empty(self):
        result = compute_metrics([])
        assert result["totalReturnPct"] == 0.0
        assert result["tradingDays"] == 0

    def test_single_day(self):
        dv = _make_daily_values(date(2024, 1, 1), [100_000])
        result = compute_metrics(dv)
        assert result["totalReturnPct"] == 0.0
        assert result["tradingDays"] == 1

    def test_flat_series(self):
        """No change -> 0% return, 0 volatility."""
        values = [100_000] * 100
        dv = _make_daily_values(date(2024, 1, 1), values)
        result = compute_metrics(dv)
        assert result["totalReturnPct"] == 0.0
        assert result["sharpeRatio"] == 0.0
        assert result["maxDrawdownPct"] == 0.0


class TestTotalReturn:
    def test_double(self):
        """Portfolio doubles -> 100% return."""
        dv = _make_daily_values(date(2024, 1, 1), [100_000, 200_000])
        result = compute_metrics(dv)
        assert result["totalReturnPct"] == 100.0

    def test_loss(self):
        """Portfolio halves -> -50% return."""
        dv = _make_daily_values(date(2024, 1, 1), [100_000, 50_000])
        result = compute_metrics(dv)
        assert result["totalReturnPct"] == -50.0


class TestCAGR:
    def test_one_year_double(self):
        """100% return over ~1 year -> CAGR ≈ 100%."""
        start = date(2024, 1, 1)
        end = date(2025, 1, 1)
        days = (end - start).days
        values = [100_000] + [100_000] * (days - 1) + [200_000]
        dv = _make_daily_values(start, values)
        result = compute_metrics(dv)
        assert result["cagr"] == pytest.approx(100.0, rel=0.05)

    def test_two_year_compound(self):
        """Grow by 10% each year for 2 years."""
        start = date(2024, 1, 1)
        days = 365 * 2
        start_val = 100_000
        end_val = int(100_000 * 1.10 ** 2)
        # Linear interpolation (rough, but tests formula)
        values = [int(start_val + (end_val - start_val) * i / days) for i in range(days + 1)]
        dv = _make_daily_values(start, values)
        result = compute_metrics(dv)
        expected_cagr = (end_val / start_val) ** (1 / 2) - 1
        assert result["cagr"] == pytest.approx(expected_cagr * 100, rel=0.05)


class TestMaxDrawdown:
    def test_simple_drawdown(self):
        """Peak 200, trough 100 -> -50% drawdown."""
        values = [100_000, 200_000, 100_000, 150_000]
        dv = _make_daily_values(date(2024, 1, 1), values)
        result = compute_metrics(dv)
        assert result["maxDrawdownPct"] == pytest.approx(-50.0, abs=0.1)

    def test_no_drawdown(self):
        """Monotonically increasing -> 0% drawdown."""
        values = [100_000, 110_000, 120_000, 130_000]
        dv = _make_daily_values(date(2024, 1, 1), values)
        result = compute_metrics(dv)
        assert result["maxDrawdownPct"] == 0.0

    def test_drawdown_dates(self):
        values = [100_000, 200_000, 100_000, 150_000]
        dv = _make_daily_values(date(2024, 1, 1), values)
        result = compute_metrics(dv)
        assert result["maxDrawdownStart"] == date(2024, 1, 2).isoformat()
        assert result["maxDrawdownEnd"] == date(2024, 1, 3).isoformat()


class TestSharpeAndSortino:
    def test_positive_sharpe_for_uptrend(self):
        """Steadily increasing portfolio should have positive Sharpe."""
        rng = np.random.default_rng(42)
        # Strong upward trend with noise
        values = [100_000]
        for _ in range(251):
            daily_return = 1.001 + rng.normal(0, 0.003)
            values.append(int(values[-1] * max(daily_return, 0.9)))
        dv = _make_daily_values(date(2024, 1, 1), values)
        result = compute_metrics(dv)
        assert result["sharpeRatio"] > 0

    def test_sortino_ignores_upside(self):
        """Sortino uses only downside deviation, so should differ from Sharpe."""
        rng = np.random.default_rng(42)
        values = [100_000]
        for _ in range(251):
            values.append(int(values[-1] * (1 + rng.normal(0.0004, 0.01))))
        dv = _make_daily_values(date(2024, 1, 1), values)
        result = compute_metrics(dv)
        # Sortino should generally be >= Sharpe when there's positive trend
        # (since it penalizes only downside)
        assert result["sortinoRatio"] >= result["sharpeRatio"] - 0.5


class TestWinRate:
    def test_all_up_days(self):
        values = [100_000 + i * 100 for i in range(100)]
        dv = _make_daily_values(date(2024, 1, 1), values)
        result = compute_metrics(dv)
        assert result["winRate"] == 100.0

    def test_all_down_days(self):
        values = [100_000 - i * 100 for i in range(100)]
        dv = _make_daily_values(date(2024, 1, 1), values)
        result = compute_metrics(dv)
        assert result["winRate"] == 0.0


class TestCalmarRatio:
    def test_positive_calmar(self):
        """Calmar = |CAGR / maxDrawdown|."""
        values = [100_000, 200_000, 150_000, 180_000]
        dv = _make_daily_values(date(2024, 1, 1), values)
        result = compute_metrics(dv)
        if result["maxDrawdownPct"] != 0:
            expected = abs(result["cagr"] / result["maxDrawdownPct"])
            assert result["calmarRatio"] == pytest.approx(expected, rel=0.01)
