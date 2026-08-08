"""Create versioned model registry and append-only base forecasts.

Revision ID: 0005_base_forecasts
Revises: 0004_market_event_matches
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_base_forecasts"
down_revision: str | None = "0004_market_event_matches"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create immutable model identities and reproducible base forecasts."""
    op.create_table(
        "model_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("model_name", sa.String(length=50), nullable=False),
        sa.Column("model_version", sa.String(length=100), nullable=False),
        sa.Column("algorithm", sa.String(length=50), nullable=False),
        sa.Column(
            "configuration",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("configuration_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("formula", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(configuration_fingerprint) = 64",
            name="ck_model_versions_fingerprint_length",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "model_name",
            "model_version",
            name="uq_model_versions_identity",
        ),
    )
    op.create_index(
        "ix_model_versions_name_created",
        "model_versions",
        ["model_name", "created_at"],
    )
    op.create_table(
        "base_forecasts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sports_event_id", sa.Uuid(), nullable=False),
        sa.Column("model_version_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=30), nullable=False),
        sa.Column("home_team_id", sa.Uuid(), nullable=False),
        sa.Column("away_team_id", sa.Uuid(), nullable=False),
        sa.Column("home_win_probability", sa.Numeric(precision=7, scale=6), nullable=False),
        sa.Column("away_win_probability", sa.Numeric(precision=7, scale=6), nullable=False),
        sa.Column("home_team_rating", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("away_team_rating", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column(
            "adjusted_rating_difference",
            sa.Numeric(precision=12, scale=4),
            nullable=False,
        ),
        sa.Column("training_data_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "input_features",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("training_games_seen", sa.Integer(), nullable=False),
        sa.Column("training_games_processed", sa.Integer(), nullable=False),
        sa.Column("skipped_tied_games", sa.Integer(), nullable=False),
        sa.Column("skipped_incomplete_games", sa.Integer(), nullable=False),
        sa.Column("home_prior_games", sa.Integer(), nullable=False),
        sa.Column("away_prior_games", sa.Integer(), nullable=False),
        sa.Column("latest_training_event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("forecast_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_event_last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "training_games_seen >= 0 AND training_games_processed >= 0 "
            "AND training_games_processed <= training_games_seen "
            "AND skipped_tied_games >= 0 AND skipped_incomplete_games >= 0 "
            "AND home_prior_games >= 0 AND away_prior_games >= 0",
            name="ck_base_forecasts_counts",
        ),
        sa.CheckConstraint(
            "home_team_id <> away_team_id",
            name="ck_base_forecasts_distinct_teams",
        ),
        sa.CheckConstraint(
            "length(training_data_fingerprint) = 64 AND length(input_fingerprint) = 64",
            name="ck_base_forecasts_fingerprint_lengths",
        ),
        sa.CheckConstraint(
            "home_win_probability >= 0 AND home_win_probability <= 1 "
            "AND away_win_probability >= 0 AND away_win_probability <= 1",
            name="ck_base_forecasts_probability_range",
        ),
        sa.CheckConstraint(
            "home_win_probability + away_win_probability = 1",
            name="ck_base_forecasts_probability_sum",
        ),
        sa.CheckConstraint(
            "purpose IN ('operational', 'historical_replay')",
            name="ck_base_forecasts_purpose",
        ),
        sa.ForeignKeyConstraint(["away_team_id"], ["teams.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["home_team_id"], ["teams.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["model_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sports_event_id"],
            ["sports_events.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "sports_event_id",
            "model_version_id",
            "purpose",
            "input_fingerprint",
            name="uq_base_forecasts_semantic_input",
        ),
    )
    op.create_index(
        "ix_base_forecasts_event_generated",
        "base_forecasts",
        ["sports_event_id", "generated_at"],
    )
    op.create_index(
        "ix_base_forecasts_model_purpose_generated",
        "base_forecasts",
        ["model_version_id", "purpose", "generated_at"],
    )


def downgrade() -> None:
    """Drop base forecasts before their model identities."""
    op.drop_index(
        "ix_base_forecasts_model_purpose_generated",
        table_name="base_forecasts",
    )
    op.drop_index("ix_base_forecasts_event_generated", table_name="base_forecasts")
    op.drop_table("base_forecasts")
    op.drop_index("ix_model_versions_name_created", table_name="model_versions")
    op.drop_table("model_versions")
