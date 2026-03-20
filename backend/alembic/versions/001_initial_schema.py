"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-03-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM, JSONB

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _try_execute(sql: str) -> None:
    """Execute SQL within a savepoint, silently ignoring errors (used for optional extensions like TimescaleDB)."""
    import sqlalchemy as _sa
    conn = op.get_bind()
    try:
        conn.execute(_sa.text("SAVEPOINT _try"))
        conn.execute(_sa.text(sql))
        conn.execute(_sa.text("RELEASE SAVEPOINT _try"))
    except Exception:
        conn.execute(_sa.text("ROLLBACK TO SAVEPOINT _try"))


def upgrade() -> None:
    # --- Extensions ---
    _try_execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # --- Enum types (using DO blocks for idempotency) ---
    enums = {
        "accounts_type_enum": "('regular', 'osakesaastotili', 'crypto_wallet', 'pension')",
        "accounts_pension_subtype_enum": "('ps_sopimus', 'kapitalisaatiosopimus')",
        "securities_asset_class_enum": "('stock', 'bond', 'etf', 'crypto')",
        "transactions_type_enum": "('buy', 'sell', 'dividend', 'transfer_in', 'transfer_out', 'fee', 'interest', 'corporate_action', 'deposit', 'withdrawal')",
        "tax_lots_state_enum": "('open', 'partially_closed', 'closed')",
        "corporate_actions_type_enum": "('split', 'reverse_split', 'merger', 'spinoff', 'name_change', 'ticker_change', 'delisting')",
        "alerts_type_enum": "('price_above', 'price_below', 'drift_threshold', 'staleness', 'dividend_announced', 'custom')",
        "alerts_status_enum": "('active', 'triggered', 'dismissed', 'expired')",
        "pipeline_runs_status_enum": "('running', 'success', 'failed', 'partial')",
        "pipeline_runs_source_enum": "('yahoo_finance', 'alpha_vantage', 'fred', 'ecb', 'coingecko', 'justetf', 'morningstar', 'manual')",
    }
    for name, values in enums.items():
        op.execute(f"""
            DO $$ BEGIN
                CREATE TYPE {name} AS ENUM {values};
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$
        """)

    # --- accounts ---
    op.create_table(
        "accounts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "type",
            ENUM(
                "regular", "osakesaastotili", "crypto_wallet", "pension",
                name="accounts_type_enum", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "pension_subtype",
            ENUM(
                "ps_sopimus", "kapitalisaatiosopimus",
                name="accounts_pension_subtype_enum", create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("institution", sa.String(100), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("osa_deposit_total_cents", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "(type = 'pension' AND pension_subtype IS NOT NULL) OR "
            "(type != 'pension' AND pension_subtype IS NULL)",
            name="chk_accounts_pension_subtype",
        ),
        sa.CheckConstraint(
            "(type = 'osakesaastotili' AND osa_deposit_total_cents >= 0 "
            "AND osa_deposit_total_cents <= 5000000) OR "
            "(type != 'osakesaastotili' AND osa_deposit_total_cents = 0)",
            name="chk_accounts_osa_deposit",
        ),
        sa.CheckConstraint("currency = upper(currency)", name="chk_accounts_currency_upper"),
    )
    op.create_index("idx_accounts_type", "accounts", ["type"])
    op.execute("CREATE INDEX idx_accounts_is_active ON accounts (is_active) WHERE is_active = TRUE")

    # --- securities ---
    op.create_table(
        "securities",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(20), nullable=False),
        sa.Column("isin", sa.String(12), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "asset_class",
            ENUM("stock", "bond", "etf", "crypto", name="securities_asset_class_enum", create_type=False),
            nullable=False,
        ),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("exchange", sa.String(20), nullable=True),
        sa.Column("sector", sa.String(100), nullable=True),
        sa.Column("industry", sa.String(100), nullable=True),
        sa.Column("country", sa.String(2), nullable=True),
        sa.Column("is_accumulating", sa.Boolean, nullable=True),
        sa.Column("coingecko_id", sa.String(100), nullable=True),
        sa.Column("openfigi", sa.String(12), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("currency = upper(currency)", name="chk_securities_currency_upper"),
    )
    op.execute(
        "CREATE UNIQUE INDEX idx_securities_ticker_exchange "
        "ON securities (ticker, exchange) WHERE exchange IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX idx_securities_ticker_crypto "
        "ON securities (ticker) WHERE asset_class = 'crypto'"
    )
    op.execute(
        "CREATE UNIQUE INDEX idx_securities_isin "
        "ON securities (isin) WHERE isin IS NOT NULL"
    )
    op.create_index("idx_securities_asset_class", "securities", ["asset_class"])
    op.execute(
        "CREATE INDEX idx_securities_name_trgm ON securities USING gin (name gin_trgm_ops)"
    )

    # --- transactions ---
    op.create_table(
        "transactions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.BigInteger, sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("security_id", sa.BigInteger, sa.ForeignKey("securities.id"), nullable=True),
        sa.Column(
            "type",
            ENUM(
                "buy", "sell", "dividend", "transfer_in", "transfer_out",
                "fee", "interest", "corporate_action", "deposit", "withdrawal",
                name="transactions_type_enum", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("trade_date", sa.Date, nullable=False),
        sa.Column("settlement_date", sa.Date, nullable=True),
        sa.Column("quantity", sa.Numeric(28, 18), nullable=False, server_default="0"),
        sa.Column("price_cents", sa.BigInteger, nullable=True),
        sa.Column("price_currency", sa.String(3), nullable=True),
        sa.Column("total_cents", sa.BigInteger, nullable=False),
        sa.Column("fee_cents", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("fee_currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("fx_rate", sa.Numeric(12, 6), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("withholding_tax_cents", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("external_ref", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("currency = upper(currency)", name="chk_transactions_currency_upper"),
        sa.CheckConstraint("fee_cents >= 0", name="chk_transactions_fee_non_negative"),
        sa.CheckConstraint("withholding_tax_cents >= 0", name="chk_transactions_withholding_non_negative"),
    )
    op.create_index("idx_transactions_account_id", "transactions", ["account_id"])
    op.create_index("idx_transactions_security_id", "transactions", ["security_id"])
    op.create_index("idx_transactions_trade_date", "transactions", ["trade_date"])
    op.create_index("idx_transactions_type", "transactions", ["type"])
    op.create_index(
        "idx_transactions_account_security_date",
        "transactions",
        ["account_id", "security_id", "trade_date"],
    )

    # --- tax_lots ---
    op.create_table(
        "tax_lots",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.BigInteger, sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("security_id", sa.BigInteger, sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("open_transaction_id", sa.BigInteger, sa.ForeignKey("transactions.id"), nullable=False),
        sa.Column("close_transaction_id", sa.BigInteger, sa.ForeignKey("transactions.id"), nullable=True),
        sa.Column(
            "state",
            ENUM("open", "partially_closed", "closed", name="tax_lots_state_enum", create_type=False),
            nullable=False,
            server_default="open",
        ),
        sa.Column("acquired_date", sa.Date, nullable=False),
        sa.Column("closed_date", sa.Date, nullable=True),
        sa.Column("original_quantity", sa.Numeric(28, 18), nullable=False),
        sa.Column("remaining_quantity", sa.Numeric(28, 18), nullable=False),
        sa.Column("cost_basis_cents", sa.BigInteger, nullable=False),
        sa.Column("cost_basis_currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("proceeds_cents", sa.BigInteger, nullable=True),
        sa.Column("realized_pnl_cents", sa.BigInteger, nullable=True),
        sa.Column("fx_rate_at_open", sa.Numeric(12, 6), nullable=True),
        sa.Column("fx_rate_at_close", sa.Numeric(12, 6), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "original_quantity > 0 AND remaining_quantity >= 0",
            name="chk_tax_lots_quantity_positive",
        ),
        sa.CheckConstraint(
            "remaining_quantity <= original_quantity",
            name="chk_tax_lots_remaining_lte_original",
        ),
        sa.CheckConstraint(
            "(state = 'closed' AND closed_date IS NOT NULL) OR (state != 'closed')",
            name="chk_tax_lots_closed_has_date",
        ),
    )
    op.create_index("idx_tax_lots_account_id", "tax_lots", ["account_id"])
    op.create_index("idx_tax_lots_security_id", "tax_lots", ["security_id"])
    op.create_index("idx_tax_lots_state", "tax_lots", ["state"])
    op.create_index("idx_tax_lots_open_transaction_id", "tax_lots", ["open_transaction_id"])
    op.create_index(
        "idx_tax_lots_account_security_state",
        "tax_lots",
        ["account_id", "security_id", "state"],
    )
    op.create_index("idx_tax_lots_acquired_date", "tax_lots", ["acquired_date"])

    # --- prices (hypertable) ---
    op.create_table(
        "prices",
        sa.Column("security_id", sa.BigInteger, sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("open_cents", sa.BigInteger, nullable=True),
        sa.Column("high_cents", sa.BigInteger, nullable=True),
        sa.Column("low_cents", sa.BigInteger, nullable=True),
        sa.Column("close_cents", sa.BigInteger, nullable=False),
        sa.Column("adjusted_close_cents", sa.BigInteger, nullable=True),
        sa.Column("volume", sa.BigInteger, nullable=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "source",
            ENUM(
                "yahoo_finance", "alpha_vantage", "fred", "ecb",
                "coingecko", "justetf", "morningstar", "manual",
                name="pipeline_runs_source_enum", create_type=False,
            ),
            nullable=False,
            server_default="yahoo_finance",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "high_cents >= low_cents "
            "AND high_cents >= open_cents "
            "AND high_cents >= close_cents "
            "AND low_cents <= open_cents "
            "AND low_cents <= close_cents",
            name="chk_prices_ohlc",
        ),
    )
    _try_execute("SELECT create_hypertable('prices', 'date', chunk_time_interval => INTERVAL '1 month')")
    op.execute("CREATE UNIQUE INDEX idx_prices_security_id_date ON prices (security_id, date)")
    op.execute("CREATE INDEX idx_prices_date ON prices (date DESC)")
    op.create_index("idx_prices_security_id", "prices", ["security_id"])

    # --- fx_rates (hypertable) ---
    op.create_table(
        "fx_rates",
        sa.Column("base_currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("quote_currency", sa.String(3), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("rate", sa.Numeric(12, 6), nullable=False),
        sa.Column(
            "source",
            ENUM(
                "yahoo_finance", "alpha_vantage", "fred", "ecb",
                "coingecko", "justetf", "morningstar", "manual",
                name="pipeline_runs_source_enum", create_type=False,
            ),
            nullable=False,
            server_default="ecb",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("rate > 0", name="chk_fx_rates_rate_positive"),
        sa.CheckConstraint("base_currency = 'EUR'", name="chk_fx_rates_base_eur"),
    )
    _try_execute("SELECT create_hypertable('fx_rates', 'date', chunk_time_interval => INTERVAL '1 month')")
    op.execute(
        "CREATE UNIQUE INDEX idx_fx_rates_pair_date "
        "ON fx_rates (base_currency, quote_currency, date)"
    )
    op.create_index("idx_fx_rates_quote_currency", "fx_rates", ["quote_currency"])
    op.execute("CREATE INDEX idx_fx_rates_date ON fx_rates (date DESC)")

    # --- macro_indicators (hypertable) ---
    op.create_table(
        "macro_indicators",
        sa.Column("indicator_code", sa.String(50), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("value", sa.Numeric(18, 6), nullable=False),
        sa.Column("unit", sa.String(20), nullable=True),
        sa.Column(
            "source",
            ENUM(
                "yahoo_finance", "alpha_vantage", "fred", "ecb",
                "coingecko", "justetf", "morningstar", "manual",
                name="pipeline_runs_source_enum", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    _try_execute(
        "SELECT create_hypertable('macro_indicators', 'date', chunk_time_interval => INTERVAL '3 months')"
    )
    op.execute(
        "CREATE UNIQUE INDEX idx_macro_indicators_code_date "
        "ON macro_indicators (indicator_code, date)"
    )
    op.create_index("idx_macro_indicators_code", "macro_indicators", ["indicator_code"])
    op.execute("CREATE INDEX idx_macro_indicators_date ON macro_indicators (date DESC)")

    # --- dividends ---
    op.create_table(
        "dividends",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.BigInteger, sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("security_id", sa.BigInteger, sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("transaction_id", sa.BigInteger, sa.ForeignKey("transactions.id"), nullable=True),
        sa.Column("ex_date", sa.Date, nullable=False),
        sa.Column("pay_date", sa.Date, nullable=True),
        sa.Column("record_date", sa.Date, nullable=True),
        sa.Column("amount_per_share_cents", sa.BigInteger, nullable=False),
        sa.Column("amount_currency", sa.String(3), nullable=False),
        sa.Column("shares_held", sa.Numeric(18, 8), nullable=False),
        sa.Column("gross_amount_cents", sa.BigInteger, nullable=False),
        sa.Column("withholding_tax_cents", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("withholding_tax_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("net_amount_cents", sa.BigInteger, nullable=False),
        sa.Column("net_amount_eur_cents", sa.BigInteger, nullable=False),
        sa.Column("fx_rate", sa.Numeric(12, 6), nullable=True),
        sa.Column("is_qualified", sa.Boolean, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "net_amount_cents = gross_amount_cents - withholding_tax_cents",
            name="chk_dividends_net_amount",
        ),
    )
    op.create_index("idx_dividends_account_id", "dividends", ["account_id"])
    op.create_index("idx_dividends_security_id", "dividends", ["security_id"])
    op.create_index("idx_dividends_ex_date", "dividends", ["ex_date"])
    op.create_index(
        "idx_dividends_account_security_ex_date",
        "dividends",
        ["account_id", "security_id", "ex_date"],
    )

    # --- corporate_actions ---
    op.create_table(
        "corporate_actions",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("security_id", sa.BigInteger, sa.ForeignKey("securities.id"), nullable=False),
        sa.Column(
            "type",
            ENUM(
                "split", "reverse_split", "merger", "spinoff",
                "name_change", "ticker_change", "delisting",
                name="corporate_actions_type_enum", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("effective_date", sa.Date, nullable=False),
        sa.Column("ratio_from", sa.Numeric(12, 6), nullable=True),
        sa.Column("ratio_to", sa.Numeric(12, 6), nullable=True),
        sa.Column("new_security_id", sa.BigInteger, sa.ForeignKey("securities.id"), nullable=True),
        sa.Column("cash_in_lieu_cents", sa.BigInteger, nullable=True),
        sa.Column("cash_currency", sa.String(3), nullable=True),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("is_processed", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "(type IN ('split', 'reverse_split') "
            "AND ratio_from IS NOT NULL AND ratio_to IS NOT NULL) OR "
            "(type NOT IN ('split', 'reverse_split'))",
            name="chk_corporate_actions_ratio",
        ),
    )
    op.create_index("idx_corporate_actions_security_id", "corporate_actions", ["security_id"])
    op.create_index("idx_corporate_actions_effective_date", "corporate_actions", ["effective_date"])
    op.execute(
        "CREATE INDEX idx_corporate_actions_is_processed "
        "ON corporate_actions (is_processed) WHERE is_processed = FALSE"
    )

    # --- holdings_snapshot ---
    op.create_table(
        "holdings_snapshot",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("snapshot_date", sa.Date, nullable=False),
        sa.Column("account_id", sa.BigInteger, sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("security_id", sa.BigInteger, sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("quantity", sa.Numeric(28, 18), nullable=False),
        sa.Column("cost_basis_cents", sa.BigInteger, nullable=False),
        sa.Column("cost_basis_currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("market_price_cents", sa.BigInteger, nullable=False),
        sa.Column("market_price_currency", sa.String(3), nullable=False),
        sa.Column("market_value_eur_cents", sa.BigInteger, nullable=False),
        sa.Column("unrealized_pnl_eur_cents", sa.BigInteger, nullable=False),
        sa.Column("fx_rate", sa.Numeric(12, 6), nullable=True),
        sa.Column("weight_pct", sa.Numeric(7, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.execute(
        "CREATE UNIQUE INDEX idx_holdings_snapshot_date_account_security "
        "ON holdings_snapshot (snapshot_date, account_id, security_id)"
    )
    op.create_index("idx_holdings_snapshot_date", "holdings_snapshot", ["snapshot_date"])
    op.create_index("idx_holdings_snapshot_security_id", "holdings_snapshot", ["security_id"])

    # --- watchlists ---
    op.create_table(
        "watchlists",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- watchlist_items ---
    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "watchlist_id",
            sa.BigInteger,
            sa.ForeignKey("watchlists.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("security_id", sa.BigInteger, sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("watchlist_id", "security_id", name="uq_watchlist_items_watchlist_security"),
    )
    op.create_index("idx_watchlist_items_watchlist_id", "watchlist_items", ["watchlist_id"])
    op.create_index("idx_watchlist_items_security_id", "watchlist_items", ["security_id"])

    # --- research_notes ---
    op.create_table(
        "research_notes",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("security_id", sa.BigInteger, sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("thesis", sa.Text, nullable=True),
        sa.Column("bull_case", sa.Text, nullable=True),
        sa.Column("bear_case", sa.Text, nullable=True),
        sa.Column("base_case", sa.Text, nullable=True),
        sa.Column("intrinsic_value_cents", sa.BigInteger, nullable=True),
        sa.Column("intrinsic_value_currency", sa.String(3), nullable=True),
        sa.Column("margin_of_safety_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("moat_rating", sa.String(20), nullable=True),
        sa.Column("tags", sa.ARRAY(sa.Text), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_research_notes_security_id", "research_notes", ["security_id"])
    op.execute("CREATE INDEX idx_research_notes_tags ON research_notes USING gin (tags)")
    op.execute(
        "CREATE INDEX idx_research_notes_is_active "
        "ON research_notes (is_active) WHERE is_active = TRUE"
    )

    # --- alerts ---
    op.create_table(
        "alerts",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "type",
            ENUM(
                "price_above", "price_below", "drift_threshold",
                "staleness", "dividend_announced", "custom",
                name="alerts_type_enum", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            ENUM(
                "active", "triggered", "dismissed", "expired",
                name="alerts_status_enum", create_type=False,
            ),
            nullable=False,
            server_default="active",
        ),
        sa.Column("security_id", sa.BigInteger, sa.ForeignKey("securities.id"), nullable=True),
        sa.Column("account_id", sa.BigInteger, sa.ForeignKey("accounts.id"), nullable=True),
        sa.Column("threshold_value", sa.Numeric(18, 6), nullable=True),
        sa.Column("threshold_currency", sa.String(3), nullable=True),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_alerts_status", "alerts", ["status"])
    op.create_index("idx_alerts_security_id", "alerts", ["security_id"])
    op.create_index("idx_alerts_type_status", "alerts", ["type", "status"])
    op.execute("CREATE INDEX idx_alerts_active ON alerts (status) WHERE status = 'active'")

    # --- esg_scores ---
    op.create_table(
        "esg_scores",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("security_id", sa.BigInteger, sa.ForeignKey("securities.id"), nullable=False),
        sa.Column("as_of_date", sa.Date, nullable=False),
        sa.Column("environment_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("social_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("governance_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("total_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("controversy_level", sa.String(20), nullable=True),
        sa.Column("controversy_details", sa.Text, nullable=True),
        sa.Column("eu_taxonomy_aligned", sa.Boolean, nullable=True),
        sa.Column("sfdr_classification", sa.String(20), nullable=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.execute(
        "CREATE UNIQUE INDEX idx_esg_scores_security_date "
        "ON esg_scores (security_id, as_of_date)"
    )
    op.create_index("idx_esg_scores_security_id", "esg_scores", ["security_id"])
    op.create_index("idx_esg_scores_as_of_date", "esg_scores", ["as_of_date"])

    # --- pipeline_runs ---
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "source",
            ENUM(
                "yahoo_finance", "alpha_vantage", "fred", "ecb",
                "coingecko", "justetf", "morningstar", "manual",
                name="pipeline_runs_source_enum", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("pipeline_name", sa.String(100), nullable=False),
        sa.Column(
            "status",
            ENUM(
                "running", "success", "failed", "partial",
                name="pipeline_runs_status_enum", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("rows_affected", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "(finished_at IS NOT NULL AND duration_ms IS NOT NULL AND duration_ms >= 0) OR "
            "(finished_at IS NULL AND duration_ms IS NULL)",
            name="chk_pipeline_runs_duration",
        ),
    )
    op.create_index("idx_pipeline_runs_source", "pipeline_runs", ["source"])
    op.create_index("idx_pipeline_runs_status", "pipeline_runs", ["status"])
    op.execute("CREATE INDEX idx_pipeline_runs_started_at ON pipeline_runs (started_at DESC)")
    op.execute("CREATE INDEX idx_pipeline_runs_source_started ON pipeline_runs (source, started_at DESC)")


def downgrade() -> None:
    # Drop tables in reverse order of creation (respecting FK dependencies)
    op.drop_table("pipeline_runs")
    op.drop_table("esg_scores")
    op.drop_table("alerts")
    op.drop_table("research_notes")
    op.drop_table("watchlist_items")
    op.drop_table("watchlists")
    op.drop_table("holdings_snapshot")
    op.drop_table("corporate_actions")
    op.drop_table("dividends")
    op.drop_table("macro_indicators")
    op.drop_table("fx_rates")
    op.drop_table("prices")
    op.drop_table("tax_lots")
    op.drop_table("transactions")
    op.drop_table("securities")
    op.drop_table("accounts")

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS pipeline_runs_source_enum")
    op.execute("DROP TYPE IF EXISTS pipeline_runs_status_enum")
    op.execute("DROP TYPE IF EXISTS alerts_status_enum")
    op.execute("DROP TYPE IF EXISTS alerts_type_enum")
    op.execute("DROP TYPE IF EXISTS corporate_actions_type_enum")
    op.execute("DROP TYPE IF EXISTS tax_lots_state_enum")
    op.execute("DROP TYPE IF EXISTS transactions_type_enum")
    op.execute("DROP TYPE IF EXISTS securities_asset_class_enum")
    op.execute("DROP TYPE IF EXISTS accounts_pension_subtype_enum")
    op.execute("DROP TYPE IF EXISTS accounts_type_enum")

    # Drop extensions
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    _try_execute("DROP EXTENSION IF EXISTS timescaledb")
