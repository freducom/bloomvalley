from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import structlog
from sqlalchemy import func, select

_logger = structlog.get_logger()


async def get_last_known_prices(security_ids: set[int]) -> dict[int, int]:
    """Get the most recent close_cents per security for spike detection."""
    if not security_ids:
        return {}
    from app.db.engine import async_session
    from app.db.models.prices import Price

    async with async_session() as session:
        subq = (
            select(
                Price.security_id,
                func.max(Price.date).label("max_date"),
            )
            .where(Price.security_id.in_(security_ids))
            .group_by(Price.security_id)
            .subquery()
        )
        result = await session.execute(
            select(Price.security_id, Price.close_cents)
            .join(subq, (Price.security_id == subq.c.security_id)
                  & (Price.date == subq.c.max_date))
        )
        return {row.security_id: row.close_cents for row in result.all()}


def check_price_spike(
    rec: dict,
    last_close_cents: int,
    errors: list[str],
) -> bool:
    """Check a price record for suspicious spikes against last known price.

    Returns True if the record should be kept (possibly after auto-correction),
    False if it was rejected and appended to errors.

    Auto-corrects ~100x spikes (GBp/GBX ↔ GBP unit switches).
    Rejects unexplained >10x moves.
    """
    close = rec.get("close")
    if close is None or last_close_cents is None or last_close_cents <= 0:
        return True

    close_cents = round(close * 100)
    ratio = close_cents / last_close_cents
    ticker = rec.get("ticker", "?")
    rec_date = rec.get("date")

    # ~100x spike: likely pence→pounds (divide by 100)
    if 80 < ratio < 120:
        _logger.warning("price_spike_autocorrected",
                        ticker=ticker, date=str(rec_date),
                        raw_close=close, last_cents=last_close_cents,
                        ratio=round(ratio, 4),
                        action="dividing OHLC by 100 (likely pence→pounds)")
        for field in ("open", "high", "low", "close", "adj_close"):
            if rec.get(field) is not None:
                rec[field] = rec[field] / 100
        return True

    # ~0.01x spike: likely pounds→pence (multiply by 100)
    if 0.008 < ratio < 0.012:
        _logger.warning("price_spike_autocorrected",
                        ticker=ticker, date=str(rec_date),
                        raw_close=close, last_cents=last_close_cents,
                        ratio=round(ratio, 4),
                        action="multiplying OHLC by 100 (likely pounds→pence)")
        for field in ("open", "high", "low", "close", "adj_close"):
            if rec.get(field) is not None:
                rec[field] = rec[field] * 100
        return True

    # Unexplained >10x spike — reject
    if ratio < 0.10 or ratio > 10:
        errors.append(
            f"{ticker} {rec_date}: price spike rejected "
            f"(ratio={ratio:.4f}, close_cents={close_cents}, "
            f"last_cents={last_close_cents})"
        )
        _logger.warning("price_spike_rejected",
                        ticker=ticker, date=str(rec_date),
                        raw_close=close, last_cents=last_close_cents,
                        ratio=round(ratio, 4))
        return False

    return True


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
