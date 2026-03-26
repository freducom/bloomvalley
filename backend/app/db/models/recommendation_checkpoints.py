"""Recommendation checkpoints for mark-to-market accuracy tracking at 30/90/180 days."""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RecommendationCheckpoint(Base):
    __tablename__ = "recommendation_checkpoints"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    recommendation_id: Mapped[int] = mapped_column(
        ForeignKey("recommendations.id", ondelete="CASCADE"), nullable=False
    )
    days_elapsed: Mapped[int] = mapped_column(Integer, nullable=False)
    check_date: Mapped[date] = mapped_column(Date, nullable=False)
    price_at_check_cents: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    return_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 4), nullable=True)
    was_correct: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    recommendation = relationship("Recommendation", backref="checkpoints")

    __table_args__ = (
        UniqueConstraint("recommendation_id", "days_elapsed", name="uq_rec_checkpoints_rec_days"),
        Index("idx_rec_checkpoints_rec_id", "recommendation_id"),
    )
