"""Add 'regional_rss' and 'yahoo_fundamentals' to pipeline_runs_source_enum.

Revision ID: 017
Revises: 016
"""

from alembic import op

revision = "017"
down_revision = "016"


def upgrade() -> None:
    op.execute("ALTER TYPE pipeline_runs_source_enum ADD VALUE IF NOT EXISTS 'regional_rss'")


def downgrade() -> None:
    pass
