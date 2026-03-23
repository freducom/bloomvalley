"""News retention cleanup — strip old summaries and delete expired items."""

from datetime import datetime, timezone

import structlog
from sqlalchemy import text

from app.db.engine import async_session

logger = structlog.get_logger()


async def cleanup_old_news() -> dict:
    """Run news retention cleanup.

    Policy:
    - Bookmarked items (is_bookmarked = true): preserved forever.
    - 30-90 days old, not bookmarked: strip summary (headline-only retention).
    - Over 90 days, not bookmarked: delete entirely (CASCADE cleans links).

    Returns a dict with counts of stripped, deleted, and preserved items.
    """
    async with async_session() as session:
        # Count bookmarked items (preserved) for reporting
        preserved_result = await session.execute(
            text("SELECT count(*) FROM news_items WHERE is_bookmarked = true")
        )
        preserved_count = preserved_result.scalar_one()

        # Strip summaries for items 30-90 days old, not bookmarked
        strip_result = await session.execute(
            text(
                """
                UPDATE news_items SET summary = NULL
                WHERE published_at < now() - interval '30 days'
                  AND published_at >= now() - interval '90 days'
                  AND is_bookmarked = false
                  AND summary IS NOT NULL
                """
            )
        )
        stripped_count = strip_result.rowcount

        # Delete items older than 90 days, not bookmarked
        delete_result = await session.execute(
            text(
                """
                DELETE FROM news_items
                WHERE published_at < now() - interval '90 days'
                  AND is_bookmarked = false
                """
            )
        )
        deleted_count = delete_result.rowcount

        await session.commit()

    logger.info(
        "news_cleanup_complete",
        stripped=stripped_count,
        deleted=deleted_count,
        preserved_bookmarked=preserved_count,
    )

    return {
        "stripped": stripped_count,
        "deleted": deleted_count,
        "preservedBookmarked": preserved_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
