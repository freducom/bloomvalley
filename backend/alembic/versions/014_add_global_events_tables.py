"""Add global_events and event_sector_impacts tables.

Revision ID: 014
Revises: 013
"""

import sqlalchemy as sa
from alembic import op

revision = "014"
down_revision = "013"


def upgrade() -> None:
    op.create_table(
        "global_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("headline", sa.String(500), nullable=False),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("location_country", sa.String(100), nullable=True),
        sa.Column("location_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("location_lon", sa.Numeric(9, 6), nullable=True),
        sa.Column("sentiment_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("source_url", sa.Text, nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("event_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_index("idx_global_events_event_date", "global_events", ["event_date"])
    op.create_index("idx_global_events_event_type", "global_events", ["event_type"])
    op.create_index("idx_global_events_severity", "global_events", ["severity"])
    op.create_index("idx_global_events_source", "global_events", ["source"])

    op.create_table(
        "event_sector_impacts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "event_id",
            sa.BigInteger,
            sa.ForeignKey("global_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sector", sa.String(50), nullable=False),
        sa.Column("impact_direction", sa.String(20), nullable=False),
        sa.Column("impact_magnitude", sa.Integer, nullable=False),
        sa.Column("reasoning", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_index(
        "idx_event_sector_impacts_event_id", "event_sector_impacts", ["event_id"]
    )
    op.create_index(
        "idx_event_sector_impacts_sector", "event_sector_impacts", ["sector"]
    )


def downgrade() -> None:
    op.drop_table("event_sector_impacts")
    op.drop_table("global_events")
