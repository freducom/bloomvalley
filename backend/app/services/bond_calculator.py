"""Bond yield and income projection calculations — all server-side."""

from datetime import date
from decimal import Decimal


def calculate_ytm(
    face_value_cents: int,
    purchase_price_cents: int,
    coupon_rate: Decimal | None,
    coupon_frequency: str,
    years_to_maturity: float,
) -> float | None:
    """Newton-Raphson YTM solver. Returns annualized yield as decimal (e.g. 0.045)."""
    if years_to_maturity <= 0 or purchase_price_cents <= 0:
        return None

    freq = _freq_to_int(coupon_frequency)
    if freq == 0:
        # Zero-coupon: YTM = (FV/Price)^(1/years) - 1
        return (face_value_cents / purchase_price_cents) ** (1 / years_to_maturity) - 1

    coupon = float(coupon_rate or 0) * face_value_cents / freq
    n_periods = int(years_to_maturity * freq)
    if n_periods <= 0:
        return None

    price = float(purchase_price_cents)
    fv = float(face_value_cents)

    # Initial guess
    ytm = float(coupon_rate or Decimal("0.05"))

    for _ in range(200):
        r = ytm / freq
        if r <= -1:
            r = 0.001
        pv = sum(coupon / (1 + r) ** t for t in range(1, n_periods + 1))
        pv += fv / (1 + r) ** n_periods
        diff = pv - price

        # Derivative
        dpv = sum(-t * coupon / (1 + r) ** (t + 1) for t in range(1, n_periods + 1))
        dpv += -n_periods * fv / (1 + r) ** (n_periods + 1)
        dpv /= freq

        if abs(dpv) < 1e-12:
            break
        ytm -= diff / dpv
        if abs(diff) < 0.01:  # converged within 0.01 cent
            break

    return ytm


def calculate_current_yield(
    coupon_rate: Decimal | None,
    face_value_cents: int,
    market_price_cents: int,
) -> float | None:
    """Current yield = annual coupon / market price."""
    if not coupon_rate or market_price_cents <= 0:
        return None
    annual_coupon = float(coupon_rate) * face_value_cents
    return annual_coupon / market_price_cents


def calculate_accrued_interest(
    face_value_cents: int,
    coupon_rate: Decimal | None,
    coupon_frequency: str,
    last_coupon_date: date | None,
    settlement_date: date | None = None,
) -> int:
    """Accrued interest in cents using 30/360 convention."""
    if not coupon_rate or not last_coupon_date:
        return 0
    if settlement_date is None:
        settlement_date = date.today()

    freq = _freq_to_int(coupon_frequency)
    if freq == 0:
        return 0

    days = (settlement_date - last_coupon_date).days
    period_days = 360 / freq
    annual_coupon = float(coupon_rate) * face_value_cents
    return int(annual_coupon * days / 360)


def calculate_annual_coupon_cents(
    face_value_cents: int,
    coupon_rate: Decimal | None,
    quantity: Decimal,
) -> int:
    """Annual coupon income in cents for given quantity."""
    if not coupon_rate:
        return 0
    return int(float(coupon_rate) * face_value_cents * float(quantity))


def project_income_stream(
    bonds: list[dict],
    years_ahead: int = 15,
) -> list[dict]:
    """Project annual coupon income for each year going forward.

    Each bond dict needs: coupon_rate, face_value_cents, quantity, maturity_date, currency.
    Returns list of {year, annual_income_cents, bonds_maturing, remaining_income_cents}.
    """
    today = date.today()
    current_year = today.year
    projection = []

    for year_offset in range(years_ahead + 1):
        year = current_year + year_offset
        year_end = date(year, 12, 31)

        income = 0
        maturing_this_year = 0
        for b in bonds:
            mat = b["maturity_date"]
            if mat >= date(year, 1, 1):  # bond still alive at start of year
                annual = calculate_annual_coupon_cents(
                    b["face_value_cents"],
                    b.get("coupon_rate"),
                    b.get("quantity", Decimal("1")),
                )
                # Prorate if maturing mid-year
                if mat.year == year:
                    months = mat.month
                    income += int(annual * months / 12)
                    maturing_this_year += 1
                else:
                    income += annual

        # Remaining annual income after this year's maturities
        remaining = 0
        for b in bonds:
            mat = b["maturity_date"]
            if mat > year_end:
                remaining += calculate_annual_coupon_cents(
                    b["face_value_cents"],
                    b.get("coupon_rate"),
                    b.get("quantity", Decimal("1")),
                )

        projection.append({
            "year": year,
            "annualIncomeCents": income,
            "bondsMaturing": maturing_this_year,
            "remainingAnnualIncomeCents": remaining,
        })

    return projection


def _freq_to_int(frequency: str) -> int:
    return {
        "annual": 1,
        "semi_annual": 2,
        "quarterly": 4,
        "zero_coupon": 0,
    }.get(frequency, 1)
