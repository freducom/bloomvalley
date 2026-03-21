"""Extend alert types and add alert_history table.

Revision ID: 010
Revises: 009
"""
from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new alert types to the enum
    op.execute("ALTER TYPE alerts_type_enum ADD VALUE IF NOT EXISTS 'insider_activity'")
    op.execute("ALTER TYPE alerts_type_enum ADD VALUE IF NOT EXISTS 'risk_breach'")
    op.execute("ALTER TYPE alerts_type_enum ADD VALUE IF NOT EXISTS 'recommendation_expiry'")

    op.create_table(
        "alert_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("alert_id", sa.Integer(), sa.ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("triggered_value", sa.Numeric(18, 6), nullable=True),
        sa.Column("triggered_value_currency", sa.String(3), nullable=True),
        sa.Column("snapshot_data", sa.JSON(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_alert_history_alert_id", "alert_history", ["alert_id"])
    op.create_index("idx_alert_history_triggered_at", "alert_history", ["triggered_at"])


def downgrade() -> None:
    op.drop_table("alert_history")
    # Note: PostgreSQL doesn't support removing enum values
