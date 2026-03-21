"""Add security_fundamentals and earnings_reports tables.

Revision ID: 012
Revises: 011
"""
from alembic import op
import sqlalchemy as sa

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security_fundamentals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id", ondelete="CASCADE"), nullable=False, unique=True),
        # Valuation
        sa.Column("price_to_book", sa.Numeric(10, 4), nullable=True),
        sa.Column("free_cash_flow_cents", sa.BigInteger(), nullable=True),
        sa.Column("fcf_currency", sa.String(3), nullable=True),
        sa.Column("dcf_value_cents", sa.BigInteger(), nullable=True),
        sa.Column("dcf_discount_rate", sa.Numeric(6, 4), nullable=True),
        sa.Column("dcf_terminal_growth", sa.Numeric(6, 4), nullable=True),
        sa.Column("dcf_model_notes", sa.Text(), nullable=True),
        # Short interest
        sa.Column("short_interest_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("short_interest_change_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("short_squeeze_risk", sa.String(10), nullable=True),
        sa.Column("days_to_cover", sa.Numeric(8, 2), nullable=True),
        # Institutional / Smart money
        sa.Column("institutional_ownership_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("institutional_flow", sa.String(20), nullable=True),
        sa.Column("smart_money_signal", sa.Text(), nullable=True),
        sa.Column("smart_money_outlook_days", sa.Integer(), nullable=True, server_default="90"),
        # Timestamps
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_security_fundamentals_security_id", "security_fundamentals", ["security_id"], unique=True)

    op.create_table(
        "earnings_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("security_id", sa.Integer(), sa.ForeignKey("securities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fiscal_quarter", sa.String(10), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("quarter", sa.Integer(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=True),
        # Financials
        sa.Column("revenue_cents", sa.BigInteger(), nullable=True),
        sa.Column("revenue_currency", sa.String(3), nullable=True),
        sa.Column("revenue_yoy_pct", sa.Numeric(8, 2), nullable=True),
        sa.Column("eps_cents", sa.Integer(), nullable=True),
        sa.Column("eps_yoy_pct", sa.Numeric(8, 2), nullable=True),
        sa.Column("gross_margin_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("operating_margin_pct", sa.Numeric(6, 2), nullable=True),
        # Qualitative
        sa.Column("forward_guidance", sa.Text(), nullable=True),
        sa.Column("red_flags", sa.Text(), nullable=True),
        sa.Column("recommendation", sa.String(10), nullable=True),
        sa.Column("recommendation_reasoning", sa.Text(), nullable=True),
        # Meta
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_earnings_reports_security_id", "earnings_reports", ["security_id"])
    op.create_index("idx_earnings_reports_quarter", "earnings_reports", ["security_id", "fiscal_year", "quarter"], unique=True)


def downgrade() -> None:
    op.drop_table("earnings_reports")
    op.drop_table("security_fundamentals")
