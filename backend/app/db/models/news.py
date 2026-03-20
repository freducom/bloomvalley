"""News items and security linkage models."""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class NewsItem(Base):
    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    published_at: Mapped[datetime] = mapped_column(nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    is_global: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_bookmarked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )

    # Relationships
    securities = relationship("NewsItemSecurity", back_populates="news_item", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_news_items_published_at", "published_at"),
        Index("idx_news_items_source", "source"),
        Index(
            "idx_news_items_is_bookmarked",
            "is_bookmarked",
            postgresql_where="is_bookmarked = TRUE",
        ),
    )


class NewsItemSecurity(Base):
    __tablename__ = "news_item_securities"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    news_item_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("news_items.id", ondelete="CASCADE"), nullable=False
    )
    security_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("securities.id"), nullable=False
    )
    impact_direction: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )  # positive, negative, neutral
    impact_severity: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )  # high, medium, low
    impact_reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    news_item = relationship("NewsItem", back_populates="securities")
    security = relationship("Security")

    __table_args__ = (
        Index("idx_news_item_securities_security_id", "security_id"),
        Index("idx_news_item_securities_news_item_id", "news_item_id"),
        {"extend_existing": True},
    )
