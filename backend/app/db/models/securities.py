import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, Index, String, Text, func
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AssetClass(str, enum.Enum):
    STOCK = "stock"
    BOND = "bond"
    ETF = "etf"
    CRYPTO = "crypto"


securities_asset_class_enum = ENUM(
    "stock", "bond", "etf", "crypto", "fund",
    name="securities_asset_class_enum",
    create_type=False,
)


class Security(Base):
    __tablename__ = "securities"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    isin: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_class: Mapped[str] = mapped_column(
        securities_asset_class_enum, nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    exchange: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    sector: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    industry: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    is_accumulating: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    coingecko_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    openfigi: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    morningstar_id: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
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
    transactions = relationship("Transaction", back_populates="security")
    tax_lots = relationship("TaxLot", back_populates="security")
    prices = relationship("Price", back_populates="security")
    dividends = relationship("Dividend", back_populates="security")
    corporate_actions = relationship(
        "CorporateAction",
        back_populates="security",
        foreign_keys="CorporateAction.security_id",
    )
    watchlist_items = relationship("WatchlistItem", back_populates="security")
    research_notes = relationship("ResearchNote", back_populates="security")
    holdings_snapshots = relationship("HoldingsSnapshot", back_populates="security")
    alerts = relationship("Alert", back_populates="security")
    bond_detail = relationship("Bond", back_populates="security", uselist=False)
    fundamentals = relationship("SecurityFundamentals", back_populates="security", uselist=False)
    earnings_reports = relationship("EarningsReport", back_populates="security")

    __table_args__ = (
        CheckConstraint(
            "currency = upper(currency)",
            name="chk_securities_currency_upper",
        ),
        Index(
            "idx_securities_ticker_exchange",
            "ticker",
            "exchange",
            unique=True,
            postgresql_where=Text("exchange IS NOT NULL"),
        ),
        Index(
            "idx_securities_ticker_crypto",
            "ticker",
            unique=True,
            postgresql_where=Text("asset_class = 'crypto'"),
        ),
        Index(
            "idx_securities_isin",
            "isin",
            unique=True,
            postgresql_where=Text("isin IS NOT NULL"),
        ),
        Index("idx_securities_asset_class", "asset_class"),
        Index(
            "idx_securities_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )
