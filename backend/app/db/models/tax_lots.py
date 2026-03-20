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


class TaxLotState(str, enum.Enum):
    OPEN = "open"
    PARTIALLY_CLOSED = "partially_closed"
    CLOSED = "closed"


tax_lots_state_enum = ENUM(
    "open", "partially_closed", "closed",
    name="tax_lots_state_enum",
    create_type=False,
)


class TaxLot(Base):
    __tablename__ = "tax_lots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id"), nullable=False
    )
    security_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("securities.id"), nullable=False
    )
    open_transaction_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("transactions.id"), nullable=False
    )
    close_transaction_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("transactions.id"), nullable=True
    )
    state: Mapped[str] = mapped_column(
        tax_lots_state_enum, nullable=False, server_default="open"
    )
    acquired_date: Mapped[date] = mapped_column(Date, nullable=False)
    closed_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    original_quantity: Mapped[Decimal] = mapped_column(
        Numeric(28, 18), nullable=False
    )
    remaining_quantity: Mapped[Decimal] = mapped_column(
        Numeric(28, 18), nullable=False
    )
    cost_basis_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cost_basis_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="EUR"
    )
    proceeds_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    realized_pnl_cents: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )
    fx_rate_at_open: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    fx_rate_at_close: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    account = relationship("Account", back_populates="tax_lots")
    security = relationship("Security", back_populates="tax_lots")
    open_transaction = relationship(
        "Transaction",
        back_populates="tax_lots_opened",
        foreign_keys=[open_transaction_id],
    )
    close_transaction = relationship(
        "Transaction",
        back_populates="tax_lots_closed",
        foreign_keys=[close_transaction_id],
    )

    __table_args__ = (
        CheckConstraint(
            "original_quantity > 0 AND remaining_quantity >= 0",
            name="chk_tax_lots_quantity_positive",
        ),
        CheckConstraint(
            "remaining_quantity <= original_quantity",
            name="chk_tax_lots_remaining_lte_original",
        ),
        CheckConstraint(
            "(state = 'closed' AND closed_date IS NOT NULL) OR "
            "(state != 'closed')",
            name="chk_tax_lots_closed_has_date",
        ),
        Index("idx_tax_lots_account_id", "account_id"),
        Index("idx_tax_lots_security_id", "security_id"),
        Index("idx_tax_lots_state", "state"),
        Index("idx_tax_lots_open_transaction_id", "open_transaction_id"),
        Index(
            "idx_tax_lots_account_security_state",
            "account_id",
            "security_id",
            "state",
        ),
        Index("idx_tax_lots_acquired_date", "acquired_date"),
    )
