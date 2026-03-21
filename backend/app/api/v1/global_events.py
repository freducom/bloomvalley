"""Global events & sector impact endpoints."""

from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select, case, literal_column

from app.db.engine import async_session
from app.db.models.global_events import GlobalEvent, EventSectorImpact
from app.db.models.securities import Security
from app.db.models.transactions import Transaction
from app.services.sector_impact import compute_net_sector_impact

logger = structlog.get_logger()

router = APIRouter()


def _event_to_dict(event: GlobalEvent, impacts: list[dict] | None = None) -> dict:
    return {
        "id": event.id,
        "source": event.source,
        "eventType": event.event_type,
        "headline": event.headline,
        "summary": event.summary,
        "locationCountry": event.location_country,
        "locationLat": float(event.location_lat) if event.location_lat is not None else None,
        "locationLon": float(event.location_lon) if event.location_lon is not None else None,
        "sentimentScore": float(event.sentiment_score) if event.sentiment_score is not None else None,
        "severity": event.severity,
        "sourceUrl": event.source_url,
        "fingerprint": event.fingerprint,
        "eventDate": event.event_date.isoformat() if event.event_date else None,
        "fetchedAt": event.fetched_at.isoformat() if event.fetched_at else None,
        "createdAt": event.created_at.isoformat() if event.created_at else None,
        "sectorImpacts": impacts or [],
    }


def _impact_to_dict(impact: EventSectorImpact) -> dict:
    return {
        "id": impact.id,
        "sector": impact.sector,
        "impactDirection": impact.impact_direction,
        "impactMagnitude": impact.impact_magnitude,
        "reasoning": impact.reasoning,
    }


@router.get("/sector-impact")
async def sector_impact_summary(
    days: int = Query(7, ge=1, le=365),
):
    """Net sector impact summary over a period.

    For each sector, computes a weighted average of impact_magnitude * direction_sign.
    """
    async with async_session() as session:
        sectors = await compute_net_sector_impact(session, days=days)

    data = sorted(sectors.values(), key=lambda s: abs(s["netImpact"]), reverse=True)

    return {
        "data": data,
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "days": days,
        },
    }


@router.get("/portfolio-impact")
async def portfolio_impact(
    days: int = Query(7, ge=1, le=365),
):
    """How recent global events affect current holdings via sector exposure.

    Cross-references holdings (from transactions) with sector impacts.
    """
    async with async_session() as session:
        # Get sector impacts
        sectors = await compute_net_sector_impact(session, days=days)

        # Calculate current holdings from transactions
        qty_case = case(
            (Transaction.type.in_(["buy", "transfer_in"]), Transaction.quantity),
            (Transaction.type.in_(["sell", "transfer_out"]), -Transaction.quantity),
            else_=literal_column("0"),
        )

        positions_query = (
            select(
                Transaction.security_id,
                func.sum(qty_case).label("net_quantity"),
            )
            .where(
                Transaction.security_id.isnot(None),
                Transaction.type.in_(["buy", "sell", "transfer_in", "transfer_out"]),
            )
            .group_by(Transaction.security_id)
            .having(func.sum(qty_case) > 0)
        )

        result = await session.execute(positions_query)
        positions = result.all()

        if not positions:
            return {
                "data": [],
                "meta": {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "days": days,
                },
            }

        # Fetch security details for held positions
        sec_ids = [p.security_id for p in positions]
        sec_result = await session.execute(
            select(Security).where(Security.id.in_(sec_ids))
        )
        securities = {s.id: s for s in sec_result.scalars().all()}

    # Map holdings to sector impacts
    holdings = []
    for pos in positions:
        sec = securities.get(pos.security_id)
        if not sec:
            continue

        sector = sec.sector
        sector_key = _normalize_sector(sector) if sector else None
        sector_data = sectors.get(sector_key) if sector_key else None

        holding = {
            "securityId": sec.id,
            "ticker": sec.ticker,
            "name": sec.name,
            "sector": sec.sector,
            "netQuantity": float(pos.net_quantity),
            "sectorImpact": None,
        }

        if sector_data:
            holding["sectorImpact"] = {
                "netImpact": sector_data["netImpact"],
                "eventCount": sector_data["eventCount"],
                "topEvents": sector_data["topEvents"][:3],
            }

        holdings.append(holding)

    # Sort: holdings with sector impact first, by abs(netImpact) descending
    holdings.sort(
        key=lambda h: abs(h["sectorImpact"]["netImpact"]) if h["sectorImpact"] else 0,
        reverse=True,
    )

    return {
        "data": holdings,
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "days": days,
            "holdingsCount": len(holdings),
            "impactedCount": sum(1 for h in holdings if h["sectorImpact"]),
        },
    }


