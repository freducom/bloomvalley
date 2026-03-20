"""Insider trades, congress trades, and buyback program models."""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class InsiderTrade(Base):
    __tablename__ = "insider_trades"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    security_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("securities.id"), nullable=False
    )
    insider_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    trade_type: Mapped[str] = mapped_column(String(20), nullable=False)  # buy, sell, exercise, gift, other
    jurisdiction: Mapped[str] = mapped_column(String(5), nullable=False)  # fi, se, us
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    disclosure_date: Mapped[date] = mapped_column(Date, nullable=False)
    shares: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    price_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    value_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    shares_after: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    is_significant: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    security = relationship("Security")

    __table_args__ = (
        Index("idx_insider_trades_security_id", "security_id"),
        Index("idx_insider_trades_trade_date", "trade_date"),
        Index("idx_insider_trades_jurisdiction", "jurisdiction"),
        Index(
            "idx_insider_trades_is_significant",
            "is_significant",
            postgresql_where="is_significant = TRUE",
        ),
    )


class CongressTrade(Base):
    __tablename__ = "congress_trades"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    security_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("securities.id"), nullable=True
    )
    member_name: Mapped[str] = mapped_column(String(255), nullable=False)
    party: Mapped[str] = mapped_column(String(20), nullable=False)  # democrat, republican, independent
    chamber: Mapped[str] = mapped_column(String(10), nullable=False)  # senate, house
    state: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    trade_type: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    disclosure_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount_range_low_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_range_high_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="USD")
    ticker_reported: Mapped[str] = mapped_column(String(20), nullable=False)
    asset_description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="quiver_quantitative"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    security = relationship("Security")

    __table_args__ = (
        Index("idx_congress_trades_security_id", "security_id"),
        Index("idx_congress_trades_trade_date", "trade_date"),
        Index("idx_congress_trades_member_name", "member_name"),
    )


class BuybackProgram(Base):
    __tablename__ = "buyback_programs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    security_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("securities.id"), nullable=False
    )
    announced_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    authorized_amount_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    authorized_shares: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    executed_amount_cents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    executed_shares: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="announced"
    )  # announced, active, completed, cancelled
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    security = relationship("Security")

    __table_args__ = (
        Index("idx_buyback_programs_security_id", "security_id"),
        Index("idx_buyback_programs_status", "status"),
    )
