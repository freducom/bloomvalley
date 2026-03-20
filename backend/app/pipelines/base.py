from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class PipelineResult:
    """Outcome of a single pipeline run."""

    rows_fetched: int = 0
    rows_valid: int = 0
    rows_stored: int = 0
    rows_skipped: int = 0
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class RetryableError(Exception):
    """Transient error — the pipeline runner will retry."""


class NonRetryableError(Exception):
    """Permanent error — logged and skipped, no retry."""


class PipelineAdapter(ABC):
    """Base class for all data pipeline adapters."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Pipeline source identifier matching pipeline_runs_source_enum."""
        ...

    @property
    @abstractmethod
    def pipeline_name(self) -> str:
        """Human-readable pipeline name, e.g. 'yahoo_daily_prices'."""
        ...

    @abstractmethod
    async def fetch(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch raw data from the external source."""
        ...

    @abstractmethod
    async def validate(
        self, raw_records: list[dict]
    ) -> tuple[list[dict], list[str]]:
        """Validate raw records. Returns (valid_records, error_messages)."""
        ...

    @abstractmethod
    async def transform(self, valid_records: list[dict]) -> list[dict]:
        """Transform validated records into DB schema."""
        ...

    @abstractmethod
    async def load(self, transformed_records: list[dict]) -> int:
        """Upsert transformed records into the database. Returns rows affected."""
        ...

    async def run(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> PipelineResult:
        """Execute the full pipeline: fetch → validate → transform → load."""
        raw = await self.fetch(from_date, to_date)
        valid, errors = await self.validate(raw)
        transformed = await self.transform(valid)
        rows_stored = await self.load(transformed)

        return PipelineResult(
            rows_fetched=len(raw),
            rows_valid=len(valid),
            rows_stored=rows_stored,
            rows_skipped=len(raw) - len(valid),
            errors=errors,
            metadata={},
        )