def _normalize_sector(sector: str | None) -> str | None:
    """Normalize security sector name to match impact rule sector keys.

    Maps common sector names (e.g. from Yahoo Finance) to our canonical keys.
    """
    if not sector:
        return None

    mapping = {
        "technology": "technology",
        "information technology": "technology",
        "tech": "technology",
        "healthcare": "healthcare",
        "health care": "healthcare",
        "energy": "energy",
        "financials": "financials",
        "financial services": "financials",
        "financial": "financials",
        "materials": "materials",
        "basic materials": "materials",
        "industrials": "industrials",
        "industrial": "industrials",
        "consumer discretionary": "consumer_discretionary",
        "consumer cyclical": "consumer_discretionary",
        "consumer staples": "consumer_staples",
        "consumer defensive": "consumer_staples",
        "utilities": "utilities",
        "real estate": "real_estate",
        "communication services": "communication_services",
        "communication": "communication_services",
        "telecommunications": "communication_services",
    }

    normalized = sector.lower().strip()
    return mapping.get(normalized, normalized.replace(" ", "_"))


@router.get("/{event_id}")
async def get_event(event_id: int):
    """Get a single global event with full sector impacts."""
    async with async_session() as session:
        event = await session.get(GlobalEvent, event_id)
        if not event:
            raise HTTPException(404, "Global event not found")

        impacts_result = await session.execute(
            select(EventSectorImpact).where(
                EventSectorImpact.event_id == event_id
            )
        )
        impacts = [_impact_to_dict(i) for i in impacts_result.scalars().all()]

    return {
        "data": _event_to_dict(event, impacts),
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }


@router.get("")
async def list_events(
    event_type: str | None = Query(None, alias="eventType"),
    severity: str | None = Query(None),
    region: str | None = Query(None),
    sector: str | None = Query(None),
    from_date: str | None = Query(None, alias="fromDate"),
    to_date: str | None = Query(None, alias="toDate"),
    search: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Paginated global event feed with filters."""
    async with async_session() as session:
        query = select(GlobalEvent).order_by(GlobalEvent.event_date.desc())

        if event_type:
            query = query.where(GlobalEvent.event_type == event_type)
        if severity:
            query = query.where(GlobalEvent.severity == severity)
        if region:
            query = query.where(GlobalEvent.location_country == region)
        if sector:
            query = query.join(
                EventSectorImpact,
                EventSectorImpact.event_id == GlobalEvent.id,
            ).where(EventSectorImpact.sector == sector)
        if from_date:
            query = query.where(
                GlobalEvent.event_date >= datetime.fromisoformat(from_date)
            )
        if to_date:
            query = query.where(
                GlobalEvent.event_date <= datetime.fromisoformat(to_date)
            )
        if search:
            pattern = f"%{search}%"
            query = query.where(GlobalEvent.headline.ilike(pattern))

        # Count
        count_q = select(func.count()).select_from(query.subquery())
        total = (await session.execute(count_q)).scalar_one()

        result = await session.execute(query.offset(offset).limit(limit))
        events = result.scalars().all()

        # Load sector impacts for all returned events
        event_ids = [e.id for e in events]
        impacts_by_event: dict[int, list[dict]] = {}
        if event_ids:
            impacts_result = await session.execute(
                select(EventSectorImpact).where(
                    EventSectorImpact.event_id.in_(event_ids)
                )
            )
            for impact in impacts_result.scalars().all():
                impacts_by_event.setdefault(impact.event_id, []).append(
                    _impact_to_dict(impact)
                )

    data = [
        _event_to_dict(event, impacts_by_event.get(event.id, []))
        for event in events
    ]

    return {
        "data": data,
        "pagination": {"total": total, "limit": limit, "offset": offset},
        "meta": {"timestamp": datetime.now(timezone.utc).isoformat()},
    }
