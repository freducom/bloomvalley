"""Import and ImportRow models for Nordnet portfolio import."""

import enum
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ImportStatus(str, enum.Enum):
    PARSING = "parsing"
    PARSED = "parsed"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class MatchStatus(str, enum.Enum):
    AUTO_MATCHED = "auto_matched"
    TICKER_MATCHED = "ticker_matched"
    MANUAL_MAPPED = "manual_mapped"
    UNRECOGNIZED = "unrecognized"
    SKIPPED = "skipped"


class ImportAction(str, enum.Enum):
    TRANSFER_IN = "transfer_in"
    BUY = "buy"
    SELL = "sell"
    SKIP = "skip"


imports_status_enum = ENUM(
    "parsing", "parsed", "confirmed", "cancelled", "failed",
    name="imports_status_enum",
    create_type=False,
)

import_rows_match_status_enum = ENUM(
    "auto_matched", "ticker_matched", "manual_mapped", "unrecognized", "skipped",
    name="import_rows_match_status_enum",
    create_type=False,
)

import_rows_action_enum = ENUM(
    "transfer_in", "buy", "sell", "skip",
    name="import_rows_action_enum",
    create_type=False,
)


class Import(Base):
    __tablename__ = "imports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="nordnet"
    )
    status: Mapped[str] = mapped_column(
        imports_status_enum, nullable=False, server_default="parsing"
    )
    account_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("accounts.id"), nullable=True
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    matched_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    unmatched_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    import_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    rows: Mapped[list["ImportRow"]] = relationship(
        back_populates="import_record", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_imports_status", "status"),
    )


class ImportRow(Base):
    __tablename__ = "import_rows"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    import_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("imports.id", ondelete="CASCADE"), nullable=False
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    # Parsed fields
    parsed_ticker: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    parsed_isin: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    parsed_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    parsed_quantity: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(28, 18), nullable=True
    )
    parsed_avg_price_cents: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )
    parsed_market_value_cents: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )
    parsed_currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    parsed_account_type: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )

    # Matching
    match_status: Mapped[str] = mapped_column(
        import_rows_match_status_enum, nullable=False, server_default="unrecognized"
    )
    action: Mapped[str] = mapped_column(
        import_rows_action_enum, nullable=False, server_default="transfer_in"
    )
    security_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("securities.id"), nullable=True
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    import_record: Mapped["Import"] = relationship(back_populates="rows")
    security = relationship("Security")

    __table_args__ = (
        Index("idx_import_rows_import_id", "import_id"),
    )
