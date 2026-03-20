import enum
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
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


class AlertType(str, enum.Enum):
    PRICE_ABOVE = "price_above"
    PRICE_BELOW = "price_below"
    DRIFT_THRESHOLD = "drift_threshold"
    STALENESS = "staleness"
    DIVIDEND_ANNOUNCED = "dividend_announced"
    CUSTOM = "custom"


class AlertStatus(str, enum.Enum):
    ACTIVE = "active"
    TRIGGERED = "triggered"
    DISMISSED = "dismissed"
    EXPIRED = "expired"


alerts_type_enum = ENUM(
    "price_above", "price_below", "drift_threshold",
    "staleness", "dividend_announced", "custom",
    name="alerts_type_enum",
    create_type=False,
)

alerts_status_enum = ENUM(
    "active", "triggered", "dismissed", "expired",
    name="alerts_status_enum",
    create_type=False,
)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(alerts_type_enum, nullable=False)
    status: Mapped[str] = mapped_column(
        alerts_status_enum, nullable=False, server_default="active"
    )
    security_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("securities.id"), nullable=True
    )
    account_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("accounts.id"), nullable=True
    )
    threshold_value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(18, 6), nullable=True
    )
    threshold_currency: Mapped[Optional[str]] = mapped_column(
        String(3), nullable=True
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    triggered_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    dismissed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    security = relationship("Security", back_populates="alerts")
    account = relationship("Account", back_populates="alerts")

    __table_args__ = (
        Index("idx_alerts_status", "status"),
        Index("idx_alerts_security_id", "security_id"),
        Index("idx_alerts_type_status", "type", "status"),
        Index(
            "idx_alerts_active",
            "status",
            postgresql_where=Text("status = 'active'"),
        ),
    )
