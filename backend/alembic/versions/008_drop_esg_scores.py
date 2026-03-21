"""Drop esg_scores table.

Revision ID: 008
Revises: 007
"""
from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("esg_scores")


def downgrade() -> None:
    op.create_table(
        "esg_scores",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("environment_score", sa.Numeric(5, 2)),
        sa.Column("social_score", sa.Numeric(5, 2)),
        sa.Column("governance_score", sa.Numeric(5, 2)),
        sa.Column("total_score", sa.Numeric(5, 2)),
        sa.Column("controversy_level", sa.String(20)),
        sa.Column("controversy_details", sa.Text()),
        sa.Column("eu_taxonomy_aligned", sa.Boolean()),
        sa.Column("sfdr_classification", sa.String(20)),
        sa.Column("source", sa.String(50)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
