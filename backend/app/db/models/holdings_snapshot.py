from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class HoldingsSnapshot(Base):
    __tablename__ = "holdings_snapshot"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id"), nullable=False
    )
    security_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("securities.id"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 18), nullable=False)
    cost_basis_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cost_basis_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="EUR"
    )
    market_price_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    market_price_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    market_value_eur_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    unrealized_pnl_eur_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fx_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6), nullable=True)
    weight_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    # Relationships
    account = relationship("Account", back_populates="holdings_snapshots")
    security = relationship("Security", back_populates="holdings_snapshots")

    __table_args__ = (
        Index(
            "idx_holdings_snapshot_date_account_security",
            "snapshot_date",
            "account_id",
            "security_id",
            unique=True,
        ),
        Index("idx_holdings_snapshot_date", "snapshot_date"),
        Index("idx_holdings_snapshot_security_id", "security_id"),
    )
