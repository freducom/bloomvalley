import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PipelineSource(str, enum.Enum):
    YAHOO_FINANCE = "yahoo_finance"
    ALPHA_VANTAGE = "alpha_vantage"
    FRED = "fred"
    ECB = "ecb"
    COINGECKO = "coingecko"
    JUSTETF = "justetf"
    MORNINGSTAR = "morningstar"
    MANUAL = "manual"


pipeline_runs_source_enum = ENUM(
    "yahoo_finance", "alpha_vantage", "fred", "ecb",
    "coingecko", "justetf", "morningstar", "manual",
    name="pipeline_runs_source_enum",
    create_type=False,
)


class Price(Base):
    __tablename__ = "prices"

    # No BIGSERIAL id — hypertable uses (security_id, date) as unique key
    security_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("securities.id"), primary_key=True
    )
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    open_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    high_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    low_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    close_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    adjusted_close_cents: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )
    volume: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    source: Mapped[str] = mapped_column(
        pipeline_runs_source_enum, nullable=False, server_default="yahoo_finance"
    )
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    # Relationships
    security = relationship("Security", back_populates="prices")

    __table_args__ = (
        CheckConstraint(
            "high_cents >= low_cents "
            "AND high_cents >= open_cents "
            "AND high_cents >= close_cents "
            "AND low_cents <= open_cents "
            "AND low_cents <= close_cents",
            name="chk_prices_ohlc",
        ),
        Index("idx_prices_security_id_date", "security_id", "date", unique=True),
        Index("idx_prices_date", "date"),
        Index("idx_prices_security_id", "security_id"),
    )


class FxRate(Base):
    __tablename__ = "fx_rates"

    # Composite primary key for hypertable
    base_currency: Mapped[str] = mapped_column(
        String(3), primary_key=True, server_default="EUR"
    )
    quote_currency: Mapped[str] = mapped_column(String(3), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    source: Mapped[str] = mapped_column(
        pipeline_runs_source_enum, nullable=False, server_default="ecb"
    )
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("rate > 0", name="chk_fx_rates_rate_positive"),
        CheckConstraint("base_currency = 'EUR'", name="chk_fx_rates_base_eur"),
        Index(
            "idx_fx_rates_pair_date",
            "base_currency",
            "quote_currency",
            "date",
            unique=True,
        ),
        Index("idx_fx_rates_quote_currency", "quote_currency"),
        Index("idx_fx_rates_date", "date"),
    )


class MacroIndicator(Base):
    __tablename__ = "macro_indicators"

    # Composite primary key for hypertable
    indicator_code: Mapped[str] = mapped_column(String(50), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    source: Mapped[str] = mapped_column(pipeline_runs_source_enum, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "idx_macro_indicators_code_date",
            "indicator_code",
            "date",
            unique=True,
        ),
        Index("idx_macro_indicators_code", "indicator_code"),
        Index("idx_macro_indicators_date", "date"),
    )
