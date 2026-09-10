"""Allow NFL classifications and research-only matching without trading authority.

Revision ID: 0021_nfl_market_matching
Revises: 0020_mlb_dataset_quality_audits
Create Date: 2026-09-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021_nfl_market_matching"
down_revision: str | None = "0020_mlb_dataset_quality_audits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_constraints(*, include_nfl: bool) -> None:
    leagues = "'nba', 'mlb', 'nfl'" if include_nfl else "'nba', 'mlb'"
    research_leagues = "'mlb', 'nfl'" if include_nfl else "'mlb'"
    op.drop_constraint("ck_markets_sports_classification", "markets", type_="check")
    op.create_check_constraint(
        "ck_markets_sports_classification",
        "markets",
        "(sports_league IS NULL AND sports_market_type IS NULL "
        "AND sports_classification_method IS NULL "
        "AND sports_classification_version IS NULL "
        "AND sports_classification_fingerprint IS NULL) OR "
        f"(sports_league IN ({leagues}) "
        "AND sports_market_type = 'single_game_winner' "
        "AND sports_classification_method IS NOT NULL "
        "AND sports_classification_version IS NOT NULL "
        "AND length(sports_classification_fingerprint) = 64)",
    )
    op.drop_constraint("ck_market_event_matches_league", "market_event_matches", type_="check")
    op.create_check_constraint(
        "ck_market_event_matches_league",
        "market_event_matches",
        f"league IN ({leagues})",
    )
    op.drop_constraint(
        "ck_market_event_matches_safety_state", "market_event_matches", type_="check"
    )
    op.create_check_constraint(
        "ck_market_event_matches_safety_state",
        "market_event_matches",
        "(status = 'matched' AND sports_event_id IS NOT NULL "
        "AND confidence >= min_confidence "
        "AND ((league = 'nba' AND automatic_trading_eligible = true) "
        f"OR (league IN ({research_leagues}) AND automatic_trading_eligible = false))) OR "
        "(status IN ('ambiguous', 'unmatched') AND sports_event_id IS NULL "
        "AND automatic_trading_eligible = false)",
    )


def upgrade() -> None:
    """Extend stored classifications while denying NFL automatic trading."""
    _replace_constraints(include_nfl=True)


def downgrade() -> None:
    """Refuse to erase NFL classification or matching audit data."""
    op.execute("LOCK TABLE markets, market_event_matches IN ACCESS EXCLUSIVE MODE")
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM markets WHERE sports_league = 'nfl') "
        "OR EXISTS (SELECT 1 FROM market_event_matches WHERE league = 'nfl') THEN "
        "RAISE EXCEPTION 'NFL classification or matching data exists; downgrade refused'; "
        "END IF; END $$"
    )
    _replace_constraints(include_nfl=False)
