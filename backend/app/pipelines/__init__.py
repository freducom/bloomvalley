from app.pipelines.base import (
    NonRetryableError,
    PipelineAdapter,
    PipelineResult,
    RetryableError,
)

PIPELINE_REGISTRY: dict[str, type[PipelineAdapter]] = {}


def register_pipeline(cls: type[PipelineAdapter]) -> type[PipelineAdapter]:
    """Class decorator to register a pipeline adapter."""
    instance = cls()
    PIPELINE_REGISTRY[instance.pipeline_name] = cls
    return cls


__all__ = [
    "PIPELINE_REGISTRY",
    "PipelineAdapter",
    "PipelineResult",
    "RetryableError",
    "NonRetryableError",
    "register_pipeline",
]
