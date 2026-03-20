import re
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.accounts import AccountCreate, AccountResponse
from app.db.engine import async_session, get_session
from app.db.models.accounts import Account

router = APIRouter()


@router.get("")
async def list_accounts(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """List all accounts."""
    query = select(Account).where(Account.is_active == True)  # noqa: E712

    count_query = select(func.count()).select_from(query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar_one()

    query = query.order_by(Account.name).offset(offset).limit(limit)
    result = await session.execute(query)
    accounts = result.scalars().all()

    return {
        "data": [AccountResponse.model_validate(a).model_dump() for a in accounts],
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cacheAge": None,
            "stale": False,
        },
        "pagination": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "hasMore": (offset + limit) < total,
        },
    }


@router.get("/{account_id}")
async def get_account(
    account_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Get a single account by ID."""
    result = await session.execute(
        select(Account).where(Account.id == account_id)
    )
    account = result.scalar_one_or_none()

    if account is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Account with id {account_id} not found",
                    "details": None,
                }
            },
        )

    return {
        "data": AccountResponse.model_validate(account).model_dump(),
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cacheAge": None,
            "stale": False,
        },
    }


@router.post("", status_code=201)
async def create_account(
    body: AccountCreate,
    session: AsyncSession = Depends(get_session),
):
    """Create a new account."""
    account = Account(**body.model_dump(exclude_unset=True))
    session.add(account)
    await session.flush()
    await session.refresh(account)

    return {
        "data": AccountResponse.model_validate(account).model_dump(),
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cacheAge": None,
            "stale": False,
        },
    }


class CashBalanceRequest(BaseModel):
    text: str  # e.g. "18 871,96 EUR" or "1234.56 USD"
    account_id: int | None = None  # If None, update all Nordnet accounts proportionally


def _parse_cash_text(text: str) -> tuple[int, str]:
    """Parse a cash balance string like '18 871,96 EUR' into (cents, currency)."""
    text = text.strip()

    # Try to extract currency at end
    match = re.match(r"^(.+?)\s*([A-Z]{3})$", text)
    if match:
        amount_str = match.group(1).strip()
        currency = match.group(2)
    else:
        amount_str = text
        currency = "EUR"

    # Detect decimal format and parse
    # If comma is the last separator before decimals → comma decimal
    if re.search(r",\d{1,2}$", amount_str):
        # Comma decimal: remove spaces and dots (thousands), replace comma
        cleaned = amount_str.replace(" ", "").replace(".", "").replace(",", ".")
    else:
        # Period decimal: remove spaces and commas (thousands)
        cleaned = amount_str.replace(" ", "").replace(",", "")

    cents = int(round(Decimal(cleaned) * 100))
    return cents, currency


@router.post("/cash")
async def update_cash_balance(req: CashBalanceRequest):
    """Update cash balance for an account.

    Accepts text like '18 871,96 EUR' (Finnish format) or '1234.56 USD'.
    If account_id is not provided, updates the first active Nordnet account.
    """
    try:
        cents, currency = _parse_cash_text(req.text)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Cannot parse cash amount: {req.text}")

    async with async_session() as session:
        if req.account_id:
            account = await session.get(Account, req.account_id)
        else:
            # Find the first active Nordnet account
            result = await session.execute(
                select(Account)
                .where(Account.institution == "Nordnet", Account.is_active.is_(True))
                .order_by(Account.id)
                .limit(1)
            )
            account = result.scalar_one_or_none()

        if not account:
            raise HTTPException(status_code=404, detail="No account found")

        account.cash_balance_cents = cents
        account.cash_currency = currency
        await session.commit()

    return {
        "data": {
            "accountId": account.id,
            "accountName": account.name,
            "cashBalanceCents": cents,
            "cashCurrency": currency,
        },
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cacheAge": None,
            "stale": False,
        },
    }
