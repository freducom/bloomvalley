"""Add unique constraint on dividends and index on transactions.external_ref
for dividend auto-reconciliation idempotency.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
"""

from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"


def upgrade() -> None:
    # Unique constraint ensures one dividend record per (account, security, ex_date)
    op.create_unique_constraint(
        "uq_dividends_account_security_ex_date",
        "dividends",
        ["account_id", "security_id", "ex_date"],
    )
    # Index on external_ref for fast idempotency checks
    op.create_index(
        "idx_transactions_external_ref",
        "transactions",
        ["external_ref"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_transactions_external_ref", table_name="transactions")
    op.drop_constraint(
        "uq_dividends_account_security_ex_date", "dividends", type_="unique"
    )
