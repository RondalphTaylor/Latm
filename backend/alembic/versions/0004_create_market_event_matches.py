"""Create append-oriented market-to-event match records.

Revision ID: 0004_market_event_matches
Revises: 0003_nba_teams_events
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_market_event_matches"
down_revision: str | None = "0003_nba_teams_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the deterministic matching audit table."""
    op.create_table(
        "market_event_matches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("market_id", sa.Uuid(), nullable=False),
        sa.Column("sports_event_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("method", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("matcher_version", sa.String(length=50), nullable=False),
        sa.Column("min_confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("ambiguity_margin", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("time_window_hours", sa.Integer(), nullable=False),
        sa.Column("automatic_trading_eligible", sa.Boolean(), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("team_signals", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "candidate_scores",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_market_event_matches_confidence",
        ),
        sa.CheckConstraint(
            "length(input_fingerprint) = 64",
            name="ck_market_event_matches_fingerprint_length",
        ),
        sa.CheckConstraint(
            "min_confidence >= 0 AND min_confidence <= 1 "
            "AND ambiguity_margin >= 0 AND ambiguity_margin <= 1",
            name="ck_market_event_matches_policy_confidence",
        ),
        sa.CheckConstraint(
            "(status = 'matched' AND sports_event_id IS NOT NULL "
            "AND confidence >= min_confidence "
            "AND automatic_trading_eligible = true) OR "
            "(status IN ('ambiguous', 'unmatched') AND sports_event_id IS NULL "
            "AND automatic_trading_eligible = false)",
            name="ck_market_event_matches_safety_state",
        ),
        sa.CheckConstraint(
            "status IN ('matched', 'ambiguous', 'unmatched')",
            name="ck_market_event_matches_status",
        ),
        sa.CheckConstraint(
            "time_window_hours >= 1 AND time_window_hours <= 168",
            name="ck_market_event_matches_time_window",
        ),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["sports_event_id"],
            ["sports_events.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "market_id",
            "matcher_version",
            "input_fingerprint",
            name="uq_market_event_matches_semantic_input",
        ),
    )
    op.create_index(
        "ix_market_event_matches_event",
        "market_event_matches",
        ["sports_event_id"],
    )
    op.create_index(
        "ix_market_event_matches_market_evaluated",
        "market_event_matches",
        ["market_id", "evaluated_at"],
    )
    op.create_index(
        "ix_market_event_matches_status_eligible",
        "market_event_matches",
        ["status", "automatic_trading_eligible", "evaluated_at"],
    )


def downgrade() -> None:
    """Drop deterministic matching audit records."""
    op.drop_index(
        "ix_market_event_matches_status_eligible",
        table_name="market_event_matches",
    )
    op.drop_index(
        "ix_market_event_matches_market_evaluated",
        table_name="market_event_matches",
    )
    op.drop_index("ix_market_event_matches_event", table_name="market_event_matches")
    op.drop_table("market_event_matches")
