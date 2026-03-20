"""Pipeline runner with retry, logging, and staleness tracking."""

import asyncio
import random
from datetime import date, datetime, timezone
from typing import Any

import structlog

from app.db.engine import async_session
from app.db.models.pipeline_runs import PipelineRun
from app.pipelines.base import (
    NonRetryableError,
    PipelineAdapter,
    PipelineResult,
    RetryableError,
)

logger = structlog.get_logger()

# Active runs tracker to prevent concurrent runs of the same pipeline
_active_runs: set[str] = set()


async def run_pipeline(
    adapter: PipelineAdapter,
    from_date: date | None = None,
    to_date: date | None = None,
    max_retries: int = 3,
    trigger: str = "manual",
    redis=None,
) -> PipelineResult:
    """Execute a pipeline with retry logic, DB logging, and Redis staleness tracking."""
    pipeline_name = adapter.pipeline_name
    source = adapter.source_name

    if pipeline_name in _active_runs:
        raise RuntimeError(f"Pipeline {pipeline_name} is already running")

    _active_runs.add(pipeline_name)
    started_at = datetime.now(timezone.utc)

    # Insert pipeline_runs row with status='running'
    async with async_session() as session:
        run_record = PipelineRun(
            source=source,
            pipeline_name=pipeline_name,
            status="running",
            started_at=started_at,
        )
        session.add(run_record)
        await session.commit()
        await session.refresh(run_record)
        run_id = run_record.id

    result = PipelineResult()
    error_message: str | None = None

    try:
        # Fetch with retry
        raw: list[dict[str, Any]] = []
        last_error: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                raw = await adapter.fetch(from_date, to_date)
                last_error = None
                break
            except RetryableError as e:
                last_error = e
                if attempt < max_retries:
                    delay = min(1 * (2**attempt), 60)
                    jitter = delay * random.uniform(-0.20, 0.20)
                    wait = delay + jitter
                    logger.warning(
                        "pipeline_fetch_retry",
                        pipeline=pipeline_name,
                        attempt=attempt,
                        delay=round(wait, 1),
                        error=str(e),
                    )
                    await asyncio.sleep(wait)
            except NonRetryableError as e:
                last_error = e
                break

        if last_error is not None:
            raise last_error

        # Validate, transform, load (no retries — failures = code bugs)
        valid, errors = await adapter.validate(raw)
        transformed = await adapter.transform(valid)
        rows_stored = await adapter.load(transformed)

        result = PipelineResult(
            rows_fetched=len(raw),
            rows_valid=len(valid),
            rows_stored=rows_stored,
            rows_skipped=len(raw) - len(valid),
            errors=errors,
            metadata={},
        )

        if result.rows_skipped > 0 and result.rows_valid > 0:
            status = "partial"
        elif result.rows_valid == 0 and result.rows_fetched > 0:
            status = "failed"
            error_message = "; ".join(errors[:5])
        else:
            status = "success"

    except Exception as e:
        status = "failed"
        error_message = str(e)[:2000]
        logger.error(
            "pipeline_run_failed",
            pipeline=pipeline_name,
            error=error_message,
        )
    finally:
        _active_runs.discard(pipeline_name)

    finished_at = datetime.now(timezone.utc)
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)

    # Update pipeline_runs row
    async with async_session() as session:
        run_record = await session.get(PipelineRun, run_id)
        if run_record:
            run_record.status = status
            run_record.finished_at = finished_at
            run_record.duration_ms = duration_ms
            run_record.rows_affected = result.rows_stored
            run_record.error_message = error_message
            run_record.run_metadata = {
                "rows_fetched": result.rows_fetched,
                "rows_valid": result.rows_valid,
                "rows_skipped": result.rows_skipped,
                "trigger": trigger,
            }
            await session.commit()

    # Update Redis staleness cache on success/partial
    if redis and status in ("success", "partial"):
        await redis.set(
            f"pipeline:{pipeline_name}:last_success_at",
            finished_at.isoformat(),
        )

    log_level = {"success": "info", "partial": "warning", "failed": "error"}
    getattr(logger, log_level.get(status, "info"))(
        "pipeline_run_completed",
        source=source,
        pipeline=pipeline_name,
        status=status,
        duration_ms=duration_ms,
        rows_fetched=result.rows_fetched,
        rows_stored=result.rows_stored,
        rows_skipped=result.rows_skipped,
        trigger=trigger,
    )

    return result


def is_pipeline_running(pipeline_name: str) -> bool:
    return pipeline_name in _active_runs
