from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.securities import SecurityCreate, SecurityResponse
from app.db.engine import get_session
from app.db.models.securities import Security

router = APIRouter()


@router.get("")
async def list_securities(
    q: Optional[str] = Query(None, description="Search by name (trigram)"),
    ticker: Optional[str] = Query(None, description="Exact ticker match"),
    asset_class: Optional[str] = Query(None, alias="assetClass"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """List securities with pagination and optional search."""
    query = select(Security).where(Security.is_active == True)  # noqa: E712

    # Exact ticker match
    if ticker:
        query = query.where(Security.ticker == ticker)

    # Text search using trigram similarity
    if q:
        query = query.where(Security.name.ilike(f"%{q}%"))

    if asset_class:
        query = query.where(Security.asset_class == asset_class)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await session.execute(count_query)
    total = total_result.scalar_one()

    # Apply pagination
    query = query.order_by(Security.name).offset(offset).limit(limit)
    result = await session.execute(query)
    securities = result.scalars().all()

    return {
        "data": [SecurityResponse.model_validate(s).model_dump(by_alias=True) for s in securities],
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


@router.get("/{security_id}")
async def get_security(
    security_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Get a single security by ID."""
    result = await session.execute(
        select(Security).where(Security.id == security_id)
    )
    security = result.scalar_one_or_none()

    if security is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"Security with id {security_id} not found",
                    "details": None,
                }
            },
        )

    return {
        "data": SecurityResponse.model_validate(security).model_dump(by_alias=True),
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cacheAge": None,
            "stale": False,
        },
    }


@router.post("", status_code=201)
async def create_security(
    body: SecurityCreate,
    session: AsyncSession = Depends(get_session),
):
    """Add a new security to the catalog."""
    security = Security(**body.model_dump())
    session.add(security)
    await session.flush()
    await session.refresh(security)

    return {
        "data": SecurityResponse.model_validate(security).model_dump(by_alias=True),
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cacheAge": None,
            "stale": False,
        },
    }
