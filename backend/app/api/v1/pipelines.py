"""Pipeline monitoring and manual trigger endpoints."""

import asyncio
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from app.db.engine import async_session
from app.db.models.pipeline_runs import PipelineRun
from app.pipelines import PIPELINE_REGISTRY
from app.pipelines.runner import is_pipeline_running, run_pipeline

router = APIRouter()


@router.get("/pipelines")
async def list_pipelines(request: Request):
    """Return last-run information for every registered pipeline."""
    pipelines = []

    async with async_session() as session:
        for name, adapter_cls in PIPELINE_REGISTRY.items():
            adapter = adapter_cls()

            # Get last successful run
            last_success = await session.execute(
                select(PipelineRun)
                .where(
                    PipelineRun.pipeline_name == name,
                    PipelineRun.status.in_(["success", "partial"]),
                )
                .order_by(PipelineRun.started_at.desc())
                .limit(1)
            )
            last_success_row = last_success.scalar_one_or_none()

            # Get last failed run
            last_failure = await session.execute(
                select(PipelineRun)
                .where(
                    PipelineRun.pipeline_name == name,
                    PipelineRun.status == "failed",
                )
                .order_by(PipelineRun.started_at.desc())
                .limit(1)
            )
            last_failure_row = last_failure.scalar_one_or_none()

            # Check Redis for cached last success
            redis = request.app.state.redis
            cached_ts = await redis.get(f"pipeline:{name}:last_success_at")

            pipelines.append(
                {
                    "name": name,
                    "source": adapter.source_name,
                    "enabled": True,
                    "isRunning": is_pipeline_running(name),
                    "lastSuccess": (
                        last_success_row.finished_at.isoformat()
                        if last_success_row and last_success_row.finished_at
                        else cached_ts
                    ),
                    "lastFailure": (
                        last_failure_row.finished_at.isoformat()
                        if last_failure_row and last_failure_row.finished_at
                        else None
                    ),
                    "lastRunStatus": (
                        last_success_row.status if last_success_row else None
                    ),
                    "lastRunDurationMs": (
                        last_success_row.duration_ms if last_success_row else None
                    ),
                    "lastRunRowsAffected": (
                        last_success_row.rows_affected if last_success_row else None
                    ),
                }
            )

    return {
        "data": pipelines,
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cacheAge": None,
            "stale": False,
        },
    }


@router.post("/pipelines/{name}/run")
async def trigger_pipeline(
    name: str,
    request: Request,
    from_date: date | None = Query(None, alias="fromDate"),
    to_date: date | None = Query(None, alias="toDate"),
):
    """Manually trigger a pipeline run."""
    if name not in PIPELINE_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Unknown pipeline: {name}")

    if is_pipeline_running(name):
        raise HTTPException(status_code=409, detail=f"Pipeline {name} is already running")

    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=422, detail="fromDate must be <= toDate")

    adapter_cls = PIPELINE_REGISTRY[name]
    adapter = adapter_cls()
    redis = request.app.state.redis

    # Run asynchronously in the background
    asyncio.create_task(
        run_pipeline(
            adapter,
            from_date=from_date,
            to_date=to_date,
            trigger="manual",
            redis=redis,
        )
    )

    return {
        "message": f"Pipeline {name} triggered",
        "pipeline": name,
    }


@router.get("/pipelines/{name}/runs")
async def get_pipeline_runs(
    name: str,
    limit: int = Query(10, ge=1, le=100),
):
    """Get recent runs for a specific pipeline."""
    async with async_session() as session:
        result = await session.execute(
            select(PipelineRun)
            .where(PipelineRun.pipeline_name == name)
            .order_by(PipelineRun.started_at.desc())
            .limit(limit)
        )
        runs = result.scalars().all()

    return {
        "data": [
            {
                "id": r.id,
                "source": r.source,
                "pipelineName": r.pipeline_name,
                "status": r.status,
                "startedAt": r.started_at.isoformat() if r.started_at else None,
                "finishedAt": r.finished_at.isoformat() if r.finished_at else None,
                "durationMs": r.duration_ms,
                "rowsAffected": r.rows_affected,
                "errorMessage": r.error_message,
                "metadata": r.run_metadata,
            }
            for r in runs
        ],
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cacheAge": None,
            "stale": False,
        },
    }
