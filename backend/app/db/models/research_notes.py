from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ResearchNote(Base):
    __tablename__ = "research_notes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    security_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("securities.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    thesis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bull_case: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bear_case: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    base_case: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    intrinsic_value_cents: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )
    intrinsic_value_currency: Mapped[Optional[str]] = mapped_column(
        String(3), nullable=True
    )
    margin_of_safety_pct: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    moat_rating: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    tags: Mapped[Optional[list[str]]] = mapped_column(
        ARRAY(Text), nullable=True
    )
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
    security = relationship("Security", back_populates="research_notes")

    __table_args__ = (
        Index("idx_research_notes_security_id", "security_id"),
        Index(
            "idx_research_notes_tags",
            "tags",
            postgresql_using="gin",
        ),
        Index(
            "idx_research_notes_is_active",
            "is_active",
            postgresql_where=Text("is_active = TRUE"),
        ),
    )
