"""Security fundamentals — P/B, DCF, short interest, smart money signals."""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SecurityFundamentals(Base):
    __tablename__ = "security_fundamentals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    # Valuation
    price_to_book: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    free_cash_flow_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    fcf_currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    dcf_value_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    dcf_discount_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)
    dcf_terminal_growth: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)
    dcf_model_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Quality & profitability
    roic: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    wacc: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    roe: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    fcf_yield: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    net_debt_ebitda: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    dividend_yield: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    eps_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    revenue_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    gross_margin: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    operating_margin: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    net_margin: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    pe_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4), nullable=True)
    market_cap_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    # Short interest
    short_interest_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    short_interest_change_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    short_squeeze_risk: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    days_to_cover: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    # Institutional / Smart money
    institutional_ownership_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    institutional_flow: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    smart_money_signal: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    smart_money_outlook_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=90)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    security = relationship("Security", back_populates="fundamentals")

    __table_args__ = (
        Index("idx_security_fundamentals_security_id", "security_id", unique=True),
    )


class EarningsReport(Base):
    __tablename__ = "earnings_reports"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False
    )
    fiscal_quarter: Mapped[str] = mapped_column(String(10), nullable=False)  # e.g. "Q1 2026"
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)
    report_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # Financials
    revenue_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    revenue_currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    revenue_yoy_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    eps_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    eps_yoy_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    gross_margin_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    operating_margin_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    # Estimates & surprise (from Finnhub)
    eps_estimate_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    revenue_estimate_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    surprise_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    # Qualitative
    forward_guidance: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    red_flags: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recommendation: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    recommendation_reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Meta
    source: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    security = relationship("Security", back_populates="earnings_reports")

    __table_args__ = (
        Index("idx_earnings_reports_security_id", "security_id"),
        Index("idx_earnings_reports_quarter", "security_id", "fiscal_year", "quarter", unique=True),
    )
