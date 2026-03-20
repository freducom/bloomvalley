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
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TransactionType(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"
    DIVIDEND = "dividend"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    FEE = "fee"
    INTEREST = "interest"
    CORPORATE_ACTION = "corporate_action"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"


transactions_type_enum = ENUM(
    "buy", "sell", "dividend", "transfer_in", "transfer_out",
    "fee", "interest", "corporate_action", "deposit", "withdrawal",
    name="transactions_type_enum",
    create_type=False,
)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id"), nullable=False
    )
    security_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("securities.id"), nullable=True
    )
    type: Mapped[str] = mapped_column(transactions_type_enum, nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    settlement_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(28, 18), nullable=False, server_default="0"
    )
    price_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    price_currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    total_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fee_cents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    fee_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="EUR"
    )
    fx_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6), nullable=True)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="EUR"
    )
    withholding_tax_cents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    external_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    account = relationship("Account", back_populates="transactions")
    security = relationship("Security", back_populates="transactions")
    tax_lots_opened = relationship(
        "TaxLot",
        back_populates="open_transaction",
        foreign_keys="TaxLot.open_transaction_id",
    )
    tax_lots_closed = relationship(
        "TaxLot",
        back_populates="close_transaction",
        foreign_keys="TaxLot.close_transaction_id",
    )
    dividend = relationship("Dividend", back_populates="transaction", uselist=False)

    __table_args__ = (
        CheckConstraint(
            "currency = upper(currency)",
            name="chk_transactions_currency_upper",
        ),
        CheckConstraint(
            "fee_cents >= 0",
            name="chk_transactions_fee_non_negative",
        ),
        CheckConstraint(
            "withholding_tax_cents >= 0",
            name="chk_transactions_withholding_non_negative",
        ),
        Index("idx_transactions_account_id", "account_id"),
        Index("idx_transactions_security_id", "security_id"),
        Index("idx_transactions_trade_date", "trade_date"),
        Index("idx_transactions_type", "type"),
        Index(
            "idx_transactions_account_security_date",
            "account_id",
            "security_id",
            "trade_date",
        ),
    )
