"""Sector impact mapping service — rule engine for global events to sector impacts."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.global_events import EventSectorImpact, GlobalEvent

# Event type -> sector impact rules
# Each entry: (impact_direction, impact_magnitude, reasoning)
IMPACT_RULES: dict[str, dict[str, tuple[str, int, str]]] = {
    "conflict": {
        "energy": ("negative", 4, "Supply disruption risk"),
        "materials": ("negative", 3, "Supply chain disruption"),
        "industrials": ("negative", 2, "Defense spending may offset"),
        "consumer_discretionary": ("negative", 2, "Consumer confidence impact"),
    },
    "trade": {
        "technology": ("negative", 3, "Export restrictions risk"),
        "industrials": ("negative", 3, "Tariff impact"),
        "materials": ("negative", 2, "Trade flow disruption"),
        "consumer_staples": ("negative", 1, "Input cost pressure"),
    },
    "weather": {
        "utilities": ("negative", 3, "Infrastructure damage"),
        "real_estate": ("negative", 3, "Property damage"),
        "materials": ("negative", 2, "Supply disruption"),
        "consumer_staples": ("negative", 2, "Agricultural impact"),
    },
    "health": {
        "healthcare": ("positive", 4, "Increased demand"),
        "consumer_discretionary": ("negative", 3, "Spending pullback"),
        "industrials": ("negative", 2, "Workforce disruption"),
        "technology": ("positive", 2, "Remote work demand"),
    },
    "economic": {
        "financials": ("negative", 3, "Credit risk increase"),
        "real_estate": ("negative", 3, "Rate sensitivity"),
        "consumer_discretionary": ("negative", 2, "Spending impact"),
    },
    "energy": {
        "energy": ("negative", 4, "Direct impact"),
        "utilities": ("negative", 3, "Input cost pressure"),
        "industrials": ("negative", 2, "Energy cost impact"),
        "consumer_staples": ("negative", 1, "Transport cost"),
    },
    "protest": {
        "consumer_discretionary": ("negative", 2, "Business disruption"),
        "financials": ("negative", 1, "Uncertainty premium"),
    },
    "strategic": {
        "technology": ("negative", 3, "Geopolitical risk"),
        "energy": ("negative", 3, "Strategic resource risk"),
        "financials": ("negative", 2, "Sanctions/regulation risk"),
    },
}


def classify_severity(tone_score: float) -> str:
    """Classify severity from GDELT tone score.

    Lower (more negative) tone = higher severity.
    """
    if tone_score < -5:
        return "critical"
    elif tone_score < -2:
        return "high"
    elif tone_score < 0:
        return "medium"
    else:
        return "low"


def map_sector_impacts(event_type: str) -> list[dict]:
    """Return list of sector impacts for a given event type from rules.

    Returns list of dicts with keys: sector, impact_direction, impact_magnitude, reasoning.
    """
    rules = IMPACT_RULES.get(event_type, {})
    impacts = []
    for sector, (direction, magnitude, reasoning) in rules.items():
        impacts.append({
            "sector": sector,
            "impact_direction": direction,
            "impact_magnitude": magnitude,
            "reasoning": reasoning,
        })
    return impacts


async def compute_net_sector_impact(
    session: AsyncSession, days: int = 7
) -> dict[str, dict]:
    """Aggregate net impact per sector over the given period.

    For each sector, computes a weighted score:
      net_impact = sum(magnitude * direction_sign) / event_count

    where direction_sign is +1 for positive, -1 for negative, 0 for neutral.

    Returns dict keyed by sector with net_impact, event_count, and top_events.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Build direction sign expression
    direction_sign = case(
        (EventSectorImpact.impact_direction == "positive", 1),
        (EventSectorImpact.impact_direction == "negative", -1),
        else_=0,
    )

    # Aggregate by sector
    query = (
        select(
            EventSectorImpact.sector,
            func.sum(EventSectorImpact.impact_magnitude * direction_sign).label(
                "weighted_sum"
            ),
            func.count(EventSectorImpact.id).label("event_count"),
        )
        .join(GlobalEvent, EventSectorImpact.event_id == GlobalEvent.id)
        .where(GlobalEvent.event_date >= cutoff)
        .group_by(EventSectorImpact.sector)
    )

    result = await session.execute(query)
    rows = result.all()

    sectors: dict[str, dict] = {}
    sector_names = [r.sector for r in rows]

    for row in rows:
        net = round(float(row.weighted_sum) / row.event_count, 2) if row.event_count else 0.0
        sectors[row.sector] = {
            "sector": row.sector,
            "netImpact": net,
            "weightedSum": int(row.weighted_sum),
            "eventCount": row.event_count,
            "topEvents": [],
        }

    # Fetch top events per sector (up to 3 per sector, highest magnitude)
    if sector_names:
        top_events_query = (
            select(
                EventSectorImpact.sector,
                GlobalEvent.id,
                GlobalEvent.headline,
                GlobalEvent.severity,
                GlobalEvent.event_date,
                EventSectorImpact.impact_direction,
                EventSectorImpact.impact_magnitude,
            )
            .join(GlobalEvent, EventSectorImpact.event_id == GlobalEvent.id)
            .where(
                GlobalEvent.event_date >= cutoff,
                EventSectorImpact.sector.in_(sector_names),
            )
            .order_by(
                EventSectorImpact.sector,
                EventSectorImpact.impact_magnitude.desc(),
            )
        )

        top_result = await session.execute(top_events_query)
        top_rows = top_result.all()

        # Group and limit to 3 per sector
        per_sector_count: dict[str, int] = {}
        for tr in top_rows:
            count = per_sector_count.get(tr.sector, 0)
            if count >= 3:
                continue
            per_sector_count[tr.sector] = count + 1

            if tr.sector in sectors:
                sectors[tr.sector]["topEvents"].append({
                    "eventId": tr.id,
                    "headline": tr.headline,
                    "severity": tr.severity,
                    "eventDate": tr.event_date.isoformat() if tr.event_date else None,
                    "impactDirection": tr.impact_direction,
                    "impactMagnitude": tr.impact_magnitude,
                })

    return sectors
