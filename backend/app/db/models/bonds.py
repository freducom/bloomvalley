"""Bond metadata for fixed income portfolio tracking."""

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


class Bond(Base):
    __tablename__ = "bonds"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    issuer: Mapped[str] = mapped_column(String(255), nullable=False)
    # government, corporate, municipal, supranational
    issuer_type: Mapped[str] = mapped_column(String(20), nullable=False, default="government")
    coupon_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5), nullable=True)
    # annual, semi_annual, quarterly, zero_coupon
    coupon_frequency: Mapped[str] = mapped_column(String(20), nullable=False, default="annual")
    face_value_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    issue_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    maturity_date: Mapped[date] = mapped_column(Date, nullable=False)
    call_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    purchase_price_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    purchase_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("1"))
    yield_to_maturity: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5), nullable=True)
    current_yield: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 5), nullable=True)
    credit_rating: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    rating_agency: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_inflation_linked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_callable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    security = relationship("Security", back_populates="bond_detail")

    __table_args__ = (
        Index("idx_bonds_security_id", "security_id", unique=True),
        Index("idx_bonds_maturity_date", "maturity_date"),
        Index("idx_bonds_issuer_type", "issuer_type"),
    )
