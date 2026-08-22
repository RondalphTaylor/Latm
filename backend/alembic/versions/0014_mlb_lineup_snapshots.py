"""Add append-only official MLB lineup observations.

Revision ID: 0014_mlb_lineup_snapshots
Revises: 0013_mlb_market_matching
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014_mlb_lineup_snapshots"
down_revision: str | None = "0013_mlb_market_matching"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create immutable, event-linked probable-pitcher and lineup snapshots."""
    op.create_table(
        "mlb_lineup_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sports_event_id", sa.Uuid(), nullable=False),
        sa.Column("provider_name", sa.String(length=50), nullable=False),
        sa.Column("provider_event_id", sa.String(length=100), nullable=False),
        sa.Column("home_team_id", sa.Uuid(), nullable=False),
        sa.Column("away_team_id", sa.Uuid(), nullable=False),
        sa.Column("scheduled_start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_abstract_state", sa.String(length=30), nullable=False),
        sa.Column("source_detailed_state", sa.String(length=100), nullable=False),
        sa.Column("observation_phase", sa.String(length=20), nullable=False),
        sa.Column("home_probable_pitcher", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("away_probable_pitcher", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("home_lineup_state", sa.String(length=20), nullable=False),
        sa.Column("away_lineup_state", sa.String(length=20), nullable=False),
        sa.Column(
            "home_lineup",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "away_lineup",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("complete_for_pregame_model", sa.Boolean(), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "source_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.CheckConstraint(
            "complete_for_pregame_model = "
            "(observation_phase = 'pregame' AND source_updated_at <= retrieved_at "
            "AND source_updated_at < scheduled_start_time AND retrieved_at < scheduled_start_time "
            "AND home_lineup_state = 'posted' AND away_lineup_state = 'posted' "
            "AND home_probable_pitcher IS NOT NULL AND away_probable_pitcher IS NOT NULL)",
            name="ck_mlb_lineup_snapshots_complete",
        ),
        sa.CheckConstraint(
            "input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_mlb_lineup_snapshots_fingerprint",
        ),
        sa.CheckConstraint(
            "(home_lineup_state = 'unavailable' AND jsonb_array_length(home_lineup) = 0) OR "
            "(home_lineup_state = 'partial' AND jsonb_array_length(home_lineup) BETWEEN 1 AND 8) "
            "OR (home_lineup_state = 'posted' AND jsonb_array_length(home_lineup) = 9)",
            name="ck_mlb_lineup_snapshots_home_count",
        ),
        sa.CheckConstraint(
            "(away_lineup_state = 'unavailable' AND jsonb_array_length(away_lineup) = 0) OR "
            "(away_lineup_state = 'partial' AND jsonb_array_length(away_lineup) BETWEEN 1 AND 8) "
            "OR (away_lineup_state = 'posted' AND jsonb_array_length(away_lineup) = 9)",
            name="ck_mlb_lineup_snapshots_away_count",
        ),
        sa.CheckConstraint(
            "observation_phase IN ('pregame', 'live', 'postgame')",
            name="ck_mlb_lineup_snapshots_phase",
        ),
        sa.CheckConstraint(
            "provider_name = 'mlb'",
            name="ck_mlb_lineup_snapshots_provider",
        ),
        sa.CheckConstraint(
            "home_lineup_state IN ('unavailable', 'partial', 'posted') "
            "AND away_lineup_state IN ('unavailable', 'partial', 'posted')",
            name="ck_mlb_lineup_snapshots_states",
        ),
        sa.CheckConstraint(
            "home_team_id <> away_team_id",
            name="ck_mlb_lineup_snapshots_teams",
        ),
        sa.ForeignKeyConstraint(
            ["away_team_id"],
            ["teams.id"],
            name=op.f("fk_mlb_lineup_snapshots_away_team_id_teams"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["home_team_id"],
            ["teams.id"],
            name=op.f("fk_mlb_lineup_snapshots_home_team_id_teams"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["provider_name"],
            ["providers.name"],
            name=op.f("fk_mlb_lineup_snapshots_provider_name_providers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sports_event_id"],
            ["sports_events.id"],
            name=op.f("fk_mlb_lineup_snapshots_sports_event_id_sports_events"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mlb_lineup_snapshots")),
        sa.UniqueConstraint(
            "sports_event_id",
            "input_fingerprint",
            name="uq_mlb_lineup_snapshots_semantic_input",
        ),
    )
    op.create_index(
        "ix_mlb_lineup_snapshots_event_retrieved",
        "mlb_lineup_snapshots",
        ["sports_event_id", "retrieved_at"],
    )
    op.create_index(
        "ix_mlb_lineup_snapshots_phase_complete",
        "mlb_lineup_snapshots",
        ["observation_phase", "complete_for_pregame_model", "retrieved_at"],
    )


def downgrade() -> None:
    """Remove the self-contained MLB lineup observation history."""
    op.drop_index(
        "ix_mlb_lineup_snapshots_phase_complete",
        table_name="mlb_lineup_snapshots",
    )
    op.drop_index(
        "ix_mlb_lineup_snapshots_event_retrieved",
        table_name="mlb_lineup_snapshots",
    )
    op.drop_table("mlb_lineup_snapshots")
