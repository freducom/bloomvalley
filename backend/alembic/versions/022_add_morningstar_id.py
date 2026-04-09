"""Add morningstar_id column to securities for caching Morningstar SecId lookups.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
"""

from alembic import op
import sqlalchemy as sa

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"


def upgrade() -> None:
    op.add_column(
        "securities",
        sa.Column("morningstar_id", sa.String(20), nullable=True),
    )
    op.create_index(
        "idx_securities_morningstar_id",
        "securities",
        ["morningstar_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_securities_morningstar_id", table_name="securities")
    op.drop_column("securities", "morningstar_id")
