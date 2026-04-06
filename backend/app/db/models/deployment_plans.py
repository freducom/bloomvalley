"""Capital deployment plan models — strategic timeline for capital allocation."""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DeploymentPlan(Base):
    """A 12-month forward capital deployment plan."""

    __tablename__ = "deployment_plans"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="draft"
    )  # draft, active, completed, superseded
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    total_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="EUR"
    )
    strategy_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    macro_regime_at_creation: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )
    next_review_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )

    tranches: Mapped[list["DeploymentTranche"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan",
        order_by="DeploymentTranche.planned_date",
    )

    __table_args__ = (
        Index("idx_deployment_plans_status", "status"),
    )


class DeploymentTranche(Base):
    """A single deployment tranche within a plan (typically quarterly)."""

    __tablename__ = "deployment_tranches"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("deployment_plans.id", ondelete="CASCADE"),
        nullable=False,
    )
    quarter_label: Mapped[str] = mapped_column(String(10), nullable=False)
    planned_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="EUR"
    )
    core_allocation_pct: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="60"
    )
    conviction_allocation_pct: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="30"
    )
    cash_buffer_pct: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="10"
    )
    candidate_tickers: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True
    )  # [{ticker, name, rationale, allocationPct}]
    conditional_triggers: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True
    )  # [{condition, threshold, action}]
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="planned"
    )  # planned, active, completed, accelerated, deferred
    executed_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    executed_amount_cents: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )
    execution_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )

    plan: Mapped["DeploymentPlan"] = relationship(back_populates="tranches")

    __table_args__ = (
        Index("idx_deployment_tranches_plan_id", "plan_id"),
        Index("idx_deployment_tranches_status", "status"),
        Index("idx_deployment_tranches_planned_date", "planned_date"),
    )
