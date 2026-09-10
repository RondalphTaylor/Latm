"""Add immutable NFL paper direct-ask comparisons."""

from collections.abc import Sequence
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "0026_nfl_paper_opportunities"
down_revision: str | None = "0025_nfl_payout_forecasts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "nfl_paper_opportunities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True),
        sa.Column(
            "forecast_id",
            sa.Uuid(),
            sa.ForeignKey("nfl_payout_forecasts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "market_id", sa.Uuid(), sa.ForeignKey("markets.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "match_id",
            sa.Uuid(),
            sa.ForeignKey("market_event_matches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            sa.Uuid(),
            sa.ForeignKey("sports_events.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "price_id",
            sa.Uuid(),
            sa.ForeignKey("market_prices.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("price_retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("yes_expected_payout", sa.Numeric(8, 6), nullable=False),
        sa.Column("no_expected_payout", sa.Numeric(8, 6), nullable=False),
        sa.Column("yes_direct_ask", sa.Numeric(18, 8), nullable=True),
        sa.Column("no_direct_ask", sa.Numeric(18, 8), nullable=True),
        sa.Column("yes_raw_edge", sa.Numeric(8, 6), nullable=True),
        sa.Column("no_raw_edge", sa.Numeric(8, 6), nullable=True),
        sa.Column("yes_status", sa.String(100), nullable=False),
        sa.Column("no_status", sa.String(100), nullable=False),
        sa.Column("yes_reason", sa.String(100), nullable=False),
        sa.Column("no_reason", sa.String(100), nullable=False),
        sa.Column("policy_version", sa.String(100), nullable=False),
        sa.Column("policy_fingerprint", sa.String(100), nullable=False),
        sa.Column("input_fingerprint", sa.String(100), nullable=False),
        sa.Column("execution_mode", sa.String(100), nullable=False),
        sa.Column("promotion_state", sa.String(100), nullable=False),
        sa.Column("operational_eligible", sa.Boolean(), nullable=False),
        sa.Column("trading_enabled", sa.Boolean(), nullable=False),
        sa.Column("costs_included", sa.Boolean(), nullable=False),
        sa.Column("depth_verified", sa.Boolean(), nullable=False),
        sa.Column("audit", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint(
            "execution_mode = 'paper' AND promotion_state = 'blocked' AND NOT operational_eligible AND NOT trading_enabled AND NOT costs_included AND NOT depth_verified",
            name="ck_nfl_paper_opp_safety",
        ),
        sa.CheckConstraint(
            "yes_expected_payout BETWEEN 0 AND 1 AND no_expected_payout BETWEEN 0 AND 1 AND yes_expected_payout + no_expected_payout = 1",
            name="ck_nfl_paper_opp_payouts",
        ),
        sa.CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$' AND policy_fingerprint ~ '^[0-9a-f]{64}$' AND input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_nfl_paper_opp_identity",
        ),
        sa.CheckConstraint(
            "(yes_status = 'ineligible' AND no_status = 'ineligible' AND valid_until IS NULL) OR (valid_until > evaluated_at AND price_id IS NOT NULL AND price_retrieved_at <= evaluated_at AND price_retrieved_at IS NOT NULL)",
            name="ck_nfl_paper_opp_times",
        ),
        sa.CheckConstraint("jsonb_typeof(audit) = 'object'", name="ck_nfl_paper_opp_audit"),
        sa.CheckConstraint(
            "(yes_direct_ask IS NULL OR yes_direct_ask BETWEEN 0 AND 1) AND ((yes_status = 'ineligible' AND yes_raw_edge IS NULL) OR (yes_status IN ('ignore','watch','paper_candidate') AND yes_direct_ask > 0 AND yes_direct_ask < 1 AND yes_raw_edge IS NOT NULL AND yes_raw_edge = round(yes_expected_payout - yes_direct_ask, 6)))",
            name="ck_nfl_paper_opp_yes",
        ),
        sa.CheckConstraint(
            "(no_direct_ask IS NULL OR no_direct_ask BETWEEN 0 AND 1) AND ((no_status = 'ineligible' AND no_raw_edge IS NULL) OR (no_status IN ('ignore','watch','paper_candidate') AND no_direct_ask > 0 AND no_direct_ask < 1 AND no_raw_edge IS NOT NULL AND no_raw_edge = round(no_expected_payout - no_direct_ask, 6)))",
            name="ck_nfl_paper_opp_no",
        ),
    )
    op.create_index("ix_nfl_paper_opp_evaluated", "nfl_paper_opportunities", ["evaluated_at"])
    op.execute(
        "CREATE FUNCTION reject_nfl_paper_opp_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'NFL paper opportunities are immutable'; END $$"
    )
    op.execute(
        "CREATE TRIGGER nfl_paper_opp_immutable BEFORE UPDATE OR DELETE ON nfl_paper_opportunities FOR EACH ROW EXECUTE FUNCTION reject_nfl_paper_opp_mutation()"
    )
    op.execute(
        "CREATE FUNCTION validate_nfl_paper_opp_lineage() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN IF NOT EXISTS (SELECT 1 FROM nfl_payout_forecasts f "
        "JOIN markets m ON m.id = f.market_id JOIN sports_events e ON e.id = f.event_id "
        "WHERE f.id = NEW.forecast_id AND f.market_id = NEW.market_id "
        "AND f.match_id = NEW.match_id AND f.event_id = NEW.event_id "
        "AND f.expected_yes_payout = NEW.yes_expected_payout AND f.expected_no_payout = NEW.no_expected_payout "
        "AND f.generated_at <= NEW.evaluated_at AND NEW.evaluated_at < f.valid_until "
        "AND clock_timestamp() >= NEW.evaluated_at AND clock_timestamp() < f.valid_until "
        "AND (NEW.valid_until IS NULL OR (NEW.valid_until <= f.valid_until AND clock_timestamp() < NEW.valid_until)) "
        "AND m.status IN ('open','active') AND m.close_time = f.market_close_time "
        "AND clock_timestamp() < m.close_time AND e.status = 'scheduled' AND NOT e.postponed "
        "AND e.scheduled_start_time = f.scheduled_start_time AND clock_timestamp() < e.scheduled_start_time "
        "AND e.home_team_id = f.home_team_id AND e.away_team_id = f.away_team_id "
        "AND (NEW.price_id IS NULL OR EXISTS (SELECT 1 FROM market_prices p WHERE p.id = NEW.price_id "
        "AND p.market_id = NEW.market_id AND p.retrieved_at IS NOT DISTINCT FROM NEW.price_retrieved_at))) "
        "THEN RAISE EXCEPTION 'NFL paper opportunity lineage inconsistent or expired'; END IF; RETURN NEW; END $$"
    )
    op.execute(
        "CREATE TRIGGER nfl_paper_opp_lineage BEFORE INSERT ON nfl_paper_opportunities FOR EACH ROW EXECUTE FUNCTION validate_nfl_paper_opp_lineage()"
    )


def downgrade() -> None:
    op.execute("LOCK TABLE nfl_paper_opportunities IN ACCESS EXCLUSIVE MODE")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM nfl_paper_opportunities) THEN RAISE EXCEPTION 'NFL paper opportunity audit data exists; downgrade refused'; END IF; END $$"
    )
    op.drop_table("nfl_paper_opportunities")
    op.execute("DROP FUNCTION reject_nfl_paper_opp_mutation()")
    op.execute("DROP FUNCTION validate_nfl_paper_opp_lineage()")
