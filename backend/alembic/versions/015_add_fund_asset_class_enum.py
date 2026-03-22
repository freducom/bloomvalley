"""Add 'fund' to securities_asset_class_enum for Morningstar pipeline.

Revision ID: 015
Revises: 014
"""

from alembic import op

revision = "015"
down_revision = "014"


def upgrade() -> None:
    op.execute("ALTER TYPE securities_asset_class_enum ADD VALUE IF NOT EXISTS 'fund'")


def downgrade() -> None:
    pass
