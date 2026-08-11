"""Create append-only directional opportunity records.

Revision ID: 0006_opportunities
Revises: 0005_base_forecasts
Create Date: 2026-08-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006_opportunities"
down_revision: str | None = "0005_base_forecasts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create immutable YES/NO market-versus-model comparisons."""
    op.create_table(
        "opportunities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("market_id", sa.Uuid(), nullable=False),
        sa.Column("market_price_id", sa.Uuid(), nullable=False),
        sa.Column("market_event_match_id", sa.Uuid(), nullable=False),
        sa.Column("sports_event_id", sa.Uuid(), nullable=False),
        sa.Column("base_forecast_id", sa.Uuid(), nullable=False),
        sa.Column("model_version_id", sa.Uuid(), nullable=False),
        sa.Column("outcome_team_id", sa.Uuid(), nullable=False),
        sa.Column("yes_team_id", sa.Uuid(), nullable=False),
        sa.Column("no_team_id", sa.Uuid(), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("price_source", sa.String(length=30), nullable=False),
        sa.Column("mapping_method", sa.String(length=100), nullable=False),
        sa.Column("orientation_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("market_probability", sa.Numeric(precision=7, scale=6), nullable=False),
        sa.Column("model_probability", sa.Numeric(precision=7, scale=6), nullable=False),
        sa.Column("raw_edge", sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("status_reason", sa.String(length=200), nullable=False),
        sa.Column("strategy_name", sa.String(length=50), nullable=False),
        sa.Column("strategy_version", sa.String(length=100), nullable=False),
        sa.Column("watch_min_raw_edge", sa.Numeric(precision=7, scale=6), nullable=False),
        sa.Column(
            "trade_candidate_min_raw_edge",
            sa.Numeric(precision=7, scale=6),
            nullable=False,
        ),
        sa.Column("max_market_price_age_seconds", sa.Integer(), nullable=False),
        sa.Column(
            "max_operational_forecast_age_seconds",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column("policy_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "source_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("price_retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("forecast_generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price_age_seconds", sa.Integer(), nullable=False),
        sa.Column("forecast_age_seconds", sa.Integer(), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "max_market_price_age_seconds > 0 "
            "AND max_operational_forecast_age_seconds > 0 "
            "AND price_age_seconds >= 0 AND forecast_age_seconds >= 0",
            name="ck_opportunities_ages",
        ),
        sa.CheckConstraint(
            "direction IN ('yes', 'no')",
            name="ck_opportunities_direction",
        ),
        sa.CheckConstraint(
            "length(orientation_fingerprint) = 64 "
            "AND length(policy_fingerprint) = 64 "
            "AND length(input_fingerprint) = 64",
            name="ck_opportunities_fingerprint_lengths",
        ),
        sa.CheckConstraint(
            "yes_team_id <> no_team_id AND "
            "((direction = 'yes' AND outcome_team_id = yes_team_id) OR "
            "(direction = 'no' AND outcome_team_id = no_team_id))",
            name="ck_opportunities_orientation",
        ),
        sa.CheckConstraint(
            "price_source IN ('direct_yes_ask', 'direct_no_ask')",
            name="ck_opportunities_price_source",
        ),
        sa.CheckConstraint(
            "market_probability > 0 AND market_probability < 1 "
            "AND model_probability >= 0 AND model_probability <= 1",
            name="ck_opportunities_probability_range",
        ),
        sa.CheckConstraint(
            "raw_edge >= -1 AND raw_edge <= 1 "
            "AND raw_edge = model_probability - market_probability",
            name="ck_opportunities_raw_edge",
        ),
        sa.CheckConstraint(
            "status IN ('ignore', 'watch', 'trade_candidate')",
            name="ck_opportunities_status",
        ),
        sa.CheckConstraint(
            "(status = 'ignore' AND raw_edge < watch_min_raw_edge) OR "
            "(status = 'watch' AND raw_edge >= watch_min_raw_edge "
            "AND raw_edge < trade_candidate_min_raw_edge) OR "
            "(status = 'trade_candidate' "
            "AND raw_edge >= trade_candidate_min_raw_edge)",
            name="ck_opportunities_status_edge",
        ),
        sa.CheckConstraint(
            "watch_min_raw_edge >= 0 "
            "AND watch_min_raw_edge < trade_candidate_min_raw_edge "
            "AND trade_candidate_min_raw_edge <= 1",
            name="ck_opportunities_thresholds",
        ),
        sa.CheckConstraint(
            "evaluated_at <= valid_until",
            name="ck_opportunities_valid_until",
        ),
        sa.ForeignKeyConstraint(["base_forecast_id"], ["base_forecasts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["market_event_match_id"], ["market_event_matches.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["market_price_id"], ["market_prices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["model_version_id"], ["model_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["no_team_id"], ["teams.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["outcome_team_id"], ["teams.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sports_event_id"], ["sports_events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["yes_team_id"], ["teams.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "market_id",
            "direction",
            "strategy_version",
            "input_fingerprint",
            name="uq_opportunities_semantic_input",
        ),
    )
    op.create_index(
        "ix_opportunities_event_evaluated",
        "opportunities",
        ["sports_event_id", "evaluated_at"],
    )
    op.create_index(
        "ix_opportunities_market_evaluated",
        "opportunities",
        ["market_id", "evaluated_at"],
    )
    op.create_index(
        "ix_opportunities_status_direction_evaluated",
        "opportunities",
        ["status", "direction", "evaluated_at"],
    )


def downgrade() -> None:
    """Drop opportunity history."""
    op.drop_index(
        "ix_opportunities_status_direction_evaluated",
        table_name="opportunities",
    )
    op.drop_index("ix_opportunities_market_evaluated", table_name="opportunities")
    op.drop_index("ix_opportunities_event_evaluated", table_name="opportunities")
    op.drop_table("opportunities")
