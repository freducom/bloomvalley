"""Tests for DCF valuation and ROIC computation.

Functions under test are in app.pipelines.yahoo_fundamentals.
The DCF logic is embedded in the pipeline class method, so we extract
and test the pure math separately.
"""

import pytest

from app.pipelines.yahoo_fundamentals import (
    DEFAULT_TAX_RATE,
    _compute_roic,
    _get_financial_debt,
    _safe_get,
)


# ---------------------------------------------------------------------------
# _safe_get
# ---------------------------------------------------------------------------


class TestSafeGet:
    def test_present(self):
        assert _safe_get({"ebit": 1000}, "ebit") == 1000

    def test_missing(self):
        assert _safe_get({}, "ebit") is None

    def test_none(self):
        assert _safe_get({"ebit": None}, "ebit") is None

    def test_na_string(self):
        assert _safe_get({"ebit": "N/A"}, "ebit") is None

    def test_default(self):
        assert _safe_get({}, "ebit", 42) == 42


# ---------------------------------------------------------------------------
# _get_financial_debt
# ---------------------------------------------------------------------------


class TestGetFinancialDebt:
    def test_no_debt(self):
        assert _get_financial_debt({}) is None

    def test_total_debt_only(self):
        assert _get_financial_debt({"totalDebt": 1_000_000}) == 1_000_000

    def test_excludes_lease_obligations(self):
        info = {"totalDebt": 1_000_000, "capitalLeaseObligations": 200_000}
        assert _get_financial_debt(info) == 800_000

    def test_balance_sheet_leases_preferred(self):
        info = {
            "totalDebt": 1_000_000,
            "bs_capital_lease_obligations": 300_000,
            "capitalLeaseObligations": 200_000,
        }
        # bs_ field takes precedence
        assert _get_financial_debt(info) == 700_000

    def test_negative_fallback(self):
        """If lease > debt (data quirk), fall back to totalDebt."""
        info = {"totalDebt": 100_000, "capitalLeaseObligations": 200_000}
        assert _get_financial_debt(info) == 100_000


# ---------------------------------------------------------------------------
# _compute_roic
# ---------------------------------------------------------------------------


class TestComputeROIC:
    def test_primary_formula(self):
        """ROIC = EBIT * (1 - tax_rate) / (financial_debt + equity - cash)"""
        info = {
            "ebit": 1_000_000,
            "stockholdersEquity": 3_000_000,
            "totalDebt": 2_000_000,
            "totalCash": 500_000,
        }
        # invested_capital = 2_000_000 + 3_000_000 - 500_000 = 4_500_000
        # NOPAT = 1_000_000 * (1 - 0.20) = 800_000
        # ROIC = 800_000 / 4_500_000 ≈ 0.1778
        result = _compute_roic(info)
        assert result == pytest.approx(800_000 / 4_500_000, rel=1e-4)

    def test_no_cash(self):
        """Missing cash treated as 0."""
        info = {
            "ebit": 500_000,
            "stockholdersEquity": 2_000_000,
            "totalDebt": 1_000_000,
        }
        # invested_capital = 1_000_000 + 2_000_000 - 0 = 3_000_000
        # NOPAT = 500_000 * 0.80 = 400_000
        result = _compute_roic(info)
        assert result == pytest.approx(400_000 / 3_000_000, rel=1e-4)

    def test_fallback_to_roe(self):
        info = {"returnOnEquity": 0.15}
        assert _compute_roic(info) == 0.15

    def test_fallback_to_roa(self):
        info = {"returnOnAssets": 0.08}
        assert _compute_roic(info) == 0.08

    def test_no_data(self):
        assert _compute_roic({}) is None

    def test_zero_invested_capital(self):
        """If invested capital = 0, skip to fallback."""
        info = {
            "ebit": 100_000,
            "stockholdersEquity": 500_000,
            "totalDebt": 0,
            "totalCash": 500_000,
            "returnOnEquity": 0.12,
        }
        # invested_capital = 0 + 500_000 - 500_000 = 0 -> skip
        # Falls back to ROE
        assert _compute_roic(info) == 0.12


# ---------------------------------------------------------------------------
# DCF pure math (extracted from _compute_dcf_valuations)
# ---------------------------------------------------------------------------


