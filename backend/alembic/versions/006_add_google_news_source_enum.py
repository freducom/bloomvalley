"""Add google_news to pipeline_runs_source_enum.

Revision ID: 006
Revises: 005
"""
from alembic import op

revision = "006"
down_revision = "005"


def upgrade() -> None:
    op.execute("ALTER TYPE pipeline_runs_source_enum ADD VALUE IF NOT EXISTS 'google_news'")


def downgrade() -> None:
    # Cannot remove enum values in PostgreSQL
    pass
