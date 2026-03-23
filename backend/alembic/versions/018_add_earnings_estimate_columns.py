"""Add earnings estimate and surprise columns to earnings_reports.

Revision ID: 018
Revises: 017
"""

import sqlalchemy as sa
from alembic import op

revision = "018"
down_revision = "017"


def upgrade() -> None:
    op.add_column("earnings_reports", sa.Column("eps_estimate_cents", sa.Integer, nullable=True))
    op.add_column("earnings_reports", sa.Column("revenue_estimate_cents", sa.BigInteger, nullable=True))
    op.add_column("earnings_reports", sa.Column("surprise_pct", sa.Numeric(8, 2), nullable=True))
    op.execute("ALTER TYPE pipeline_runs_source_enum ADD VALUE IF NOT EXISTS 'finnhub'")


def downgrade() -> None:
    op.drop_column("earnings_reports", "surprise_pct")
    op.drop_column("earnings_reports", "revenue_estimate_cents")
    op.drop_column("earnings_reports", "eps_estimate_cents")
