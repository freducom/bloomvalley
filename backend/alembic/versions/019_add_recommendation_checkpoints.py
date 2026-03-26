"""Add recommendation_checkpoints table for accuracy tracking.

Revision ID: 932b5c71de45
Revises: 018
"""

import sqlalchemy as sa
from alembic import op

revision = "932b5c71de45"
down_revision = "018"


def upgrade() -> None:
    op.create_table(
        "recommendation_checkpoints",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "recommendation_id",
            sa.Integer,
            sa.ForeignKey("recommendations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("days_elapsed", sa.Integer, nullable=False),
        sa.Column("check_date", sa.Date, nullable=False),
        sa.Column("price_at_check_cents", sa.BigInteger, nullable=True),
        sa.Column("return_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("was_correct", sa.Boolean, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("recommendation_id", "days_elapsed", name="uq_rec_checkpoints_rec_days"),
    )
    op.create_index(
        "idx_rec_checkpoints_rec_id",
        "recommendation_checkpoints",
        ["recommendation_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_rec_checkpoints_rec_id", table_name="recommendation_checkpoints")
    op.drop_table("recommendation_checkpoints")
