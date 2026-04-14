from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class SecurityCreate(BaseModel):
    """Request body for creating a security."""

    model_config = ConfigDict(populate_by_name=True)

    ticker: str
    isin: Optional[str] = None
    name: str
    asset_class: str
    currency: str
    exchange: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    country: Optional[str] = None
    is_accumulating: Optional[bool] = None
    coingecko_id: Optional[str] = None
    openfigi: Optional[str] = None
    company_group: Optional[str] = None


class SecurityResponse(BaseModel):
    """Response schema for a security."""

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )

    id: int
    ticker: str
    isin: Optional[str] = None
    name: str
    asset_class: str
    currency: str
    exchange: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    country: Optional[str] = None
    is_accumulating: Optional[bool] = None
    coingecko_id: Optional[str] = None
    openfigi: Optional[str] = None
    company_group: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
