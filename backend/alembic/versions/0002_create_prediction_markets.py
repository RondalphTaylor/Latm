"""Create prediction-market ingestion tables.

Revision ID: 0002_prediction_markets
Revises: 0001_system_metadata
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_prediction_markets"
down_revision: str | None = "0001_system_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create provider, market, outcome, and price-snapshot tables."""
    op.create_table(
        "providers",
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("is_read_only", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("name"),
    )
    op.create_table(
        "markets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_name", sa.String(length=50), nullable=False),
        sa.Column("provider_market_id", sa.String(length=200), nullable=False),
        sa.Column("provider_event_id", sa.String(length=200), nullable=True),
        sa.Column("series_ticker", sa.String(length=200), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("market_type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("subtitle", sa.Text(), nullable=True),
        sa.Column("rules_primary", sa.Text(), nullable=True),
        sa.Column("rules_secondary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("is_nba", sa.Boolean(), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("occurrence_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["provider_name"], ["providers.name"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_name",
            "provider_market_id",
            name="uq_markets_provider_market_id",
        ),
    )
    op.create_index("ix_markets_is_nba_status", "markets", ["is_nba", "status"])
    op.create_table(
        "market_outcomes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("market_id", sa.Uuid(), nullable=False),
        sa.Column("provider_outcome_id", sa.String(length=100), nullable=False),
        sa.Column("side", sa.String(length=10), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "market_id",
            "provider_outcome_id",
            name="uq_market_outcomes_provider_outcome_id",
        ),
    )
    op.create_index("ix_market_outcomes_market_id", "market_outcomes", ["market_id"])
    op.create_table(
        "market_prices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("market_id", sa.Uuid(), nullable=False),
        sa.Column("yes_bid", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("yes_ask", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("no_bid", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("no_ask", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("last_price", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("volume", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("volume_24h", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("open_interest", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("liquidity", sa.Numeric(precision=24, scale=4), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("market_id", "retrieved_at", name="uq_market_prices_observation"),
    )
    op.create_index(
        "ix_market_prices_market_retrieved",
        "market_prices",
        ["market_id", "retrieved_at"],
    )


def downgrade() -> None:
    """Drop prediction-market ingestion tables."""
    op.drop_index("ix_market_prices_market_retrieved", table_name="market_prices")
    op.drop_table("market_prices")
    op.drop_index("ix_market_outcomes_market_id", table_name="market_outcomes")
    op.drop_table("market_outcomes")
    op.drop_index("ix_markets_is_nba_status", table_name="markets")
    op.drop_table("markets")
    op.drop_table("providers")
