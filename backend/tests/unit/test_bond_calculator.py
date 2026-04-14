"""Tests for bond yield, accrued interest, and income projection calculations."""

from datetime import date
from decimal import Decimal

import pytest

from app.services.bond_calculator import (
    _freq_to_int,
    calculate_accrued_interest,
    calculate_annual_coupon_cents,
    calculate_current_yield,
    calculate_ytm,
    project_income_stream,
)


class TestFreqToInt:
    def test_annual(self):
        assert _freq_to_int("annual") == 1

    def test_semi_annual(self):
        assert _freq_to_int("semi_annual") == 2

    def test_quarterly(self):
        assert _freq_to_int("quarterly") == 4

    def test_zero_coupon(self):
        assert _freq_to_int("zero_coupon") == 0

    def test_unknown_defaults_to_1(self):
        assert _freq_to_int("monthly") == 1


class TestCalculateYTM:
    def test_zero_coupon(self):
        """Zero-coupon: YTM = (FV/Price)^(1/years) - 1"""
        # Buy at $900, face $1000, 2 years
        ytm = calculate_ytm(100_000, 90_000, None, "zero_coupon", 2.0)
        expected = (100_000 / 90_000) ** (1 / 2) - 1
        assert ytm == pytest.approx(expected, rel=1e-4)

    def test_par_bond(self):
        """Bond bought at par -> YTM ≈ coupon rate."""
        ytm = calculate_ytm(100_000, 100_000, Decimal("0.05"), "annual", 10.0)
        assert ytm == pytest.approx(0.05, abs=0.001)

    def test_discount_bond(self):
        """Bond below par -> YTM > coupon rate."""
        ytm = calculate_ytm(100_000, 95_000, Decimal("0.05"), "annual", 10.0)
        assert ytm is not None
        assert ytm > 0.05

    def test_premium_bond(self):
        """Bond above par -> YTM < coupon rate."""
        ytm = calculate_ytm(100_000, 105_000, Decimal("0.05"), "annual", 10.0)
        assert ytm is not None
        assert ytm < 0.05

    def test_semi_annual_coupon(self):
        ytm = calculate_ytm(100_000, 100_000, Decimal("0.06"), "semi_annual", 5.0)
        assert ytm == pytest.approx(0.06, abs=0.002)

    def test_zero_years_returns_none(self):
        assert calculate_ytm(100_000, 95_000, Decimal("0.05"), "annual", 0.0) is None

    def test_zero_price_returns_none(self):
        assert calculate_ytm(100_000, 0, Decimal("0.05"), "annual", 5.0) is None

    def test_negative_years_returns_none(self):
        assert calculate_ytm(100_000, 95_000, Decimal("0.05"), "annual", -1.0) is None


class TestCurrentYield:
    def test_basic(self):
        # 5% coupon, face $1000, market price $950
        cy = calculate_current_yield(Decimal("0.05"), 100_000, 95_000)
        # annual coupon = 5000, / 95000 ≈ 0.05263
        assert cy == pytest.approx(5_000 / 95_000, rel=1e-4)

    def test_at_par(self):
        cy = calculate_current_yield(Decimal("0.05"), 100_000, 100_000)
        assert cy == pytest.approx(0.05, rel=1e-4)

    def test_no_coupon(self):
        assert calculate_current_yield(None, 100_000, 95_000) is None
        assert calculate_current_yield(Decimal("0"), 100_000, 95_000) is None

    def test_zero_price(self):
        assert calculate_current_yield(Decimal("0.05"), 100_000, 0) is None


class TestAccruedInterest:
    def test_half_year_accrual(self):
        # 5% annual coupon on $1000 face, 180 days since last coupon
        ai = calculate_accrued_interest(
            100_000, Decimal("0.05"), "annual",
            date(2025, 1, 1), date(2025, 7, 1),
        )
        # 180/360 * 5000 = 2500
        days = (date(2025, 7, 1) - date(2025, 1, 1)).days
        expected = int(5_000 * days / 360)
        assert ai == expected

    def test_no_coupon(self):
        assert calculate_accrued_interest(100_000, None, "annual", date(2025, 1, 1)) == 0

    def test_no_last_coupon_date(self):
        assert calculate_accrued_interest(100_000, Decimal("0.05"), "annual", None) == 0

    def test_zero_coupon_bond(self):
        assert calculate_accrued_interest(
            100_000, Decimal("0.05"), "zero_coupon",
            date(2025, 1, 1), date(2025, 7, 1),
        ) == 0


class TestAnnualCouponCents:
    def test_basic(self):
        # 5% on $1000 face, 10 bonds
        result = calculate_annual_coupon_cents(100_000, Decimal("0.05"), Decimal("10"))
        assert result == 50_000  # $500 in cents

    def test_no_coupon(self):
        assert calculate_annual_coupon_cents(100_000, None, Decimal("1")) == 0

    def test_fractional_quantity(self):
        result = calculate_annual_coupon_cents(100_000, Decimal("0.04"), Decimal("2.5"))
        assert result == 10_000  # 0.04 * 100000 * 2.5 = 10000


class TestProjectIncomeStream:
    def test_basic_projection(self):
        bonds = [
            {
                "face_value_cents": 100_000,
                "coupon_rate": Decimal("0.05"),
                "quantity": Decimal("1"),
                "maturity_date": date(2030, 12, 31),
            },
        ]
        projection = project_income_stream(bonds, years_ahead=3)
        assert len(projection) == 4  # current year + 3

        # Each full year should have annual coupon income
        for p in projection:
            if p["year"] < 2030:
                assert p["annualIncomeCents"] == 5_000
            assert p["bondsMaturing"] >= 0

    def test_maturity_prorates(self):
        """Bond maturing in June gets ~6/12 of annual coupon."""
        bonds = [
            {
                "face_value_cents": 100_000,
                "coupon_rate": Decimal("0.12"),  # 12% for easy math
                "quantity": Decimal("1"),
                "maturity_date": date(2026, 6, 15),
            },
        ]
        projection = project_income_stream(bonds, years_ahead=2)
        # In 2026, bond matures in June -> 6/12 of 12000 = 6000
        year_2026 = next(p for p in projection if p["year"] == 2026)
        assert year_2026["annualIncomeCents"] == 6_000
        assert year_2026["bondsMaturing"] == 1

    def test_empty_bonds(self):
        projection = project_income_stream([], years_ahead=3)
        assert len(projection) == 4
        assert all(p["annualIncomeCents"] == 0 for p in projection)
