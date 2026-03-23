import enum
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PipelineRunStatus(str, enum.Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


pipeline_runs_status_enum = ENUM(
    "running", "success", "failed", "partial",
    name="pipeline_runs_status_enum",
    create_type=False,
)

pipeline_runs_source_enum = ENUM(
    "yahoo_finance", "alpha_vantage", "fred", "ecb",
    "coingecko", "justetf", "morningstar", "manual",
    "google_news", "sec_edgar", "quiver", "gdelt",
    "regional_rss",
    name="pipeline_runs_source_enum",
    create_type=False,
)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(pipeline_runs_source_enum, nullable=False)
    pipeline_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(pipeline_runs_status_enum, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rows_affected: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    run_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "(finished_at IS NOT NULL AND duration_ms IS NOT NULL AND duration_ms >= 0) OR "
            "(finished_at IS NULL AND duration_ms IS NULL)",
            name="chk_pipeline_runs_duration",
        ),
        Index("idx_pipeline_runs_source", "source"),
        Index("idx_pipeline_runs_status", "status"),
        Index("idx_pipeline_runs_started_at", "started_at"),
        Index("idx_pipeline_runs_source_started", "source", "started_at"),
    )
