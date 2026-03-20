from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class EsgScore(Base):
    __tablename__ = "esg_scores"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    security_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("securities.id"), nullable=False
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    environment_score: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    social_score: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    governance_score: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    total_score: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    controversy_level: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    controversy_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    eu_taxonomy_aligned: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True
    )
    sfdr_classification: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    security = relationship("Security", back_populates="esg_scores")

    __table_args__ = (
        Index(
            "idx_esg_scores_security_date",
            "security_id",
            "as_of_date",
            unique=True,
        ),
        Index("idx_esg_scores_security_id", "security_id"),
        Index("idx_esg_scores_as_of_date", "as_of_date"),
    )
