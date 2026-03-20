"""Add imports and import_rows tables for Nordnet import.

Revision ID: 002
Revises: 001
Create Date: 2026-03-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM, JSONB

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enums
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE imports_status_enum AS ENUM (
                'parsing', 'parsed', 'confirmed', 'cancelled', 'failed'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE import_rows_match_status_enum AS ENUM (
                'auto_matched', 'ticker_matched', 'manual_mapped', 'unrecognized', 'skipped'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE import_rows_action_enum AS ENUM (
                'transfer_in', 'buy', 'sell', 'skip'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)

    op.create_table(
        "imports",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="nordnet"),
        sa.Column(
            "status",
            ENUM(
                "parsing", "parsed", "confirmed", "cancelled", "failed",
                name="imports_status_enum", create_type=False,
            ),
            nullable=False,
            server_default="parsing",
        ),
        sa.Column("account_id", sa.BigInteger, sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column("total_rows", sa.Integer, nullable=False, server_default="0"),
        sa.Column("matched_rows", sa.Integer, nullable=False, server_default="0"),
        sa.Column("unmatched_rows", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "import_rows",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "import_id",
            sa.BigInteger,
            sa.ForeignKey("imports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_number", sa.Integer, nullable=False),
        sa.Column("raw_data", JSONB, nullable=False),
        # Parsed fields
        sa.Column("parsed_ticker", sa.String(50), nullable=True),
        sa.Column("parsed_isin", sa.String(12), nullable=True),
        sa.Column("parsed_name", sa.String(200), nullable=True),
        sa.Column("parsed_quantity", sa.Numeric(28, 18), nullable=True),
        sa.Column("parsed_avg_price_cents", sa.BigInteger, nullable=True),
        sa.Column("parsed_market_value_cents", sa.BigInteger, nullable=True),
        sa.Column("parsed_currency", sa.String(3), nullable=True),
        sa.Column("parsed_account_type", sa.String(50), nullable=True),
        # Matching
        sa.Column(
            "match_status",
            ENUM(
                "auto_matched", "ticker_matched", "manual_mapped", "unrecognized", "skipped",
                name="import_rows_match_status_enum", create_type=False,
            ),
            nullable=False,
            server_default="unrecognized",
        ),
        sa.Column(
            "action",
            ENUM(
                "transfer_in", "buy", "sell", "skip",
                name="import_rows_action_enum", create_type=False,
            ),
            nullable=False,
            server_default="transfer_in",
        ),
        sa.Column("security_id", sa.BigInteger, sa.ForeignKey("securities.id"), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_index("idx_import_rows_import_id", "import_rows", ["import_id"])
    op.create_index("idx_imports_status", "imports", ["status"])


def downgrade() -> None:
    op.drop_table("import_rows")
    op.drop_table("imports")
    op.execute("DROP TYPE IF EXISTS import_rows_action_enum")
    op.execute("DROP TYPE IF EXISTS import_rows_match_status_enum")
    op.execute("DROP TYPE IF EXISTS imports_status_enum")
