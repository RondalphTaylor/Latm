"""Add immutable research-only NFL shadow forecast snapshots.

Revision ID: 0022_nfl_shadow_forecasts
Revises: 0021_nfl_market_matching
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0022_nfl_shadow_forecasts"
down_revision: str | None = "0021_nfl_market_matching"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "nfl_shadow_forecasts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "match_id",
            sa.Uuid(),
            sa.ForeignKey("market_event_matches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "market_id", sa.Uuid(), sa.ForeignKey("markets.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "sports_event_id",
            sa.Uuid(),
            sa.ForeignKey("sports_events.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "yes_team_id", sa.Uuid(), sa.ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("model_version", sa.String(100), nullable=False),
        sa.Column("seed_fingerprint", sa.String(64), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_source_last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_home_payout", sa.Numeric(7, 6), nullable=False),
        sa.Column("expected_away_payout", sa.Numeric(7, 6), nullable=False),
        sa.Column("expected_yes_payout", sa.Numeric(7, 6), nullable=False),
        sa.Column("expected_no_payout", sa.Numeric(7, 6), nullable=False),
        sa.Column("research_only", sa.Boolean(), nullable=False),
        sa.Column("trading_enabled", sa.Boolean(), nullable=False),
        sa.Column("audit", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(
            "research_only = true AND trading_enabled = false", name="ck_nfl_shadow_safety"
        ),
        sa.CheckConstraint(
            "expected_home_payout BETWEEN 0 AND 1 AND expected_away_payout BETWEEN 0 AND 1 "
            "AND expected_home_payout + expected_away_payout = 1 "
            "AND expected_yes_payout BETWEEN 0 AND 1 AND expected_no_payout BETWEEN 0 AND 1 "
            "AND expected_yes_payout + expected_no_payout = 1",
            name="ck_nfl_shadow_payouts",
        ),
        sa.CheckConstraint(
            "target_source_last_seen_at <= generated_at AND generated_at < scheduled_start_time",
            name="ck_nfl_shadow_pregame",
        ),
        sa.CheckConstraint(
            "seed_fingerprint ~ '^[0-9a-f]{64}$' AND input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_nfl_shadow_fingerprints",
        ),
        sa.CheckConstraint("jsonb_typeof(audit) = 'object'", name="ck_nfl_shadow_audit"),
    )
    op.create_index(
        "ix_nfl_shadow_event_generated", "nfl_shadow_forecasts", ["sports_event_id", "generated_at"]
    )
    op.execute(
        "CREATE FUNCTION reject_nfl_shadow_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN RAISE EXCEPTION 'NFL shadow forecasts are immutable'; END $$"
    )
    op.execute(
        "CREATE TRIGGER nfl_shadow_immutable BEFORE UPDATE OR DELETE ON nfl_shadow_forecasts "
        "FOR EACH ROW EXECUTE FUNCTION reject_nfl_shadow_mutation()"
    )
    op.execute(
        "CREATE FUNCTION validate_nfl_shadow_lineage() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN IF NOT EXISTS (SELECT 1 FROM market_event_matches m "
        "JOIN sports_events e ON e.id = m.sports_event_id "
        "JOIN markets k ON k.id = m.market_id "
        "WHERE m.id = NEW.match_id AND m.market_id = NEW.market_id "
        "AND m.sports_event_id = NEW.sports_event_id AND m.league = 'nfl' "
        "AND m.status = 'matched' AND m.automatic_trading_eligible = false "
        "AND e.league = 'nfl' AND e.provider_name = 'balldontlie_nfl' "
        "AND k.sports_league = 'nfl' AND k.provider_name = 'kalshi' "
        "AND NEW.scheduled_start_time = e.scheduled_start_time "
        "AND ((NEW.yes_team_id = e.home_team_id AND NEW.expected_yes_payout = NEW.expected_home_payout) "
        "OR (NEW.yes_team_id = e.away_team_id AND NEW.expected_yes_payout = NEW.expected_away_payout))) "
        "THEN RAISE EXCEPTION 'NFL shadow lineage is inconsistent'; END IF; RETURN NEW; END $$"
    )
    op.execute(
        "CREATE TRIGGER nfl_shadow_lineage BEFORE INSERT ON nfl_shadow_forecasts "
        "FOR EACH ROW EXECUTE FUNCTION validate_nfl_shadow_lineage()"
    )


def downgrade() -> None:
    op.execute("LOCK TABLE nfl_shadow_forecasts IN ACCESS EXCLUSIVE MODE")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM nfl_shadow_forecasts) THEN "
        "RAISE EXCEPTION 'NFL shadow audit data exists; downgrade refused'; END IF; END $$"
    )
    op.drop_table("nfl_shadow_forecasts")
    op.execute("DROP FUNCTION reject_nfl_shadow_mutation()")
    op.execute("DROP FUNCTION IF EXISTS validate_nfl_shadow_lineage()")
