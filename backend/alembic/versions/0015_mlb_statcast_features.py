"""Add append-only official Statcast quantitative feature snapshots.

Revision ID: 0015_mlb_statcast_features
Revises: 0014_mlb_lineup_snapshots
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015_mlb_statcast_features"
down_revision: str | None = "0014_mlb_lineup_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create exact-lineup-linked rolling Statcast source and feature snapshots."""
    op.create_unique_constraint(
        "uq_mlb_lineup_snapshots_id_event",
        "mlb_lineup_snapshots",
        ["id", "sports_event_id"],
    )
    op.create_table(
        "mlb_statcast_feature_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sports_event_id", sa.Uuid(), nullable=False),
        sa.Column("lineup_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("provider_name", sa.String(length=50), nullable=False),
        sa.Column("provider_event_id", sa.String(length=100), nullable=False),
        sa.Column("target_event_date", sa.Date(), nullable=False),
        sa.Column("scheduled_start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_start_date", sa.Date(), nullable=False),
        sa.Column("window_end_date", sa.Date(), nullable=False),
        sa.Column("lookback_days", sa.Integer(), nullable=False),
        sa.Column("source_retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observation_basis", sa.String(length=30), nullable=False),
        sa.Column("operational_pregame_eligible", sa.Boolean(), nullable=False),
        sa.Column("policy_name", sa.String(length=100), nullable=False),
        sa.Column("policy_version", sa.String(length=100), nullable=False),
        sa.Column("policy_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "home_starting_pitcher",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "away_starting_pitcher",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("home_batters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("away_batters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "source_manifest",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("source_rows", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "jsonb_array_length(home_batters) = 9 AND jsonb_array_length(away_batters) = 9",
            name="ck_mlb_statcast_feature_snapshots_batters",
        ),
        sa.CheckConstraint(
            "observation_basis IN ('operational_pregame', 'retrospective')",
            name="ck_mlb_statcast_feature_snapshots_basis",
        ),
        sa.CheckConstraint(
            "(observation_basis = 'operational_pregame' "
            "AND operational_pregame_eligible = true "
            "AND source_retrieved_at < scheduled_start_time) OR "
            "(observation_basis = 'retrospective' "
            "AND operational_pregame_eligible = false "
            "AND source_retrieved_at >= scheduled_start_time)",
            name="ck_mlb_statcast_feature_snapshots_eligibility",
        ),
        sa.CheckConstraint(
            "policy_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND source_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_mlb_statcast_feature_snapshots_fingerprints",
        ),
        sa.CheckConstraint(
            "lookback_days BETWEEN 1 AND 90",
            name="ck_mlb_statcast_feature_snapshots_lookback",
        ),
        sa.CheckConstraint(
            "provider_name = 'baseball_savant'",
            name="ck_mlb_statcast_feature_snapshots_provider",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(source_rows) = 'array'",
            name="ck_mlb_statcast_feature_snapshots_source_rows",
        ),
        sa.CheckConstraint(
            "window_end_date < target_event_date "
            "AND window_end_date - window_start_date + 1 = lookback_days",
            name="ck_mlb_statcast_feature_snapshots_window",
        ),
        sa.ForeignKeyConstraint(
            ["lineup_snapshot_id", "sports_event_id"],
            ["mlb_lineup_snapshots.id", "mlb_lineup_snapshots.sports_event_id"],
            name="fk_mlb_statcast_feature_snapshots_lineup_event",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["provider_name"],
            ["providers.name"],
            name=op.f("fk_mlb_statcast_feature_snapshots_provider_name_providers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sports_event_id"],
            ["sports_events.id"],
            name=op.f("fk_mlb_statcast_feature_snapshots_sports_event_id_sports_events"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mlb_statcast_feature_snapshots")),
        sa.UniqueConstraint(
            "lineup_snapshot_id",
            "input_fingerprint",
            name="uq_mlb_statcast_feature_snapshots_semantic_input",
        ),
    )
    op.create_index(
        "ix_mlb_statcast_feature_snapshots_eligible_retrieved",
        "mlb_statcast_feature_snapshots",
        ["operational_pregame_eligible", "source_retrieved_at"],
    )
    op.create_index(
        "ix_mlb_statcast_feature_snapshots_event_retrieved",
        "mlb_statcast_feature_snapshots",
        ["sports_event_id", "source_retrieved_at"],
    )


def downgrade() -> None:
    """Remove the self-contained Statcast snapshot slice."""
    op.drop_index(
        "ix_mlb_statcast_feature_snapshots_event_retrieved",
        table_name="mlb_statcast_feature_snapshots",
    )
    op.drop_index(
        "ix_mlb_statcast_feature_snapshots_eligible_retrieved",
        table_name="mlb_statcast_feature_snapshots",
    )
    op.drop_table("mlb_statcast_feature_snapshots")
    op.drop_constraint(
        "uq_mlb_lineup_snapshots_id_event",
        "mlb_lineup_snapshots",
        type_="unique",
    )
