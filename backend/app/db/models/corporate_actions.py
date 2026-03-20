import enum
from datetime import datetime
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
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CorporateActionType(str, enum.Enum):
    SPLIT = "split"
    REVERSE_SPLIT = "reverse_split"
    MERGER = "merger"
    SPINOFF = "spinoff"
    NAME_CHANGE = "name_change"
    TICKER_CHANGE = "ticker_change"
    DELISTING = "delisting"


corporate_actions_type_enum = ENUM(
    "split", "reverse_split", "merger", "spinoff",
    "name_change", "ticker_change", "delisting",
    name="corporate_actions_type_enum",
    create_type=False,
)


class CorporateAction(Base):
    __tablename__ = "corporate_actions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    security_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("securities.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(corporate_actions_type_enum, nullable=False)
    effective_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    ratio_from: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    ratio_to: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6), nullable=True)
    new_security_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("securities.id"), nullable=True
    )
    cash_in_lieu_cents: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )
    cash_currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_processed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    security = relationship(
        "Security",
        back_populates="corporate_actions",
        foreign_keys=[security_id],
    )
    new_security = relationship(
        "Security",
        foreign_keys=[new_security_id],
    )

    __table_args__ = (
        CheckConstraint(
            "(type IN ('split', 'reverse_split') "
            "AND ratio_from IS NOT NULL AND ratio_to IS NOT NULL) OR "
            "(type NOT IN ('split', 'reverse_split'))",
            name="chk_corporate_actions_ratio",
        ),
        Index("idx_corporate_actions_security_id", "security_id"),
        Index("idx_corporate_actions_effective_date", "effective_date"),
        Index(
            "idx_corporate_actions_is_processed",
            "is_processed",
            postgresql_where=Text("is_processed = FALSE"),
        ),
    )
