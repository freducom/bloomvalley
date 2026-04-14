"""Tests for Finnish capital gains tax calculations.

Finnish tax rules:
- OST (osakesäästötili): 0% tax
- 30% on gains up to €30,000/year
- 34% on gains above €30,000/year
- Deemed cost of acquisition: 20% of proceeds (<10yr), 40% (>=10yr)
- Deemed cost only used if it reduces taxable gain
"""

import pytest

from app.services.rebalancer import TaxImpact, _compute_finnish_tax


class TestOSTExemption:
    """OST (osakesäästötili) accounts pay no tax."""

    def test_ost_zero_tax(self):
        result = _compute_finnish_tax(
            gain_cents=500_000,  # €5,000 gain
            proceeds_cents=1_000_000,
            holding_years=3.0,
            ytd_realized_gains_cents=0,
            is_ost=True,
        )
        assert result.estimated_tax_cents == 0
        assert result.realized_gain_cents == 0
        assert result.is_osakesaastotili is True
        assert result.tax_rate == 0.0

    def test_ost_large_gain(self):
        result = _compute_finnish_tax(
            gain_cents=10_000_000,  # €100,000 gain
            proceeds_cents=20_000_000,
            holding_years=15.0,
            ytd_realized_gains_cents=5_000_000,
            is_ost=True,
        )
        assert result.estimated_tax_cents == 0
        assert result.is_osakesaastotili is True


class TestStandardRate:
    """30% rate for gains up to €30,000/year."""

    def test_small_gain_30_pct(self):
        result = _compute_finnish_tax(
            gain_cents=100_000,  # €1,000 gain
            proceeds_cents=200_000,
            holding_years=2.0,
            ytd_realized_gains_cents=0,
            is_ost=False,
        )
        assert result.estimated_tax_cents == 30_000  # €1,000 * 30% = €300
        assert result.tax_rate == 30.0

    def test_exactly_at_threshold(self):
        """Gain of exactly €30,000 with no prior YTD gains -> all at 30%."""
        result = _compute_finnish_tax(
            gain_cents=3_000_000,  # €30,000
            proceeds_cents=6_000_000,
            holding_years=2.0,
            ytd_realized_gains_cents=0,
            is_ost=False,
        )
        assert result.estimated_tax_cents == 900_000  # €30,000 * 30% = €9,000
        assert result.tax_rate == 30.0


class TestHighRate:
    """34% rate for gains above €30,000/year."""

    def test_all_at_34_pct(self):
        """YTD gains already exceed €30k -> this gain is entirely at 34%."""
        result = _compute_finnish_tax(
            gain_cents=500_000,  # €5,000 gain
            proceeds_cents=1_000_000,
            holding_years=2.0,
            ytd_realized_gains_cents=4_000_000,  # €40k already realized
            is_ost=False,
        )
        assert result.estimated_tax_cents == 170_000  # €5,000 * 34% = €1,700
        assert result.tax_rate == pytest.approx(34.0)


class TestSplitBracket:
    """Gains that cross the €30,000 threshold are split between 30% and 34%."""

    def test_crosses_threshold(self):
        """YTD = €25k, new gain = €10k -> €5k at 30%, €5k at 34%."""
        result = _compute_finnish_tax(
            gain_cents=1_000_000,  # €10,000
            proceeds_cents=2_000_000,
            holding_years=2.0,
            ytd_realized_gains_cents=2_500_000,  # €25,000
            is_ost=False,
        )
        # €5,000 at 30% = €1,500 + €5,000 at 34% = €1,700 = €3,200
        expected_tax = 150_000 + 170_000
        assert result.estimated_tax_cents == expected_tax
        # Blended rate: 3200/10000 = 32%
        assert result.tax_rate == pytest.approx(32.0)