def compute_dcf(
    fcf_cents: int,
    roic: float | None,
    wacc: float | None,
    terminal_growth: float = 0.025,
) -> dict:
    """Extract of the DCF logic from YahooFundamentals._compute_dcf_valuations."""
    # Growth rate by ROIC tier
    if roic is not None:
        if roic > 0.20:
            growth_rate = 0.15
        elif roic > 0.15:
            growth_rate = 0.12
        elif roic > 0.10:
            growth_rate = 0.08
        else:
            growth_rate = 0.05
    else:
        growth_rate = 0.05
    growth_rate = min(growth_rate, 0.20)

    # Discount rate
    if wacc is not None and wacc > terminal_growth:
        discount_rate = wacc
    else:
        if roic is not None and roic > 0.15:
            discount_rate = 0.10
        elif roic is not None and roic > 0.10:
            discount_rate = 0.11
        else:
            discount_rate = 0.12

    if discount_rate <= terminal_growth:
        return {"dcf_value_cents": None, "skip_reason": "low_discount_rate"}

    # Stage 1
    fcf = fcf_cents
    pv_stage1 = 0
    for year in range(1, 6):
        fcf = fcf * (1 + growth_rate)
        pv_stage1 += fcf / (1 + discount_rate) ** year
    fcf_year5 = fcf

    # Stage 2
    terminal_value = fcf_year5 * (1 + terminal_growth) / (discount_rate - terminal_growth)
    pv_terminal = terminal_value / (1 + discount_rate) ** 5

    return {
        "dcf_value_cents": round(pv_stage1 + pv_terminal),
        "growth_rate": growth_rate,
        "discount_rate": discount_rate,
    }


class TestDCFGrowthTiers:
    """Stage 1 growth rate depends on ROIC quality."""

    def test_high_roic_15_pct_growth(self):
        result = compute_dcf(100_000_00, roic=0.25, wacc=None)
        assert result["growth_rate"] == 0.15

    def test_good_roic_12_pct_growth(self):
        result = compute_dcf(100_000_00, roic=0.18, wacc=None)
        assert result["growth_rate"] == 0.12

    def test_moderate_roic_8_pct_growth(self):
        result = compute_dcf(100_000_00, roic=0.12, wacc=None)
        assert result["growth_rate"] == 0.08

    def test_low_roic_5_pct_growth(self):
        result = compute_dcf(100_000_00, roic=0.05, wacc=None)
        assert result["growth_rate"] == 0.05

    def test_no_roic_default_5_pct(self):
        result = compute_dcf(100_000_00, roic=None, wacc=None)
        assert result["growth_rate"] == 0.05


class TestDCFDiscountRate:
    """Discount rate: WACC if available, else tiered by ROIC."""

    def test_wacc_used_when_above_terminal(self):
        result = compute_dcf(100_000_00, roic=0.20, wacc=0.08)
        assert result["discount_rate"] == 0.08

    def test_wacc_ignored_when_below_terminal(self):
        """WACC <= 2.5% -> fall back to ROIC-tiered rate."""
        result = compute_dcf(100_000_00, roic=0.20, wacc=0.02)
        assert result["discount_rate"] == 0.10  # ROIC > 0.15 -> 10%

    def test_no_wacc_high_roic(self):
        result = compute_dcf(100_000_00, roic=0.20, wacc=None)
        assert result["discount_rate"] == 0.10

    def test_no_wacc_moderate_roic(self):
        result = compute_dcf(100_000_00, roic=0.12, wacc=None)
        assert result["discount_rate"] == 0.11

    def test_no_wacc_low_roic(self):
        result = compute_dcf(100_000_00, roic=0.05, wacc=None)
        assert result["discount_rate"] == 0.12


class TestDCFValuation:
    """End-to-end DCF value sanity checks."""

    def test_positive_value(self):
        result = compute_dcf(1_000_000_00, roic=0.20, wacc=0.10)
        assert result["dcf_value_cents"] > 0

    def test_higher_growth_higher_value(self):
        """Higher ROIC -> higher growth -> higher DCF."""
        low = compute_dcf(1_000_000_00, roic=0.05, wacc=0.10)
        high = compute_dcf(1_000_000_00, roic=0.25, wacc=0.10)
        assert high["dcf_value_cents"] > low["dcf_value_cents"]

    def test_higher_discount_lower_value(self):
        """Higher discount rate -> lower DCF value."""
        low_dr = compute_dcf(1_000_000_00, roic=0.20, wacc=0.08)
        high_dr = compute_dcf(1_000_000_00, roic=0.20, wacc=0.15)
        assert low_dr["dcf_value_cents"] > high_dr["dcf_value_cents"]

    def test_manual_calculation(self):
        """Verify DCF math with a hand-calculated example.

        FCF = $1,000,000 (100_000_000 cents), ROIC=25% -> 15% growth, WACC=10%
        """
        fcf_cents = 100_000_000
        growth = 0.15
        discount = 0.10
        terminal = 0.025

        fcf = fcf_cents
        pv1 = 0
        for yr in range(1, 6):
            fcf = fcf * (1 + growth)
            pv1 += fcf / (1 + discount) ** yr

        fcf5 = fcf
        tv = fcf5 * (1 + terminal) / (discount - terminal)
        pv_tv = tv / (1 + discount) ** 5

        expected = round(pv1 + pv_tv)
        result = compute_dcf(100_000_000, roic=0.25, wacc=0.10)
        assert result["dcf_value_cents"] == expected
