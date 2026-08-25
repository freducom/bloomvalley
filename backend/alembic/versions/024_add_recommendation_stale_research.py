"""Add stale_research flag to recommendations.

Recommendations for stocks whose per-security research-analyst note is older
than 7 days (or missing) are flagged with stale_research=true. Rule targets
stocks only; non-stock asset classes (crypto, ETFs) are always false because
the research-analyst pipeline skips them by design.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
"""

from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"


def upgrade() -> None:
    op.add_column(
        "recommendations",
        sa.Column(
            "stale_research",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("recommendations", "stale_research")
