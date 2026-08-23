"""Add resumable MLB historical backfill checkpoints and batch audit facts.

Revision ID: 0018_mlb_backfill_workflow
Revises: 0017_mlb_dataset_examples
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0018_mlb_backfill_workflow"
down_revision: str | None = "0017_mlb_dataset_examples"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mlb_backfill_checkpoints",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("policy_name", sa.String(100), nullable=False),
        sa.Column("policy_version", sa.String(100), nullable=False),
        sa.Column("policy_fingerprint", sa.String(64), nullable=False),
        sa.Column("split_policy_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("regular_season_start", sa.Date(), nullable=False),
        sa.Column("validation_start_date", sa.Date(), nullable=False),
        sa.Column("test_start_date", sa.Date(), nullable=False),
        sa.Column("prospective_holdout_start_date", sa.Date(), nullable=False),
        sa.Column("train_cursor_date", sa.Date(), nullable=False),
        sa.Column("train_cursor_offset", sa.Integer(), nullable=False),
        sa.Column("validation_cursor_date", sa.Date(), nullable=False),
        sa.Column("validation_cursor_offset", sa.Integer(), nullable=False),
        sa.Column("test_cursor_date", sa.Date(), nullable=False),
        sa.Column("test_cursor_offset", sa.Integer(), nullable=False),
        sa.Column("batch_limit", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("batches_completed", sa.Integer(), nullable=False),
        sa.Column("events_examined", sa.Integer(), nullable=False),
        sa.Column("examples_created", sa.Integer(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("state_fingerprint", sa.String(64), nullable=False),
        sa.Column("research_only", sa.Boolean(), nullable=False),
        sa.Column("probability_generated", sa.Boolean(), nullable=False),
        sa.Column("automatic_trading_eligible", sa.Boolean(), nullable=False),
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
        sa.CheckConstraint(
            "regular_season_start < validation_start_date "
            "AND validation_start_date < test_start_date "
            "AND test_start_date < prospective_holdout_start_date",
            name="ck_mlb_backfill_checkpoints_boundaries",
        ),
        sa.CheckConstraint(
            "version >= 0 AND batches_completed >= 0 AND events_examined >= 0 "
            "AND examples_created >= 0",
            name="ck_mlb_backfill_checkpoints_counts",
        ),
        sa.CheckConstraint(
            "train_cursor_date BETWEEN regular_season_start - 1 "
            "AND validation_start_date - 1 "
            "AND validation_cursor_date BETWEEN regular_season_start - 1 "
            "AND test_start_date - 1 "
            "AND test_cursor_date BETWEEN regular_season_start - 1 "
            "AND prospective_holdout_start_date - 1",
            name="ck_mlb_backfill_checkpoints_cursors",
        ),
        sa.CheckConstraint(
            "policy_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND split_policy_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND state_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_mlb_backfill_checkpoints_fingerprints",
        ),
        sa.CheckConstraint(
            "train_cursor_offset >= 0 AND validation_cursor_offset >= 0 "
            "AND test_cursor_offset >= 0 AND batch_limit BETWEEN 1 AND 10",
            name="ck_mlb_backfill_checkpoints_offsets",
        ),
        sa.CheckConstraint(
            "research_only = true AND probability_generated = false "
            "AND automatic_trading_eligible = false",
            name="ck_mlb_backfill_checkpoints_safety",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'complete', 'exhausted')",
            name="ck_mlb_backfill_checkpoints_status",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND finished_at IS NULL) "
            "OR (status IN ('complete', 'exhausted') AND finished_at IS NOT NULL)",
            name="ck_mlb_backfill_checkpoints_terminal",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("policy_fingerprint", name="uq_mlb_backfill_checkpoints_policy"),
    )
    op.create_table(
        "mlb_backfill_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("checkpoint_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("split", sa.String(30), nullable=False),
        sa.Column("window_date", sa.Date(), nullable=False),
        sa.Column("batch_offset", sa.Integer(), nullable=False),
        sa.Column("batch_limit", sa.Integer(), nullable=False),
        sa.Column("cursor_date_after", sa.Date(), nullable=False),
        sa.Column("cursor_offset_after", sa.Integer(), nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("events_refreshed", sa.Integer(), nullable=False),
        sa.Column("examined", sa.Integer(), nullable=False),
        sa.Column("retrospective_vectors_built", sa.Integer(), nullable=False),
        sa.Column("examples_labeled", sa.Integer(), nullable=False),
        sa.Column("examples_created", sa.Integer(), nullable=False),
        sa.Column("result_counts", postgresql.JSONB(), nullable=False),
        sa.Column("event_results", postgresql.JSONB(), nullable=False),
        sa.Column("readiness_before", postgresql.JSONB(), nullable=False),
        sa.Column("readiness_after", postgresql.JSONB(), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("result_fingerprint", sa.String(64), nullable=False),
        sa.Column("research_only", sa.Boolean(), nullable=False),
        sa.Column("probability_generated", sa.Boolean(), nullable=False),
        sa.Column("automatic_trading_eligible", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "events_refreshed >= 0 AND examined >= 0 "
            "AND retrospective_vectors_built >= 0 AND examples_labeled >= 0 "
            "AND examples_created >= 0 AND examples_created <= examples_labeled",
            name="ck_mlb_backfill_batches_counts",
        ),
        sa.CheckConstraint(
            "sequence >= 1 AND batch_offset >= 0 AND batch_limit BETWEEN 1 AND 10",
            name="ck_mlb_backfill_batches_cursor",
        ),
        sa.CheckConstraint(
            "input_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND result_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_mlb_backfill_batches_fingerprints",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(result_counts) = 'object' "
            "AND jsonb_typeof(event_results) = 'array' "
            "AND jsonb_typeof(readiness_before) = 'object' "
            "AND jsonb_typeof(readiness_after) = 'object'",
            name="ck_mlb_backfill_batches_json",
        ),
        sa.CheckConstraint(
            "research_only = true AND probability_generated = false "
            "AND automatic_trading_eligible = false",
            name="ck_mlb_backfill_batches_safety",
        ),
        sa.CheckConstraint(
            "split IN ('train', 'validation', 'test')",
            name="ck_mlb_backfill_batches_split",
        ),
        sa.ForeignKeyConstraint(
            ["checkpoint_id"],
            ["mlb_backfill_checkpoints.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "checkpoint_id", "input_fingerprint", name="uq_mlb_backfill_batches_input"
        ),
        sa.UniqueConstraint(
            "checkpoint_id", "sequence", name="uq_mlb_backfill_batches_sequence"
        ),
    )
    op.create_index(
        "ix_mlb_backfill_batches_checkpoint_run",
        "mlb_backfill_batches",
        ["checkpoint_id", "run_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mlb_backfill_batches_checkpoint_run", table_name="mlb_backfill_batches"
    )
    op.drop_table("mlb_backfill_batches")
    op.drop_table("mlb_backfill_checkpoints")
