"""Add deployment_plans and deployment_tranches tables for capital deployment timeline.

Revision ID: a1b2c3d4e5f6
Revises: 932b5c71de45
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "a1b2c3d4e5f6"
down_revision = "932b5c71de45"


def upgrade() -> None:
    op.create_table(
        "deployment_plans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("total_amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("strategy_notes", sa.Text(), nullable=True),
        sa.Column("macro_regime_at_creation", sa.String(50), nullable=True),
        sa.Column("next_review_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_deployment_plans_status", "deployment_plans", ["status"])

    op.create_table(
        "deployment_tranches",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("plan_id", sa.BigInteger(), sa.ForeignKey("deployment_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quarter_label", sa.String(10), nullable=False),
        sa.Column("planned_date", sa.Date(), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("core_allocation_pct", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("conviction_allocation_pct", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("cash_buffer_pct", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("candidate_tickers", JSONB(), nullable=True),
        sa.Column("conditional_triggers", JSONB(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="planned"),
        sa.Column("executed_date", sa.Date(), nullable=True),
        sa.Column("executed_amount_cents", sa.BigInteger(), nullable=True),
        sa.Column("execution_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_deployment_tranches_plan_id", "deployment_tranches", ["plan_id"])
    op.create_index("idx_deployment_tranches_status", "deployment_tranches", ["status"])
    op.create_index("idx_deployment_tranches_planned_date", "deployment_tranches", ["planned_date"])


def downgrade() -> None:
    op.drop_index("idx_deployment_tranches_planned_date")
    op.drop_index("idx_deployment_tranches_status")
    op.drop_index("idx_deployment_tranches_plan_id")
    op.drop_table("deployment_tranches")
    op.drop_index("idx_deployment_plans_status")
    op.drop_table("deployment_plans")
