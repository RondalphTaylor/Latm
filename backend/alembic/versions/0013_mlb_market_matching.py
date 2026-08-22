"""Add exact sports-market classification and research-only MLB matching.

Revision ID: 0013_mlb_market_matching
Revises: 0012_phase8_trade_repair
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_mlb_market_matching"
down_revision: str | None = "0012_phase8_trade_repair"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist typed classifications and league-scoped matching safety state."""
    op.add_column("markets", sa.Column("sports_league", sa.String(length=20)))
    op.add_column("markets", sa.Column("sports_market_type", sa.String(length=50)))
    op.add_column(
        "markets",
        sa.Column("sports_classification_method", sa.String(length=50)),
    )
    op.add_column(
        "markets",
        sa.Column("sports_classification_version", sa.String(length=50)),
    )
    op.add_column(
        "markets",
        sa.Column("sports_classification_fingerprint", sa.String(length=64)),
    )
    op.create_check_constraint(
        "ck_markets_sports_classification",
        "markets",
        "(sports_league IS NULL AND sports_market_type IS NULL "
        "AND sports_classification_method IS NULL "
        "AND sports_classification_version IS NULL "
        "AND sports_classification_fingerprint IS NULL) OR "
        "(sports_league IN ('nba', 'mlb') "
        "AND sports_market_type = 'single_game_winner' "
        "AND sports_classification_method IS NOT NULL "
        "AND sports_classification_version IS NOT NULL "
        "AND length(sports_classification_fingerprint) = 64)",
    )
    op.create_index(
        "ix_markets_sports_classification_status",
        "markets",
        ["sports_league", "sports_market_type", "status"],
    )

    op.add_column(
        "market_event_matches",
        sa.Column("league", sa.String(length=20), nullable=True),
    )
    op.execute("UPDATE market_event_matches SET league = 'nba' WHERE league IS NULL")
    op.alter_column("market_event_matches", "league", nullable=False)
    op.drop_constraint(
        "ck_market_event_matches_safety_state",
        "market_event_matches",
        type_="check",
    )
    op.create_check_constraint(
        "ck_market_event_matches_league",
        "market_event_matches",
        "league IN ('nba', 'mlb')",
    )
    op.create_check_constraint(
        "ck_market_event_matches_safety_state",
        "market_event_matches",
        "(status = 'matched' AND sports_event_id IS NOT NULL "
        "AND confidence >= min_confidence "
        "AND ((league = 'nba' AND automatic_trading_eligible = true) "
        "OR (league = 'mlb' AND automatic_trading_eligible = false))) OR "
        "(status IN ('ambiguous', 'unmatched') AND sports_event_id IS NULL "
        "AND automatic_trading_eligible = false)",
    )
    op.create_index(
        "ix_market_event_matches_league_evaluated",
        "market_event_matches",
        ["league", "evaluated_at"],
    )


def downgrade() -> None:
    """Remove MLB-only audit rows before restoring the NBA-only constraint."""
    op.execute("DELETE FROM market_event_matches WHERE league = 'mlb'")
    op.drop_index(
        "ix_market_event_matches_league_evaluated",
        table_name="market_event_matches",
    )
    op.drop_constraint(
        "ck_market_event_matches_safety_state",
        "market_event_matches",
        type_="check",
    )
    op.drop_constraint(
        "ck_market_event_matches_league",
        "market_event_matches",
        type_="check",
    )
    op.create_check_constraint(
        "ck_market_event_matches_safety_state",
        "market_event_matches",
        "(status = 'matched' AND sports_event_id IS NOT NULL "
        "AND confidence >= min_confidence "
        "AND automatic_trading_eligible = true) OR "
        "(status IN ('ambiguous', 'unmatched') AND sports_event_id IS NULL "
        "AND automatic_trading_eligible = false)",
    )
    op.drop_column("market_event_matches", "league")

    op.drop_index("ix_markets_sports_classification_status", table_name="markets")
    op.drop_constraint("ck_markets_sports_classification", "markets", type_="check")
    op.drop_column("markets", "sports_classification_fingerprint")
    op.drop_column("markets", "sports_classification_version")
    op.drop_column("markets", "sports_classification_method")
    op.drop_column("markets", "sports_market_type")
    op.drop_column("markets", "sports_league")
