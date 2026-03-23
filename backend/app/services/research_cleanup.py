"""Research notes retention cleanup — delete old auto-generated notes."""

from datetime import datetime, timedelta

import structlog
from sqlalchemy import delete, and_

from app.db.engine import async_session
from app.db.models.research_notes import ResearchNote

logger = structlog.get_logger()

# Retention periods
SWARM_REPORT_DAYS = 7      # Analyst swarm reports regenerate 3x/day
SEC_FILING_DAYS = 30        # SEC filing metadata
TECHNICAL_NOTE_DAYS = 7     # Auto-generated technical notes
# Manual notes (no auto-generated tags) are kept forever


async def cleanup_old_research() -> dict:
    """Delete old auto-generated research notes based on retention policy.

    - analyst_report/swarm tagged: 7 days
    - sec_filing tagged: 30 days
    - technical/auto-generated tagged: 7 days
    - Manual notes (no auto tags): never deleted
    """
    now = datetime.utcnow()
    deleted = 0

    async with async_session() as session:
        # Swarm analyst reports older than 7 days
        cutoff = now - timedelta(days=SWARM_REPORT_DAYS)
        result = await session.execute(
            delete(ResearchNote).where(
                and_(
                    ResearchNote.tags.contains(["analyst_report"]),
                    ResearchNote.created_at < cutoff,
                )
            )
        )
        swarm_deleted = result.rowcount
        deleted += swarm_deleted

        # SEC filings older than 30 days
        cutoff = now - timedelta(days=SEC_FILING_DAYS)
        result = await session.execute(
            delete(ResearchNote).where(
                and_(
                    ResearchNote.tags.contains(["sec_filing"]),
                    ResearchNote.created_at < cutoff,
                )
            )
        )
        sec_deleted = result.rowcount
        deleted += sec_deleted

        # Auto-generated technical notes older than 7 days
        cutoff = now - timedelta(days=TECHNICAL_NOTE_DAYS)
        result = await session.execute(
            delete(ResearchNote).where(
                and_(
                    ResearchNote.tags.contains(["auto-generated"]),
                    ResearchNote.created_at < cutoff,
                )
            )
        )
        tech_deleted = result.rowcount
        deleted += tech_deleted

        await session.commit()

    logger.info(
        "research_cleanup_complete",
        swarm_deleted=swarm_deleted,
        sec_deleted=sec_deleted,
        tech_deleted=tech_deleted,
        total_deleted=deleted,
    )

    return {
        "swarm_deleted": swarm_deleted,
        "sec_deleted": sec_deleted,
        "tech_deleted": tech_deleted,
        "total_deleted": deleted,
    }
