"""Add sec_edgar, quiver, gdelt to pipeline_runs_source_enum.

Revision ID: 013
Revises: 012
"""

from alembic import op

revision = "013"
down_revision = "012"


def upgrade() -> None:
    op.execute("ALTER TYPE pipeline_runs_source_enum ADD VALUE IF NOT EXISTS 'sec_edgar'")
    op.execute("ALTER TYPE pipeline_runs_source_enum ADD VALUE IF NOT EXISTS 'quiver'")
    op.execute("ALTER TYPE pipeline_runs_source_enum ADD VALUE IF NOT EXISTS 'gdelt'")


def downgrade() -> None:
    # PostgreSQL doesn't support removing values from enums
    pass
