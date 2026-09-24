"""Permit explicitly execution-supported NFL matches to be paper eligible.

Revision ID: 0036_nfl_paper_match
Revises: 0035_nfl_pilot_audit_verify
Create Date: 2026-09-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0036_nfl_paper_match"
down_revision: str | None = "0035_nfl_pilot_audit_verify"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow NFL eligibility only when the matcher explicitly sets it."""
    op.drop_constraint(
        "ck_market_event_matches_safety_state", "market_event_matches", type_="check"
    )
    op.create_check_constraint(
        "ck_market_event_matches_safety_state",
        "market_event_matches",
        "(status = 'matched' AND sports_event_id IS NOT NULL "
        "AND confidence >= min_confidence "
        "AND ((league = 'nba' AND automatic_trading_eligible = true) "
        "OR (league = 'nfl' AND (automatic_trading_eligible = false "
        "OR evidence->>'execution_supported' = 'true')) "
        "OR (league = 'mlb' AND automatic_trading_eligible = false))) OR "
        "(status IN ('ambiguous', 'unmatched') AND sports_event_id IS NULL "
        "AND automatic_trading_eligible = false)",
    )


def downgrade() -> None:
    """Do not silently invalidate an auditable NFL paper-eligible match."""
    op.execute("LOCK TABLE market_event_matches IN ACCESS EXCLUSIVE MODE")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM market_event_matches "
        "WHERE league = 'nfl' AND automatic_trading_eligible) THEN "
        "RAISE EXCEPTION 'NFL paper-eligible matches exist; downgrade refused'; END IF; END $$"
    )
    op.drop_constraint(
        "ck_market_event_matches_safety_state", "market_event_matches", type_="check"
    )
    op.create_check_constraint(
        "ck_market_event_matches_safety_state",
        "(status = 'matched' AND sports_event_id IS NOT NULL "
        "AND confidence >= min_confidence "
        "AND ((league = 'nba' AND automatic_trading_eligible = true) "
        "OR (league IN ('mlb', 'nfl') AND automatic_trading_eligible = false))) OR "
        "(status IN ('ambiguous', 'unmatched') AND sports_event_id IS NULL "
        "AND automatic_trading_eligible = false)",
    )
