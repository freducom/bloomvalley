"""Global events and sector impact models."""

from datetime import datetime
from typing import Optional

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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class GlobalEvent(Base):
    __tablename__ = "global_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)  # gdelt, manual
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # conflict, trade, weather, health, economic, energy, protest, strategic
    headline: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    location_country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    location_lat: Mapped[Optional[float]] = mapped_column(
        Numeric(9, 6), nullable=True
    )
    location_lon: Mapped[Optional[float]] = mapped_column(
        Numeric(9, 6), nullable=True
    )
    sentiment_score: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 2), nullable=True
    )  # GDELT tone score
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # critical, high, medium, low
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    event_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    fetched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    sector_impacts = relationship(
        "EventSectorImpact",
        back_populates="event",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_global_events_event_date", "event_date"),
        Index("idx_global_events_event_type", "event_type"),
        Index("idx_global_events_severity", "severity"),
        Index("idx_global_events_source", "source"),
    )


class EventSectorImpact(Base):
    __tablename__ = "event_sector_impacts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("global_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    sector: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # technology, healthcare, energy, financials, materials, industrials,
    # consumer_discretionary, consumer_staples, utilities, real_estate,
    # communication_services
    impact_direction: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # positive, negative, neutral
    impact_magnitude: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # 1 to 5
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    event = relationship("GlobalEvent", back_populates="sector_impacts")

    __table_args__ = (
        Index("idx_event_sector_impacts_event_id", "event_id"),
        Index("idx_event_sector_impacts_sector", "sector"),
    )
