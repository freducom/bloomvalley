"""Add dividend_events table for tracking known dividend announcements.

Revision ID: 004
Revises: 003
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"


def upgrade() -> None:
    op.create_table(
        "dividend_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("security_id", sa.BigInteger, sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("ex_date", sa.Date, nullable=False),
        sa.Column("payment_date", sa.Date, nullable=True),
        sa.Column("record_date", sa.Date, nullable=True),
        sa.Column("amount_cents", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("frequency", sa.String(20), nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="yahoo_finance"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("security_id", "ex_date", name="uq_dividend_events_security_ex_date"),
        sa.CheckConstraint("amount_cents > 0", name="chk_dividend_events_amount_positive"),
    )
    op.create_index("idx_dividend_events_security_id", "dividend_events", ["security_id"])
    op.create_index("idx_dividend_events_ex_date", "dividend_events", ["ex_date"])
    op.create_index("idx_dividend_events_payment_date", "dividend_events", ["payment_date"])


def downgrade() -> None:
    op.drop_table("dividend_events")
