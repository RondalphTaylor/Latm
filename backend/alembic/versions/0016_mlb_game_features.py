"""Add leakage-safe derived MLB game feature vectors.

Revision ID: 0016_mlb_game_features
Revises: 0015_mlb_statcast_features
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0016_mlb_game_features"
down_revision: str | None = "0015_mlb_statcast_features"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_mlb_statcast_feature_snapshots_id_event_lineup",
        "mlb_statcast_feature_snapshots",
        ["id", "sports_event_id", "lineup_snapshot_id"],
    )
    op.create_table(
        "mlb_game_feature_vectors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sports_event_id", sa.Uuid(), nullable=False),
        sa.Column("lineup_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("statcast_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("provider_event_id", sa.String(length=100), nullable=False),
        sa.Column("target_event_date", sa.Date(), nullable=False),
        sa.Column("scheduled_start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("home_team_id", sa.Uuid(), nullable=False),
        sa.Column("away_team_id", sa.Uuid(), nullable=False),
        sa.Column("source_retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_observation_basis", sa.String(length=30), nullable=False),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("feature_availability_basis", sa.String(length=30), nullable=False),
        sa.Column("policy_name", sa.String(length=100), nullable=False),
        sa.Column("policy_version", sa.String(length=100), nullable=False),
        sa.Column("model_candidate_name", sa.String(length=100), nullable=False),
        sa.Column("policy_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("coverage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("feature_values", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("missing_features", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("complete_feature_vector", sa.Boolean(), nullable=False),
        sa.Column("operational_model_input_eligible", sa.Boolean(), nullable=False),
        sa.Column("research_only", sa.Boolean(), nullable=False),
        sa.Column("probability_generated", sa.Boolean(), nullable=False),
        sa.Column("automatic_trading_eligible", sa.Boolean(), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "source_observation_basis IN ('operational_pregame', 'retrospective') "
            "AND feature_availability_basis IN ('operational_pregame', 'retrospective')",
            name="ck_mlb_game_feature_vectors_basis",
        ),
        sa.CheckConstraint(
            "complete_feature_vector = (jsonb_array_length(missing_features) = 0)",
            name="ck_mlb_game_feature_vectors_complete",
        ),
        sa.CheckConstraint(
            "operational_model_input_eligible = (complete_feature_vector "
            "AND source_observation_basis = 'operational_pregame' "
            "AND feature_availability_basis = 'operational_pregame' "
            "AND source_retrieved_at < scheduled_start_time "
            "AND built_at < scheduled_start_time)",
            name="ck_mlb_game_feature_vectors_eligibility",
        ),
        sa.CheckConstraint(
            "policy_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND source_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_mlb_game_feature_vectors_fingerprints",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(source_metrics) = 'object' "
            "AND jsonb_typeof(coverage) = 'object' "
            "AND jsonb_typeof(feature_values) = 'object' "
            "AND jsonb_typeof(missing_features) = 'array'",
            name="ck_mlb_game_feature_vectors_json",
        ),
        sa.CheckConstraint(
            "research_only = true AND probability_generated = false "
            "AND automatic_trading_eligible = false",
            name="ck_mlb_game_feature_vectors_safety",
        ),
        sa.CheckConstraint(
            "home_team_id <> away_team_id", name="ck_mlb_game_feature_vectors_teams"
        ),
        sa.ForeignKeyConstraint(["away_team_id"], ["teams.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["home_team_id"], ["teams.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sports_event_id"], ["sports_events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["statcast_snapshot_id", "sports_event_id", "lineup_snapshot_id"],
            [
                "mlb_statcast_feature_snapshots.id",
                "mlb_statcast_feature_snapshots.sports_event_id",
                "mlb_statcast_feature_snapshots.lineup_snapshot_id",
            ],
            name="fk_mlb_game_feature_vectors_statcast_lineage",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "statcast_snapshot_id",
            "input_fingerprint",
            name="uq_mlb_game_feature_vectors_semantic_input",
        ),
    )
    op.create_index(
        "ix_mlb_game_feature_vectors_eligible_built",
        "mlb_game_feature_vectors",
        ["operational_model_input_eligible", "built_at"],
    )
    op.create_index(
        "ix_mlb_game_feature_vectors_event_built",
        "mlb_game_feature_vectors",
        ["sports_event_id", "built_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_mlb_game_feature_vectors_event_built", table_name="mlb_game_feature_vectors")
    op.drop_index(
        "ix_mlb_game_feature_vectors_eligible_built", table_name="mlb_game_feature_vectors"
    )
    op.drop_table("mlb_game_feature_vectors")
    op.drop_constraint(
        "uq_mlb_statcast_feature_snapshots_id_event_lineup",
        "mlb_statcast_feature_snapshots",
        type_="unique",
    )
