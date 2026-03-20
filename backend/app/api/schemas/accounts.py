from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class AccountCreate(BaseModel):
    """Request body for creating an account."""

    name: str
    type: str
    pension_subtype: Optional[str] = None
    institution: Optional[str] = None
    currency: str = "EUR"
    notes: Optional[str] = None


class AccountResponse(BaseModel):
    """Response schema for an account."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: str
    pension_subtype: Optional[str] = None
    institution: Optional[str] = None
    currency: str
    osa_deposit_total_cents: int
    cash_balance_cents: int = 0
    cash_currency: str = "EUR"
    notes: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
