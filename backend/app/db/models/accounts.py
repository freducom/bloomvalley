import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, Index, String, Text, func
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AccountType(str, enum.Enum):
    REGULAR = "regular"
    OSAKESAASTOTILI = "osakesaastotili"
    CRYPTO_WALLET = "crypto_wallet"
    PENSION = "pension"


class PensionSubtype(str, enum.Enum):
    PS_SOPIMUS = "ps_sopimus"
    KAPITALISAATIOSOPIMUS = "kapitalisaatiosopimus"


accounts_type_enum = ENUM(
    "regular", "osakesaastotili", "crypto_wallet", "pension",
    name="accounts_type_enum",
    create_type=False,
)

accounts_pension_subtype_enum = ENUM(
    "ps_sopimus", "kapitalisaatiosopimus",
    name="accounts_pension_subtype_enum",
    create_type=False,
)


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(accounts_type_enum, nullable=False)
    pension_subtype: Mapped[Optional[str]] = mapped_column(
        accounts_pension_subtype_enum, nullable=True
    )
    institution: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="EUR")
    osa_deposit_total_cents: Mapped[int] = mapped_column(
        nullable=False, server_default="0"
    )
    cash_balance_cents: Mapped[int] = mapped_column(
        nullable=False, server_default="0"
    )
    cash_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="EUR"
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    transactions = relationship("Transaction", back_populates="account")
    tax_lots = relationship("TaxLot", back_populates="account")
    dividends = relationship("Dividend", back_populates="account")
    holdings_snapshots = relationship("HoldingsSnapshot", back_populates="account")
    alerts = relationship("Alert", back_populates="account")

    __table_args__ = (
        CheckConstraint(
            "(type = 'pension' AND pension_subtype IS NOT NULL) OR "
            "(type != 'pension' AND pension_subtype IS NULL)",
            name="chk_accounts_pension_subtype",
        ),
        CheckConstraint(
            "(type = 'osakesaastotili' AND osa_deposit_total_cents >= 0 "
            "AND osa_deposit_total_cents <= 5000000) OR "
            "(type != 'osakesaastotili' AND osa_deposit_total_cents = 0)",
            name="chk_accounts_osa_deposit",
        ),
        CheckConstraint(
            "currency = upper(currency)",
            name="chk_accounts_currency_upper",
        ),
        Index("idx_accounts_type", "type"),
        Index(
            "idx_accounts_is_active",
            "is_active",
            postgresql_where=(is_active == True),  # noqa: E712
        ),
    )
