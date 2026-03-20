"""Add news_items and news_item_securities tables.

Revision ID: 005
Revises: 004
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"


def upgrade() -> None:
    op.create_table(
        "news_items",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("image_url", sa.Text, nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("is_global", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_bookmarked", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_news_items_published_at", "news_items", [sa.text("published_at DESC")])
    op.create_index("idx_news_items_source", "news_items", ["source"])
    op.create_index(
        "idx_news_items_is_bookmarked",
        "news_items",
        ["is_bookmarked"],
        postgresql_where=sa.text("is_bookmarked = TRUE"),
    )

    op.create_table(
        "news_item_securities",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "news_item_id",
            sa.BigInteger,
            sa.ForeignKey("news_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "security_id",
            sa.BigInteger,
            sa.ForeignKey("securities.id"),
            nullable=False,
        ),
        sa.Column("impact_direction", sa.String(20), nullable=True),
        sa.Column("impact_severity", sa.String(20), nullable=True),
        sa.Column("impact_reasoning", sa.Text, nullable=True),
        sa.UniqueConstraint("news_item_id", "security_id", name="uq_news_item_securities"),
    )
    op.create_index("idx_news_item_securities_security_id", "news_item_securities", ["security_id"])
    op.create_index("idx_news_item_securities_news_item_id", "news_item_securities", ["news_item_id"])


def downgrade() -> None:
    op.drop_table("news_item_securities")
    op.drop_table("news_items")
