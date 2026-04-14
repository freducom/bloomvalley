"""Tests for integer money arithmetic helpers."""

from decimal import Decimal

from app.utils.money import cents_to_decimal, decimal_to_cents, format_eur


class TestCentsToDecimal:
    def test_basic(self):
        assert cents_to_decimal(123456) == Decimal("1234.56")

    def test_zero(self):
        assert cents_to_decimal(0) == Decimal("0.00")

    def test_negative(self):
        assert cents_to_decimal(-50000) == Decimal("-500.00")

    def test_one_cent(self):
        assert cents_to_decimal(1) == Decimal("0.01")

    def test_large_value(self):
        assert cents_to_decimal(100_000_000_00) == Decimal("100000000.00")


class TestDecimalToCents:
    def test_basic(self):
        assert decimal_to_cents(Decimal("1234.56")) == 123456

    def test_zero(self):
        assert decimal_to_cents(Decimal("0")) == 0

    def test_negative(self):
        assert decimal_to_cents(Decimal("-500.00")) == -50000

    def test_rounds_half_up(self):
        # 12.345 -> 1234.5 cents -> rounds to 1235
        assert decimal_to_cents(Decimal("12.345")) == 1235

    def test_rounds_half_up_negative(self):
        # -12.345 -> -1234.5 cents -> ROUND_HALF_UP rounds away from zero = -1235
        assert decimal_to_cents(Decimal("-12.345")) == -1235

    def test_sub_cent_down(self):
        # 12.341 -> 1234.1 -> rounds to 1234
        assert decimal_to_cents(Decimal("12.341")) == 1234

    def test_roundtrip(self):
        for cents in [0, 1, 99, 100, 123456, -50000, 999_999_99]:
            assert decimal_to_cents(cents_to_decimal(cents)) == cents


class TestFormatEur:
    def test_basic(self):
        assert format_eur(123456) == "\u20ac1,234.56"

    def test_zero(self):
        assert format_eur(0) == "\u20ac0.00"

    def test_negative(self):
        assert format_eur(-50000) == "-\u20ac500.00"

    def test_one_cent(self):
        assert format_eur(1) == "\u20ac0.01"

    def test_large(self):
        assert format_eur(100_000_000_00) == "\u20ac100,000,000.00"

    def test_negative_one_cent(self):
        assert format_eur(-1) == "-\u20ac0.01"
