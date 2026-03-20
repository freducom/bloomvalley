"""Price data endpoints."""

from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.db.engine import async_session
from app.db.models.prices import Price
from app.db.models.securities import Security

router = APIRouter()


@router.get("/")
async def list_prices(
    security_id: int | None = Query(None, alias="securityId"),
    ticker: str | None = None,
    from_date: date | None = Query(None, alias="fromDate"),
    to_date: date | None = Query(None, alias="toDate"),
    limit: int = Query(100, ge=1, le=1000),
):
    """Get price history for a security. Filter by securityId or ticker."""
    async with async_session() as session:
        # Resolve ticker to security_id if needed
        if security_id is None and ticker:
            result = await session.execute(
                select(Security).where(Security.ticker == ticker)
            )
            sec = result.scalar_one_or_none()
            if not sec:
                raise HTTPException(status_code=404, detail=f"Security not found: {ticker}")
            security_id = sec.id
        elif security_id is None:
            raise HTTPException(status_code=400, detail="Provide securityId or ticker")

        query = (
            select(Price)
            .where(Price.security_id == security_id)
            .order_by(Price.date.desc())
            .limit(limit)
        )

        if from_date:
            query = query.where(Price.date >= from_date)
        if to_date:
            query = query.where(Price.date <= to_date)

        result = await session.execute(query)
        prices = result.scalars().all()

    return {
        "data": [
            {
                "securityId": p.security_id,
                "date": p.date.isoformat(),
                "openCents": p.open_cents,
                "highCents": p.high_cents,
                "lowCents": p.low_cents,
                "closeCents": p.close_cents,
                "adjustedCloseCents": p.adjusted_close_cents,
                "volume": p.volume,
                "currency": p.currency,
                "source": p.source,
            }
            for p in prices
        ],
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cacheAge": None,
            "stale": False,
        },
    }


@router.get("/latest")
async def latest_prices(
    security_ids: str | None = Query(None, alias="securityIds"),
):
    """Get the most recent price for one or more securities.

    securityIds: comma-separated list of security IDs.
    If omitted, returns latest price for all securities with price data.
    """
    async with async_session() as session:
        if security_ids:
            ids = [int(x.strip()) for x in security_ids.split(",")]
        else:
            ids = None

        # Subquery: max date per security
        from sqlalchemy import func

        subq = (
            select(
                Price.security_id,
                func.max(Price.date).label("max_date"),
            )
            .group_by(Price.security_id)
        )
        if ids:
            subq = subq.where(Price.security_id.in_(ids))
        subq = subq.subquery()

        query = (
            select(Price)
            .join(
                subq,
                (Price.security_id == subq.c.security_id)
                & (Price.date == subq.c.max_date),
            )
        )

        result = await session.execute(query)
        prices = result.scalars().all()

    return {
        "data": [
            {
                "securityId": p.security_id,
                "date": p.date.isoformat(),
                "openCents": p.open_cents,
                "highCents": p.high_cents,
                "lowCents": p.low_cents,
                "closeCents": p.close_cents,
                "adjustedCloseCents": p.adjusted_close_cents,
                "volume": p.volume,
                "currency": p.currency,
                "source": p.source,
            }
            for p in prices
        ],
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cacheAge": None,
            "stale": False,
        },
    }