class TestDeemedCost:
    """Deemed cost of acquisition (hankintameno-olettama)."""

    def test_deemed_20_pct_under_10_years(self):
        """Held <10 years: deemed cost = 20% of proceeds.
        If deemed cost is more favorable (lower gain), use it.
        """
        # Actual gain: €8,000. Deemed: proceeds €10,000 * 80% = €8,000 gain.
        # Not better. Let's use a case where deemed IS better:
        # Proceeds = €10,000, actual cost basis = €1,000, actual gain = €9,000
        # Deemed cost = 20% of €10,000 = €2,000, deemed gain = €8,000
        # Deemed gain (€8,000) < actual gain (€9,000) -> use deemed
        result = _compute_finnish_tax(
            gain_cents=900_000,  # €9,000 actual gain
            proceeds_cents=1_000_000,  # €10,000 proceeds
            holding_years=5.0,  # <10 years -> 20% deemed
            ytd_realized_gains_cents=0,
            is_ost=False,
        )
        assert result.used_deemed_cost is True
        # Deemed gain = €10,000 - €2,000 = €8,000
        assert result.realized_gain_cents == 800_000
        assert result.estimated_tax_cents == 240_000  # €8,000 * 30%

    def test_deemed_40_pct_over_10_years(self):
        """Held >=10 years: deemed cost = 40% of proceeds."""
        # Proceeds = €10,000, actual gain = €9,000
        # Deemed cost = 40% of €10,000 = €4,000, deemed gain = €6,000
        result = _compute_finnish_tax(
            gain_cents=900_000,
            proceeds_cents=1_000_000,
            holding_years=12.0,  # >=10 years -> 40% deemed
            ytd_realized_gains_cents=0,
            is_ost=False,
        )
        assert result.used_deemed_cost is True
        assert result.realized_gain_cents == 600_000  # €6,000
        assert result.estimated_tax_cents == 180_000  # €6,000 * 30%

    def test_deemed_not_used_when_actual_is_better(self):
        """Deemed cost not used when actual gain is already lower."""
        # Proceeds = €10,000, actual gain = €500 (bought at €9,500)
        # Deemed cost 20% -> deemed gain = €8,000 — worse than actual
        result = _compute_finnish_tax(
            gain_cents=50_000,  # €500 actual gain
            proceeds_cents=1_000_000,
            holding_years=3.0,
            ytd_realized_gains_cents=0,
            is_ost=False,
        )
        assert result.used_deemed_cost is False
        assert result.realized_gain_cents == 50_000
        assert result.estimated_tax_cents == 15_000  # €500 * 30%

    def test_deemed_exactly_10_years(self):
        """At exactly 10 years, use 40% deemed cost."""
        result = _compute_finnish_tax(
            gain_cents=900_000,
            proceeds_cents=1_000_000,
            holding_years=10.0,
            ytd_realized_gains_cents=0,
            is_ost=False,
        )
        assert result.used_deemed_cost is True
        assert result.realized_gain_cents == 600_000  # 40% deemed


class TestLossPositions:
    """Loss positions are not taxed."""

    def test_loss_no_tax(self):
        result = _compute_finnish_tax(
            gain_cents=-200_000,  # €2,000 loss
            proceeds_cents=800_000,
            holding_years=3.0,
            ytd_realized_gains_cents=0,
            is_ost=False,
        )
        assert result.estimated_tax_cents == 0
        assert result.tax_rate == 0.0

    def test_zero_gain(self):
        result = _compute_finnish_tax(
            gain_cents=0,
            proceeds_cents=1_000_000,
            holding_years=3.0,
            ytd_realized_gains_cents=0,
            is_ost=False,
        )
        assert result.estimated_tax_cents == 0


class TestEdgeCases:
    """Edge cases for tax calculation."""

    def test_ytd_exactly_at_threshold(self):
        """YTD = exactly €30,000. Next gain should be entirely at 34%."""
        result = _compute_finnish_tax(
            gain_cents=100_000,  # €1,000
            proceeds_cents=200_000,
            holding_years=2.0,
            ytd_realized_gains_cents=3_000_000,  # exactly €30,000
            is_ost=False,
        )
        assert result.estimated_tax_cents == 34_000  # €1,000 * 34%
        assert result.tax_rate == pytest.approx(34.0)

    def test_one_cent_gain(self):
        result = _compute_finnish_tax(
            gain_cents=1,
            proceeds_cents=100,
            holding_years=1.0,
            ytd_realized_gains_cents=0,
            is_ost=False,
        )
        assert result.estimated_tax_cents == 0  # int(1 * 0.30) = 0
