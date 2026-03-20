from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class Money(BaseModel):
    """Monetary value in integer cents with ISO 4217 currency code."""

    amount: int
    currency: str = "EUR"


class ResponseMeta(BaseModel):
    """Standard response metadata."""

    timestamp: datetime
    cacheAge: Optional[int] = None
    stale: bool = False


class PaginatedMeta(BaseModel):
    """Pagination metadata."""

    total: int
    limit: int
    offset: int
    hasMore: bool


class ErrorDetail(BaseModel):
    """Field-level validation error."""

    field: str
    message: str
    value: Optional[Any] = None


class ErrorBody(BaseModel):
    """Error response body."""

    code: str
    message: str
    details: Optional[list[ErrorDetail]] = None


class ErrorResponse(BaseModel):
    """Standard error response envelope."""

    error: ErrorBody
