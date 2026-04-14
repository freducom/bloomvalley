"""Add company_group column to securities for grouping share classes.

Securities with the same company_group value (e.g. "Kesko") are treated as
one company in portfolio analysis — weights, exposure, and analyst reports
aggregate across share classes.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
"""

from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"


def upgrade() -> None:
    op.add_column(
        "securities",
        sa.Column("company_group", sa.String(100), nullable=True),
    )
    op.create_index(
        "idx_securities_company_group",
        "securities",
        ["company_group"],
        unique=False,
        postgresql_where=sa.text("company_group IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_securities_company_group", table_name="securities")
    op.drop_column("securities", "company_group")
