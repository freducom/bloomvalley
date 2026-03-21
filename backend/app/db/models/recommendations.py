"""Recommendation tracking with retrospective accuracy analysis."""

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


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False
    )
    # Action: buy, sell, hold
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    # Confidence: high, medium, low
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)
    # Target price in cents
    target_price_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    # Price at time of recommendation (cents)
    entry_price_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    # Thesis
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    bull_case: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bear_case: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Source agent / analyst
    source: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # Time horizon: short (< 3m), medium (3-12m), long (> 12m)
    time_horizon: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    # Status: active, closed, expired
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")
    # Dates
    recommended_date: Mapped[date] = mapped_column(Date, nullable=False)
    closed_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # Outcome (filled when closed)
    exit_price_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    return_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    outcome_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    security = relationship("Security", backref="recommendations")

    __table_args__ = (
        Index("idx_recommendations_security_id", "security_id"),
        Index("idx_recommendations_status", "status"),
        Index("idx_recommendations_date", "recommended_date"),
    )
