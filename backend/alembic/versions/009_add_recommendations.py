"""Add recommendations table for tracking buy/sell/hold calls with retrospective analysis.

Revision ID: 009
Revises: 008
"""
from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recommendations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("confidence", sa.String(10), nullable=False),
        sa.Column("target_price_cents", sa.BigInteger(), nullable=True),
        sa.Column("entry_price_cents", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("bull_case", sa.Text(), nullable=True),
        sa.Column("bear_case", sa.Text(), nullable=True),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("time_horizon", sa.String(10), nullable=True),
        sa.Column("status", sa.String(10), nullable=False, server_default="active"),
        sa.Column("recommended_date", sa.Date(), nullable=False),
        sa.Column("closed_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("exit_price_cents", sa.BigInteger(), nullable=True),
        sa.Column("return_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("outcome_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_recommendations_security_id", "recommendations", ["security_id"])
    op.create_index("idx_recommendations_status", "recommendations", ["status"])
    op.create_index("idx_recommendations_date", "recommendations", ["recommended_date"])


def downgrade() -> None:
    op.drop_table("recommendations")
