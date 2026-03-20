"""Watchlist CRUD endpoints."""

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.db.engine import async_session
from app.db.models.prices import Price
from app.db.models.securities import Security
from app.db.models.watchlists import Watchlist, WatchlistItem

logger = structlog.get_logger()

router = APIRouter()


class WatchlistCreate(BaseModel):
    name: str
    description: str | None = None


class WatchlistItemAdd(BaseModel):
    security_id: int
    notes: str | None = None


def _meta():
    return {"timestamp": datetime.now(timezone.utc).isoformat(), "cacheAge": None, "stale": False}


@router.get("/")
async def list_watchlists():
    """List all watchlists with item counts."""
    async with async_session() as session:
        result = await session.execute(
            select(Watchlist).order_by(Watchlist.sort_order, Watchlist.name)
        )
        watchlists = result.scalars().all()

        data = []
        for wl in watchlists:
            count_result = await session.execute(
                select(func.count(WatchlistItem.id)).where(
                    WatchlistItem.watchlist_id == wl.id
                )
            )
            count = count_result.scalar_one()
            data.append({
                "id": wl.id,
                "name": wl.name,
                "description": wl.description,
                "isDefault": wl.is_default,
                "itemCount": count,
                "createdAt": wl.created_at.isoformat(),
            })

    return {"data": data, "meta": _meta()}


@router.post("/")
async def create_watchlist(body: WatchlistCreate):
    """Create a new watchlist."""
    async with async_session() as session:
        wl = Watchlist(name=body.name, description=body.description)
        session.add(wl)
        await session.commit()
        await session.refresh(wl)

    return {
        "data": {
            "id": wl.id,
            "name": wl.name,
            "description": wl.description,
            "isDefault": wl.is_default,
        },
        "meta": _meta(),
    }


@router.get("/{watchlist_id}")
async def get_watchlist(watchlist_id: int):
    """Get a watchlist with all items, securities, and latest prices."""
    async with async_session() as session:
        wl = await session.get(Watchlist, watchlist_id)
        if not wl:
            raise HTTPException(status_code=404, detail="Watchlist not found")

        # Get items with securities
        items_result = await session.execute(
            select(WatchlistItem)
            .where(WatchlistItem.watchlist_id == watchlist_id)
            .order_by(WatchlistItem.sort_order)
        )
        items = items_result.scalars().all()

        if not items:
            return {
                "data": {
                    "id": wl.id,
                    "name": wl.name,
                    "description": wl.description,
                    "isDefault": wl.is_default,
                    "items": [],
                },
                "meta": _meta(),
            }

        # Load securities
        sec_ids = [i.security_id for i in items]
        sec_result = await session.execute(
            select(Security).where(Security.id.in_(sec_ids))
        )
        securities = {s.id: s for s in sec_result.scalars().all()}

        # Load latest prices
        subq = (
            select(Price.security_id, func.max(Price.date).label("max_date"))
            .where(Price.security_id.in_(sec_ids))
            .group_by(Price.security_id)
            .subquery()
        )
        price_result = await session.execute(
            select(Price).join(
                subq,
                (Price.security_id == subq.c.security_id)
                & (Price.date == subq.c.max_date),
            )
        )
        prices = {p.security_id: p for p in price_result.scalars().all()}

        # Also get previous day prices for day change
        prev_subq = (
            select(Price.security_id, func.max(Price.date).label("prev_date"))
            .where(Price.security_id.in_(sec_ids))
            .group_by(Price.security_id)
        )
        # This is simplified — get second-most-recent price
        # For now, just compute day change from OHLC (close vs open)

        item_data = []
        for item in items:
            sec = securities.get(item.security_id)
            price = prices.get(item.security_id)
            if not sec:
                continue

            day_change_cents = None
            day_change_pct = None
            if price and price.open_cents and price.close_cents:
                day_change_cents = price.close_cents - price.open_cents
                if price.open_cents != 0:
                    day_change_pct = round(
                        (day_change_cents / price.open_cents) * 100, 2
                    )

            item_data.append({
                "id": item.id,
                "securityId": sec.id,
                "ticker": sec.ticker,
                "name": sec.name,
                "assetClass": sec.asset_class,
                "currency": sec.currency,
                "exchange": sec.exchange,
                "sector": sec.sector,
                "notes": item.notes,
                "priceCents": price.close_cents if price else None,
                "priceDate": price.date.isoformat() if price else None,
                "dayChangeCents": day_change_cents,
                "dayChangePct": day_change_pct,
                "addedAt": item.added_at.isoformat(),
            })

    return {
        "data": {
            "id": wl.id,
            "name": wl.name,
            "description": wl.description,
            "isDefault": wl.is_default,
            "items": item_data,
        },
        "meta": _meta(),
    }


@router.post("/{watchlist_id}/items")
async def add_watchlist_item(watchlist_id: int, body: WatchlistItemAdd):
    """Add a security to a watchlist."""
    async with async_session() as session:
        wl = await session.get(Watchlist, watchlist_id)
        if not wl:
            raise HTTPException(status_code=404, detail="Watchlist not found")

        sec = await session.get(Security, body.security_id)
        if not sec:
            raise HTTPException(status_code=404, detail="Security not found")

        # Check duplicate
        existing = await session.execute(
            select(WatchlistItem).where(
                WatchlistItem.watchlist_id == watchlist_id,
                WatchlistItem.security_id == body.security_id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Security already in watchlist")

        item = WatchlistItem(
            watchlist_id=watchlist_id,
            security_id=body.security_id,
            notes=body.notes,
        )
        session.add(item)
        await session.commit()

    return {"data": {"watchlistId": watchlist_id, "securityId": body.security_id}, "meta": _meta()}


@router.delete("/{watchlist_id}/items/{security_id}")
async def remove_watchlist_item(watchlist_id: int, security_id: int):
    """Remove a security from a watchlist."""
    async with async_session() as session:
        result = await session.execute(
            select(WatchlistItem).where(
                WatchlistItem.watchlist_id == watchlist_id,
                WatchlistItem.security_id == security_id,
            )
        )
        item = result.scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        await session.delete(item)
        await session.commit()

    return {"data": {"removed": True}, "meta": _meta()}


@router.delete("/{watchlist_id}")
async def delete_watchlist(watchlist_id: int):
    """Delete a watchlist and all its items."""
    async with async_session() as session:
        wl = await session.get(Watchlist, watchlist_id)
        if not wl:
            raise HTTPException(status_code=404, detail="Watchlist not found")

        await session.delete(wl)
        await session.commit()

    return {"data": {"deleted": True}, "meta": _meta()}
