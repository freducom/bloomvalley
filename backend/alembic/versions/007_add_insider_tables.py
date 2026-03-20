"""Add insider_trades, congress_trades, and buyback_programs tables.

Revision ID: 007
Revises: 006
"""
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"


def upgrade() -> None:
    op.create_table(
        "insider_trades",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("security_id", sa.BigInteger, sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("insider_name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("trade_type", sa.String(20), nullable=False),
        sa.Column("jurisdiction", sa.String(5), nullable=False),
        sa.Column("trade_date", sa.Date, nullable=False),
        sa.Column("disclosure_date", sa.Date, nullable=False),
        sa.Column("shares", sa.Numeric(18, 8), nullable=False),
        sa.Column("price_cents", sa.BigInteger, nullable=True),
        sa.Column("value_cents", sa.BigInteger, nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("shares_after", sa.Numeric(18, 8), nullable=True),
        sa.Column("source_url", sa.Text, nullable=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("is_significant", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_insider_trades_security_id", "insider_trades", ["security_id"])
    op.create_index("idx_insider_trades_trade_date", "insider_trades", [sa.text("trade_date DESC")])
    op.create_index("idx_insider_trades_jurisdiction", "insider_trades", ["jurisdiction"])
    op.create_index(
        "idx_insider_trades_is_significant", "insider_trades", ["is_significant"],
        postgresql_where=sa.text("is_significant = TRUE"),
    )

    op.create_table(
        "congress_trades",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("security_id", sa.BigInteger, sa.ForeignKey("securities.id"), nullable=True),
        sa.Column("member_name", sa.String(255), nullable=False),
        sa.Column("party", sa.String(20), nullable=False),
        sa.Column("chamber", sa.String(10), nullable=False),
        sa.Column("state", sa.String(2), nullable=True),
        sa.Column("trade_type", sa.String(20), nullable=False),
        sa.Column("trade_date", sa.Date, nullable=False),
        sa.Column("disclosure_date", sa.Date, nullable=False),
        sa.Column("amount_range_low_cents", sa.BigInteger, nullable=False),
        sa.Column("amount_range_high_cents", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("ticker_reported", sa.String(20), nullable=False),
        sa.Column("asset_description", sa.String(500), nullable=True),
        sa.Column("source_url", sa.Text, nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="quiver_quantitative"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_congress_trades_security_id", "congress_trades", ["security_id"])
    op.create_index("idx_congress_trades_trade_date", "congress_trades", [sa.text("trade_date DESC")])
    op.create_index("idx_congress_trades_member_name", "congress_trades", ["member_name"])

    op.create_table(
        "buyback_programs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("security_id", sa.BigInteger, sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("announced_date", sa.Date, nullable=False),
        sa.Column("start_date", sa.Date, nullable=True),
        sa.Column("end_date", sa.Date, nullable=True),
        sa.Column("authorized_amount_cents", sa.BigInteger, nullable=True),
        sa.Column("authorized_shares", sa.BigInteger, nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("executed_amount_cents", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("executed_shares", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="announced"),
        sa.Column("source_url", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_buyback_programs_security_id", "buyback_programs", ["security_id"])
    op.create_index("idx_buyback_programs_status", "buyback_programs", ["status"])


def downgrade() -> None:
    op.drop_table("buyback_programs")
    op.drop_table("congress_trades")
    op.drop_table("insider_trades")
