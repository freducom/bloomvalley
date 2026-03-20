"""Add cash_balance_cents to accounts.

Revision ID: 003
Revises: 002
Create Date: 2026-03-20
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("cash_balance_cents", sa.BigInteger, nullable=False, server_default="0"),
    )
    op.add_column(
        "accounts",
        sa.Column("cash_currency", sa.String(3), nullable=False, server_default="EUR"),
    )


def downgrade() -> None:
    op.drop_column("accounts", "cash_currency")
    op.drop_column("accounts", "cash_balance_cents")
