import asyncio
from datetime import datetime, timezone
from typing import Optional

import structlog
import yfinance as yf
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.securities import SecurityCreate, SecurityResponse
from app.db.engine import get_session
from app.db.models.securities import Security

logger = structlog.get_logger()
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


_COUNTRY_TO_ISO = {
    "United States": "US", "United Kingdom": "GB", "Germany": "DE", "France": "FR",
    "Finland": "FI", "Sweden": "SE", "Denmark": "DK", "Norway": "NO", "Netherlands": "NL",
    "Switzerland": "CH", "Japan": "JP", "China": "CN", "Canada": "CA", "Australia": "AU",
    "Ireland": "IE", "Belgium": "BE", "Austria": "AT", "Spain": "ES", "Italy": "IT",
    "Portugal": "PT", "Luxembourg": "LU", "South Korea": "KR", "Taiwan": "TW",
    "India": "IN", "Brazil": "BR", "Mexico": "MX", "Singapore": "SG", "Hong Kong": "HK",
    "Israel": "IL", "South Africa": "ZA", "Poland": "PL", "Greece": "GR",
}


def _yf_lookup(ticker: str) -> dict | None:
    """Fetch basic info for a ticker from Yahoo Finance (blocking)."""
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        name = info.get("longName") or info.get("shortName")
        if not name:
            return None
        qtype = info.get("quoteType", "").upper()
        asset_class = "crypto" if qtype == "CRYPTOCURRENCY" else "etf" if qtype == "ETF" else "stock"
        country_raw = info.get("country") or ""
        country_code = _COUNTRY_TO_ISO.get(country_raw, country_raw[:2].upper() if country_raw else None)
        return {
            "ticker": ticker.upper(),
            "name": name,
            "assetClass": asset_class,
            "currency": info.get("currency", "USD"),
            "exchange": info.get("exchange"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "country": country_code,
            "countryName": country_raw or None,
            "quoteType": qtype,
            "marketCap": info.get("marketCap"),
            "currentPrice": info.get("currentPrice") or info.get("regularMarketPrice"),
        }
    except Exception as e:
        logger.warning("yf_lookup_failed", ticker=ticker, error=str(e))
        return None


@router.get("/lookup/{ticker}")
async def lookup_ticker(ticker: str):
    """Look up a ticker from Yahoo Finance. Returns basic info without saving."""
    result = await asyncio.to_thread(_yf_lookup, ticker)
    if not result:
        raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found on Yahoo Finance")
    return {
        "data": result,
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }
