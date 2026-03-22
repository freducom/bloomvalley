"""Add ROIC, WACC, FCF yield, Net Debt/EBITDA, dividend yield, margins, EPS, revenue.

Revision ID: 016
Revises: 015
"""

import sqlalchemy as sa
from alembic import op

revision = "016"
down_revision = "015"


def upgrade() -> None:
    op.add_column("security_fundamentals", sa.Column("roic", sa.Numeric(8, 4), nullable=True))
    op.add_column("security_fundamentals", sa.Column("wacc", sa.Numeric(8, 4), nullable=True))
    op.add_column("security_fundamentals", sa.Column("roe", sa.Numeric(8, 4), nullable=True))
    op.add_column("security_fundamentals", sa.Column("fcf_yield", sa.Numeric(8, 4), nullable=True))
    op.add_column("security_fundamentals", sa.Column("net_debt_ebitda", sa.Numeric(10, 4), nullable=True))
    op.add_column("security_fundamentals", sa.Column("dividend_yield", sa.Numeric(8, 4), nullable=True))
    op.add_column("security_fundamentals", sa.Column("eps_cents", sa.BigInteger(), nullable=True))
    op.add_column("security_fundamentals", sa.Column("revenue_cents", sa.BigInteger(), nullable=True))
    op.add_column("security_fundamentals", sa.Column("gross_margin", sa.Numeric(8, 4), nullable=True))
    op.add_column("security_fundamentals", sa.Column("operating_margin", sa.Numeric(8, 4), nullable=True))
    op.add_column("security_fundamentals", sa.Column("net_margin", sa.Numeric(8, 4), nullable=True))
    op.add_column("security_fundamentals", sa.Column("pe_ratio", sa.Numeric(10, 4), nullable=True))
    op.add_column("security_fundamentals", sa.Column("market_cap_cents", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    for col in [
        "roic", "wacc", "roe", "fcf_yield", "net_debt_ebitda", "dividend_yield",
        "eps_cents", "revenue_cents", "gross_margin", "operating_margin",
        "net_margin", "pe_ratio", "market_cap_cents",
    ]:
        op.drop_column("security_fundamentals", col)
