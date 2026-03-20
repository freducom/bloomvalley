from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Dividend(Base):
    __tablename__ = "dividends"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("accounts.id"), nullable=False
    )
    security_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("securities.id"), nullable=False
    )
    transaction_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("transactions.id"), nullable=True
    )
    ex_date: Mapped[date] = mapped_column(Date, nullable=False)
    pay_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    record_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    amount_per_share_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    amount_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    shares_held: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    gross_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    withholding_tax_cents: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default="0"
    )
    withholding_tax_pct: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    net_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    net_amount_eur_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fx_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6), nullable=True)
    is_qualified: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    account = relationship("Account", back_populates="dividends")
    security = relationship("Security", back_populates="dividends")
    transaction = relationship("Transaction", back_populates="dividend")

    __table_args__ = (
        CheckConstraint(
            "net_amount_cents = gross_amount_cents - withholding_tax_cents",
            name="chk_dividends_net_amount",
        ),
        Index("idx_dividends_account_id", "account_id"),
        Index("idx_dividends_security_id", "security_id"),
        Index("idx_dividends_ex_date", "ex_date"),
        Index(
            "idx_dividends_account_security_ex_date",
            "account_id",
            "security_id",
            "ex_date",
        ),
    )
