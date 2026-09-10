"""Add immutable unpromoted NFL paper-candidate payout forecasts.

Revision ID: 0025_nfl_payout_forecasts
Revises: 0024_fractional_settlement
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0025_nfl_payout_forecasts"
down_revision: str | None = "0024_fractional_settlement"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "nfl_payout_forecasts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True),
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
            "event_id",
            sa.Uuid(),
            sa.ForeignKey("sports_events.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_shadow_snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("nfl_shadow_forecasts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "home_team_id",
            sa.Uuid(),
            sa.ForeignKey("teams.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "away_team_id",
            sa.Uuid(),
            sa.ForeignKey("teams.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "yes_team_id", sa.Uuid(), sa.ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("model_version", sa.String(100), nullable=False),
        sa.Column("seed_fingerprint", sa.String(64), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("purpose", sa.String(100), nullable=False),
        sa.Column("metric_kind", sa.String(100), nullable=False),
        sa.Column("execution_mode", sa.String(100), nullable=False),
        sa.Column("promotion_state", sa.String(100), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("market_close_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_source_last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("market_source_last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_home_payout", sa.Numeric(7, 6), nullable=False),
        sa.Column("expected_away_payout", sa.Numeric(7, 6), nullable=False),
        sa.Column("expected_yes_payout", sa.Numeric(7, 6), nullable=False),
        sa.Column("expected_no_payout", sa.Numeric(7, 6), nullable=False),
        sa.Column("operational_eligible", sa.Boolean(), nullable=False),
        sa.Column("trading_enabled", sa.Boolean(), nullable=False),
        sa.Column("audit", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(
            "purpose = 'paper_candidate' AND metric_kind = 'expected_payout' AND execution_mode = 'paper' AND promotion_state = 'blocked' AND operational_eligible = false AND trading_enabled = false",
            name="ck_nfl_payout_forecast_safety",
        ),
        sa.CheckConstraint(
            "event_source_last_seen_at <= generated_at AND market_source_last_seen_at <= generated_at AND generated_at < valid_until AND valid_until <= generated_at + interval '15 minutes' AND valid_until <= scheduled_start_time AND valid_until <= market_close_time AND valid_until <= event_source_last_seen_at + interval '24 hours' AND valid_until <= market_source_last_seen_at + interval '24 hours'",
            name="ck_nfl_payout_forecast_times",
        ),
        sa.CheckConstraint(
            "expected_home_payout BETWEEN 0 AND 1 AND expected_away_payout BETWEEN 0 AND 1 AND expected_home_payout + expected_away_payout = 1 AND expected_yes_payout BETWEEN 0 AND 1 AND expected_no_payout BETWEEN 0 AND 1 AND expected_yes_payout + expected_no_payout = 1",
            name="ck_nfl_payout_forecast_payouts",
        ),
        sa.CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$' AND seed_fingerprint ~ '^[0-9a-f]{64}$' AND input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_nfl_payout_forecast_identity",
        ),
        sa.CheckConstraint("jsonb_typeof(audit) = 'object'", name="ck_nfl_payout_forecast_audit"),
    )
    op.create_index("ix_nfl_payout_forecast_generated", "nfl_payout_forecasts", ["generated_at"])
    op.execute(
        "CREATE FUNCTION reject_nfl_payout_forecast_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'NFL payout forecasts are immutable'; END $$"
    )
    op.execute(
        "CREATE TRIGGER nfl_payout_forecast_immutable BEFORE UPDATE OR DELETE ON nfl_payout_forecasts FOR EACH ROW EXECUTE FUNCTION reject_nfl_payout_forecast_mutation()"
    )
    op.execute(
        "CREATE FUNCTION validate_nfl_payout_forecast_lineage() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN IF NOT EXISTS (SELECT 1 FROM nfl_shadow_forecasts f JOIN market_event_matches m ON m.id = f.match_id "
        "JOIN sports_events e ON e.id = f.sports_event_id JOIN markets k ON k.id = f.market_id "
        "WHERE f.id = NEW.source_shadow_snapshot_id "
        "AND f.match_id = NEW.match_id AND f.market_id = NEW.market_id AND f.sports_event_id = NEW.event_id "
        "AND f.model_version = NEW.model_version AND f.seed_fingerprint = NEW.seed_fingerprint "
        "AND f.yes_team_id = NEW.yes_team_id AND f.expected_home_payout = NEW.expected_home_payout "
        "AND f.expected_yes_payout = NEW.expected_yes_payout AND f.generated_at <= NEW.generated_at "
        "AND m.league = 'nfl' AND m.status = 'matched' AND m.automatic_trading_eligible = false "
        "AND e.home_team_id = NEW.home_team_id AND e.away_team_id = NEW.away_team_id "
        "AND e.scheduled_start_time = NEW.scheduled_start_time AND e.league = 'nfl' "
        "AND e.provider_name = 'balldontlie_nfl' AND e.status = 'scheduled' AND e.postponed = false "
        "AND e.last_seen_at = NEW.event_source_last_seen_at "
        "AND k.close_time = NEW.market_close_time AND k.last_seen_at = NEW.market_source_last_seen_at "
        "AND k.status IN ('open', 'active') AND k.sports_league = 'nfl' "
        "AND clock_timestamp() >= NEW.generated_at AND clock_timestamp() < NEW.valid_until) "
        "THEN RAISE EXCEPTION 'NFL payout forecast lineage is inconsistent or expired'; "
        "END IF; RETURN NEW; END $$"
    )
    op.execute(
        "CREATE TRIGGER nfl_payout_forecast_lineage BEFORE INSERT ON nfl_payout_forecasts FOR EACH ROW EXECUTE FUNCTION validate_nfl_payout_forecast_lineage()"
    )


def downgrade() -> None:
    op.execute("LOCK TABLE nfl_payout_forecasts IN ACCESS EXCLUSIVE MODE")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM nfl_payout_forecasts) THEN RAISE EXCEPTION 'NFL payout forecast audit data exists; downgrade refused'; END IF; END $$"
    )
    op.drop_table("nfl_payout_forecasts")
    op.execute("DROP FUNCTION reject_nfl_payout_forecast_mutation()")
    op.execute("DROP FUNCTION validate_nfl_payout_forecast_lineage()")
