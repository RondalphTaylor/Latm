"""Create NBA team and sports-event tables.

Revision ID: 0003_nba_teams_events
Revises: 0002_prediction_markets
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_nba_teams_events"
down_revision: str | None = "0002_prediction_markets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create normalized NBA team and sports-event tables."""
    op.create_table(
        "teams",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_name", sa.String(length=50), nullable=False),
        sa.Column("provider_team_id", sa.String(length=100), nullable=False),
        sa.Column("league", sa.String(length=20), nullable=False),
        sa.Column("abbreviation", sa.String(length=10), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("conference", sa.String(length=50), nullable=True),
        sa.Column("division", sa.String(length=100), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["provider_name"], ["providers.name"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_name",
            "provider_team_id",
            name="uq_teams_provider_team_id",
        ),
    )
    op.create_index(
        "ix_teams_league_abbreviation",
        "teams",
        ["league", "abbreviation"],
    )
    op.create_table(
        "sports_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_name", sa.String(length=50), nullable=False),
        sa.Column("provider_event_id", sa.String(length=100), nullable=False),
        sa.Column("league", sa.String(length=20), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("scheduled_start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("status_detail", sa.String(length=100), nullable=False),
        sa.Column("period", sa.Integer(), nullable=False),
        sa.Column("clock", sa.String(length=50), nullable=True),
        sa.Column("postseason", sa.Boolean(), nullable=False),
        sa.Column("postponed", sa.Boolean(), nullable=False),
        sa.Column("tournament_stage", sa.String(length=100), nullable=True),
        sa.Column("home_team_id", sa.Uuid(), nullable=False),
        sa.Column("away_team_id", sa.Uuid(), nullable=False),
        sa.Column("home_score", sa.Integer(), nullable=True),
        sa.Column("away_score", sa.Integer(), nullable=True),
        sa.Column("venue", sa.String(length=300), nullable=True),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "away_score IS NULL OR away_score >= 0",
            name="ck_sports_events_away_score_nonnegative",
        ),
        sa.CheckConstraint(
            "home_score IS NULL OR home_score >= 0",
            name="ck_sports_events_home_score_nonnegative",
        ),
        sa.CheckConstraint(
            "home_team_id <> away_team_id",
            name="ck_sports_events_distinct_teams",
        ),
        sa.CheckConstraint(
            "(home_score IS NULL) = (away_score IS NULL)",
            name="ck_sports_events_score_pair",
        ),
        sa.ForeignKeyConstraint(["away_team_id"], ["teams.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["home_team_id"], ["teams.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["provider_name"], ["providers.name"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_name",
            "provider_event_id",
            name="uq_sports_events_provider_event_id",
        ),
    )
    op.create_index(
        "ix_sports_events_away_start",
        "sports_events",
        ["away_team_id", "scheduled_start_time"],
    )
    op.create_index(
        "ix_sports_events_home_start",
        "sports_events",
        ["home_team_id", "scheduled_start_time"],
    )
    op.create_index(
        "ix_sports_events_league_start_status",
        "sports_events",
        ["league", "scheduled_start_time", "status"],
    )


def downgrade() -> None:
    """Drop normalized NBA sports-event tables."""
    op.drop_index("ix_sports_events_league_start_status", table_name="sports_events")
    op.drop_index("ix_sports_events_home_start", table_name="sports_events")
    op.drop_index("ix_sports_events_away_start", table_name="sports_events")
    op.drop_table("sports_events")
    op.drop_index("ix_teams_league_abbreviation", table_name="teams")
    op.drop_table("teams")
