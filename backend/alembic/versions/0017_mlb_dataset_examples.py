"""Add immutable MLB labeled dataset examples.

Revision ID: 0017_mlb_dataset_examples
Revises: 0016_mlb_game_features
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0017_mlb_dataset_examples"
down_revision: str | None = "0016_mlb_game_features"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_mlb_game_feature_vectors_id_event",
        "mlb_game_feature_vectors",
        ["id", "sports_event_id"],
    )
    op.create_table(
        "mlb_labeled_feature_examples",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("game_feature_vector_id", sa.Uuid(), nullable=False),
        sa.Column("sports_event_id", sa.Uuid(), nullable=False),
        sa.Column("feature_vector_input_fingerprint", sa.String(64), nullable=False),
        sa.Column("feature_policy_fingerprint", sa.String(64), nullable=False),
        sa.Column("availability_basis", sa.String(30), nullable=False),
        sa.Column("scheduled_start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome_status", sa.String(30), nullable=False),
        sa.Column("home_score", sa.Integer(), nullable=False),
        sa.Column("away_score", sa.Integer(), nullable=False),
        sa.Column("home_won", sa.Boolean(), nullable=False),
        sa.Column("outcome_source_last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome_source_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("split", sa.String(30), nullable=False),
        sa.Column("split_policy_name", sa.String(100), nullable=False),
        sa.Column("split_policy_version", sa.String(100), nullable=False),
        sa.Column("validation_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("test_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prospective_holdout_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("split_policy_fingerprint", sa.String(64), nullable=False),
        sa.Column("outcome_fingerprint", sa.String(64), nullable=False),
        sa.Column("example_fingerprint", sa.String(64), nullable=False),
        sa.Column("labeled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("research_only", sa.Boolean(), nullable=False),
        sa.Column("probability_generated", sa.Boolean(), nullable=False),
        sa.Column("automatic_trading_eligible", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "validation_start < test_start AND test_start < prospective_holdout_start",
            name="ck_mlb_labeled_examples_boundaries",
        ),
        sa.CheckConstraint(
            "feature_vector_input_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND feature_policy_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND split_policy_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND outcome_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND example_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_mlb_labeled_examples_fingerprints",
        ),
        sa.CheckConstraint("outcome_status = 'final'", name="ck_mlb_labeled_examples_final"),
        sa.CheckConstraint(
            "availability_basis IN ('operational_pregame', 'retrospective') "
            "AND split IN ('train', 'validation', 'test', 'prospective_holdout')",
            name="ck_mlb_labeled_examples_roles",
        ),
        sa.CheckConstraint(
            "research_only = true AND probability_generated = false "
            "AND automatic_trading_eligible = false",
            name="ck_mlb_labeled_examples_safety",
        ),
        sa.CheckConstraint(
            "home_score >= 0 AND away_score >= 0 AND home_score <> away_score",
            name="ck_mlb_labeled_examples_score",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(outcome_source_snapshot) = 'object'",
            name="ck_mlb_labeled_examples_source_snapshot",
        ),
        sa.CheckConstraint(
            "(split = 'train' AND scheduled_start_time < validation_start) OR "
            "(split = 'validation' AND scheduled_start_time >= validation_start "
            "AND scheduled_start_time < test_start) OR "
            "(split = 'test' AND scheduled_start_time >= test_start "
            "AND scheduled_start_time < prospective_holdout_start) OR "
            "(split = 'prospective_holdout' "
            "AND scheduled_start_time >= prospective_holdout_start)",
            name="ck_mlb_labeled_examples_split",
        ),
        sa.CheckConstraint(
            "outcome_source_last_seen_at >= scheduled_start_time "
            "AND labeled_at >= outcome_source_last_seen_at",
            name="ck_mlb_labeled_examples_timing",
        ),
        sa.CheckConstraint(
            "home_won = (home_score > away_score)",
            name="ck_mlb_labeled_examples_winner",
        ),
        sa.ForeignKeyConstraint(["sports_event_id"], ["sports_events.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["game_feature_vector_id", "sports_event_id"],
            ["mlb_game_feature_vectors.id", "mlb_game_feature_vectors.sports_event_id"],
            name="fk_mlb_labeled_feature_examples_vector_event",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "game_feature_vector_id",
            "split_policy_fingerprint",
            "outcome_fingerprint",
            name="uq_mlb_labeled_feature_examples_semantic_input",
        ),
    )
    op.create_index(
        "ix_mlb_labeled_examples_event_labeled",
        "mlb_labeled_feature_examples",
        ["sports_event_id", "labeled_at"],
    )
    op.create_index(
        "ix_mlb_labeled_examples_policy_split_start",
        "mlb_labeled_feature_examples",
        ["split_policy_fingerprint", "split", "scheduled_start_time"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mlb_labeled_examples_policy_split_start",
        table_name="mlb_labeled_feature_examples",
    )
    op.drop_index(
        "ix_mlb_labeled_examples_event_labeled",
        table_name="mlb_labeled_feature_examples",
    )
    op.drop_table("mlb_labeled_feature_examples")
    op.drop_constraint(
        "uq_mlb_game_feature_vectors_id_event",
        "mlb_game_feature_vectors",
        type_="unique",
    )
