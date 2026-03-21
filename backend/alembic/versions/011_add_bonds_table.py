"""Add bonds table for fixed income tracking.

Revision ID: 011
Revises: 010
"""
from alembic import op
import sqlalchemy as sa

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bonds",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("issuer", sa.String(255), nullable=False),
        sa.Column("issuer_type", sa.String(20), nullable=False, server_default="government"),
        sa.Column("coupon_rate", sa.Numeric(8, 5), nullable=True),
        sa.Column("coupon_frequency", sa.String(20), nullable=False, server_default="annual"),
        sa.Column("face_value_cents", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("maturity_date", sa.Date(), nullable=False),
        sa.Column("call_date", sa.Date(), nullable=True),
        sa.Column("purchase_price_cents", sa.BigInteger(), nullable=True),
        sa.Column("purchase_date", sa.Date(), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False, server_default="1"),
        sa.Column("yield_to_maturity", sa.Numeric(8, 5), nullable=True),
        sa.Column("current_yield", sa.Numeric(8, 5), nullable=True),
        sa.Column("credit_rating", sa.String(10), nullable=True),
        sa.Column("rating_agency", sa.String(50), nullable=True),
        sa.Column("is_inflation_linked", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_callable", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_bonds_security_id", "bonds", ["security_id"], unique=True)
    op.create_index("idx_bonds_maturity_date", "bonds", ["maturity_date"])
    op.create_index("idx_bonds_issuer_type", "bonds", ["issuer_type"])


def downgrade() -> None:
    op.drop_table("bonds")
