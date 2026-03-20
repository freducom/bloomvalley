"""Integer money arithmetic helpers.

All monetary values are stored as integer cents. These helpers convert
between cents and Decimal for display and intermediate calculations.
"""

from decimal import ROUND_HALF_UP, Decimal


def cents_to_decimal(cents: int) -> Decimal:
    """Convert integer cents to a Decimal with 2 decimal places.

    Example: 123456 -> Decimal('1234.56')
    """
    return Decimal(cents) / Decimal(100)


def decimal_to_cents(amount: Decimal) -> int:
    """Convert a Decimal amount to integer cents, rounding half-up.

    Example: Decimal('1234.56') -> 123456
    """
    return int((amount * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_eur(cents: int) -> str:
    """Format integer cents as a EUR display string.

    Example: 123456 -> '€1,234.56'
    Example: -50000 -> '-€500.00'
    Example: 0 -> '€0.00'
    """
    amount = cents_to_decimal(abs(cents))
    # Format with comma thousands separator and dot decimal
    formatted = f"{amount:,.2f}"
    if cents < 0:
        return f"-\u20ac{formatted}"
    return f"\u20ac{formatted}"
