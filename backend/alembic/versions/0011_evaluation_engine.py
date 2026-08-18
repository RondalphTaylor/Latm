"""Add immutable forecast evaluation facts.

Revision ID: 0011_evaluation_engine
Revises: 0010_position_monitoring
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011_evaluation_engine"
down_revision: str | None = "0010_position_monitoring"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create append-only forecast/outcome evaluation facts without backfill."""
    # Recreate the finalized Phase 9 constraint defensively. Early local 0010
    # installations used ``reference_price < 1``, which incorrectly rejected a
    # standard-binary winning settlement at its authoritative payout of 1.
    op.drop_constraint(
        "ck_position_events_market_values",
        "position_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_position_events_market_values",
        "position_events",
        "(reference_price IS NULL OR (reference_price >= 0 AND reference_price <= 1)) "
        "AND (exit_price IS NULL OR (exit_price >= 0 AND exit_price < 1)) "
        "AND (model_probability IS NULL OR "
        "(model_probability >= 0 AND model_probability <= 1)) "
        "AND (hold_edge IS NULL OR (hold_edge >= -1 AND hold_edge <= 1)) "
        "AND (exit_slippage_bps IS NULL OR exit_slippage_bps >= 0) "
        "AND (exit_slippage_amount_per_contract IS NULL "
        "OR exit_slippage_amount_per_contract >= 0) "
        "AND (exit_fee_bps IS NULL OR exit_fee_bps >= 0)",
    )
    op.create_table(
        "forecast_evaluations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("base_forecast_id", sa.Uuid(), nullable=False),
        sa.Column("sports_event_id", sa.Uuid(), nullable=False),
        sa.Column("model_version_id", sa.Uuid(), nullable=False),
        sa.Column("home_team_id", sa.Uuid(), nullable=False),
        sa.Column("away_team_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=30), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("result_scheduled_start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("forecast_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("forecast_generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "result_source_last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "home_win_probability",
            sa.Numeric(precision=7, scale=6),
            nullable=False,
        ),
        sa.Column("predicted_home_win", sa.Boolean(), nullable=True),
        sa.Column("home_won", sa.Boolean(), nullable=False),
        sa.Column("result_home_score", sa.Integer(), nullable=False),
        sa.Column("result_away_score", sa.Integer(), nullable=False),
        sa.Column(
            "brier_score",
            sa.Numeric(precision=14, scale=12),
            nullable=False,
        ),
        sa.Column("correct", sa.Boolean(), nullable=True),
        sa.Column("policy_name", sa.String(length=50), nullable=False),
        sa.Column("policy_version", sa.String(length=100), nullable=False),
        sa.Column("policy_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("outcome_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "audit_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('operational', 'historical_replay')",
            name="ck_forecast_evaluations_purpose",
        ),
        sa.CheckConstraint(
            "home_team_id <> away_team_id",
            name="ck_forecast_evaluations_distinct_teams",
        ),
        sa.CheckConstraint(
            "result_home_score >= 0 AND result_away_score >= 0 "
            "AND result_home_score <> result_away_score "
            "AND ((home_won = true AND result_home_score > result_away_score) OR "
            "(home_won = false AND result_home_score < result_away_score))",
            name="ck_forecast_evaluations_result",
        ),
        sa.CheckConstraint(
            "home_win_probability >= 0 AND home_win_probability <= 1 "
            "AND ((home_win_probability = 0.5 "
            "AND predicted_home_win IS NULL) OR "
            "(home_win_probability > 0.5 "
            "AND predicted_home_win IS TRUE) OR "
            "(home_win_probability < 0.5 "
            "AND predicted_home_win IS FALSE))",
            name="ck_forecast_evaluations_prediction",
        ),
        sa.CheckConstraint(
            "brier_score >= 0 AND brier_score <= 1 "
            "AND brier_score = "
            "(home_win_probability - CASE WHEN home_won THEN 1 ELSE 0 END) * "
            "(home_win_probability - CASE WHEN home_won THEN 1 ELSE 0 END)",
            name="ck_forecast_evaluations_brier",
        ),
        sa.CheckConstraint(
            "(predicted_home_win IS NULL AND correct IS NULL) OR "
            "(predicted_home_win IS NOT NULL "
            "AND correct IS NOT NULL "
            "AND correct = (predicted_home_win = home_won))",
            name="ck_forecast_evaluations_correctness",
        ),
        sa.CheckConstraint(
            "(purpose = 'operational' "
            "AND forecast_as_of = forecast_generated_at "
            "AND forecast_as_of < result_scheduled_start_time) OR "
            "(purpose = 'historical_replay' "
            "AND forecast_as_of = result_scheduled_start_time "
            "AND forecast_generated_at >= forecast_as_of)",
            name="ck_forecast_evaluations_cutoff",
        ),
        sa.CheckConstraint(
            "forecast_generated_at <= evaluated_at AND result_source_last_seen_at <= evaluated_at",
            name="ck_forecast_evaluations_times",
        ),
        sa.CheckConstraint(
            "length(policy_fingerprint) = 64 "
            "AND length(outcome_fingerprint) = 64 "
            "AND length(input_fingerprint) = 64",
            name="ck_forecast_evaluations_fingerprints",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(audit_snapshot) = 'object'",
            name="ck_forecast_evaluations_source_snapshot",
        ),
        sa.ForeignKeyConstraint(
            ["base_forecast_id"],
            ["base_forecasts.id"],
            name="forecast_evaluations_base_forecast_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sports_event_id"],
            ["sports_events.id"],
            name="forecast_evaluations_sports_event_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            name="forecast_evaluations_model_version_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["home_team_id"],
            ["teams.id"],
            name="forecast_evaluations_home_team_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["away_team_id"],
            ["teams.id"],
            name="forecast_evaluations_away_team_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "base_forecast_id",
            "policy_version",
            "input_fingerprint",
            name="uq_forecast_evaluations_semantic_input",
        ),
    )
    op.create_index(
        "ix_forecast_evaluations_event_evaluated",
        "forecast_evaluations",
        ["sports_event_id", "evaluated_at"],
    )
    op.create_index(
        "ix_forecast_evaluations_model_purpose_event_date",
        "forecast_evaluations",
        ["model_version_id", "purpose", "event_date"],
    )
    op.create_index(
        "ix_forecast_evaluations_purpose_event_date",
        "forecast_evaluations",
        ["purpose", "event_date"],
    )


def downgrade() -> None:
    """Remove only Phase 10 forecast evaluation facts."""
    op.drop_index(
        "ix_forecast_evaluations_purpose_event_date",
        table_name="forecast_evaluations",
    )
    op.drop_index(
        "ix_forecast_evaluations_model_purpose_event_date",
        table_name="forecast_evaluations",
    )
    op.drop_index(
        "ix_forecast_evaluations_event_evaluated",
        table_name="forecast_evaluations",
    )
    op.drop_table("forecast_evaluations")
