"""Add immutable NFL shadow outcome scoring without financial settlement.

Revision ID: 0023_nfl_shadow_evaluations
Revises: 0022_nfl_shadow_forecasts
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0023_nfl_shadow_evaluations"
down_revision: str | None = "0022_nfl_shadow_forecasts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "nfl_shadow_evaluations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "snapshot_id",
            sa.Uuid(),
            sa.ForeignKey("nfl_shadow_forecasts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "sports_event_id",
            sa.Uuid(),
            sa.ForeignKey("sports_events.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("model_version", sa.String(100), nullable=False),
        sa.Column("seed_fingerprint", sa.String(64), nullable=False),
        sa.Column("evaluation_version", sa.String(100), nullable=False),
        sa.Column("snapshot_fingerprint", sa.String(64), nullable=False),
        sa.Column("result_fingerprint", sa.String(64), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("label_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result_source_last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_home_payout", sa.Numeric(7, 6), nullable=False),
        sa.Column("expected_yes_payout", sa.Numeric(7, 6), nullable=False),
        sa.Column("actual_home_payout", sa.Numeric(7, 6), nullable=False),
        sa.Column("actual_yes_payout", sa.Numeric(7, 6), nullable=False),
        sa.Column("squared_home_payout_error", sa.Numeric(13, 12), nullable=False),
        sa.Column("constant_half_squared_error", sa.Numeric(13, 12), nullable=False),
        sa.Column("research_only", sa.Boolean(), nullable=False),
        sa.Column("trading_enabled", sa.Boolean(), nullable=False),
        sa.Column("audit", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(
            "research_only = true AND trading_enabled = false", name="ck_nfl_evaluation_safety"
        ),
        sa.CheckConstraint(
            "generated_at < scheduled_start_time AND scheduled_start_time <= result_source_last_seen_at AND result_source_last_seen_at <= label_time",
            name="ck_nfl_evaluation_times",
        ),
        sa.CheckConstraint(
            "expected_home_payout BETWEEN 0 AND 1 AND expected_yes_payout BETWEEN 0 AND 1 "
            "AND actual_home_payout IN (0, 0.5, 1) AND actual_yes_payout IN (0, 0.5, 1) "
            "AND squared_home_payout_error = (expected_home_payout - actual_home_payout) * (expected_home_payout - actual_home_payout) "
            "AND constant_half_squared_error = (0.5 - actual_home_payout) * (0.5 - actual_home_payout)",
            name="ck_nfl_evaluation_scores",
        ),
        sa.CheckConstraint(
            "seed_fingerprint ~ '^[0-9a-f]{64}$' AND input_fingerprint ~ '^[0-9a-f]{64}$' AND snapshot_fingerprint ~ '^[0-9a-f]{64}$' AND result_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_nfl_evaluation_fingerprints",
        ),
        sa.CheckConstraint("jsonb_typeof(audit) = 'object'", name="ck_nfl_evaluation_audit"),
    )
    op.create_index(
        "ix_nfl_evaluation_snapshot_time", "nfl_shadow_evaluations", ["snapshot_id", "label_time"]
    )
    op.execute(
        "CREATE FUNCTION reject_nfl_evaluation_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN RAISE EXCEPTION 'NFL shadow evaluations are immutable'; END $$"
    )
    op.execute(
        "CREATE TRIGGER nfl_evaluation_immutable BEFORE UPDATE OR DELETE ON nfl_shadow_evaluations FOR EACH ROW EXECUTE FUNCTION reject_nfl_evaluation_mutation()"
    )
    op.execute(
        "CREATE FUNCTION validate_nfl_evaluation_lineage() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN IF NOT EXISTS (SELECT 1 FROM nfl_shadow_forecasts f JOIN sports_events e ON e.id = f.sports_event_id "
        "WHERE f.id = NEW.snapshot_id AND f.sports_event_id = NEW.sports_event_id "
        "AND f.model_version = NEW.model_version AND f.seed_fingerprint = NEW.seed_fingerprint "
        "AND f.expected_home_payout = NEW.expected_home_payout AND f.expected_yes_payout = NEW.expected_yes_payout "
        "AND f.generated_at = NEW.generated_at AND f.scheduled_start_time = NEW.scheduled_start_time "
        "AND e.scheduled_start_time = f.scheduled_start_time AND e.status = 'final' "
        "AND e.home_team_id::text = f.audit->'prediction'->'target_snapshot'->>'home_team_id' "
        "AND e.away_team_id::text = f.audit->'prediction'->'target_snapshot'->>'away_team_id' "
        "AND e.provider_event_id = f.audit->'prediction'->'target_snapshot'->>'provider_event_id' "
        "AND e.raw_data->>'week' = f.audit->'prediction'->'target_snapshot'->>'week' "
        "AND e.league = 'nfl' AND e.provider_name = 'balldontlie_nfl' AND e.season = 2026 AND e.postseason = false "
        "AND e.home_score IS NOT NULL AND e.away_score IS NOT NULL "
        "AND e.last_seen_at = NEW.result_source_last_seen_at "
        "AND NEW.actual_home_payout = CASE WHEN e.home_score = e.away_score THEN 0.5 WHEN e.home_score > e.away_score THEN 1 ELSE 0 END "
        "AND ((f.yes_team_id = e.home_team_id AND NEW.actual_yes_payout = NEW.actual_home_payout) "
        "OR (f.yes_team_id = e.away_team_id AND NEW.actual_yes_payout = 1 - NEW.actual_home_payout))) "
        "THEN RAISE EXCEPTION 'NFL shadow evaluation lineage is inconsistent'; END IF; RETURN NEW; END $$"
    )
    op.execute(
        "CREATE TRIGGER nfl_evaluation_lineage BEFORE INSERT ON nfl_shadow_evaluations FOR EACH ROW EXECUTE FUNCTION validate_nfl_evaluation_lineage()"
    )


def downgrade() -> None:
    op.execute("LOCK TABLE nfl_shadow_evaluations IN ACCESS EXCLUSIVE MODE")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM nfl_shadow_evaluations) THEN RAISE EXCEPTION 'NFL shadow evaluation audit data exists; downgrade refused'; END IF; END $$"
    )
    op.drop_table("nfl_shadow_evaluations")
    op.execute("DROP FUNCTION reject_nfl_evaluation_mutation()")
    op.execute("DROP FUNCTION validate_nfl_evaluation_lineage()")
