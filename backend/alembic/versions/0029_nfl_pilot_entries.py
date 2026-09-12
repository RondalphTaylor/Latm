"""Add an isolated, paper-only NFL pilot entry journal."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0029_nfl_pilot_entries"
down_revision = "0028_nfl_pilot_scenarios"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nfl_pilot_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("preflight_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("opportunity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("market_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("direction", sa.String(3), nullable=False),
        sa.Column("entered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("gross_cost", sa.Numeric(18, 2), nullable=False),
        sa.Column("estimated_fee", sa.Numeric(18, 2), nullable=False),
        sa.Column("total_cost", sa.Numeric(18, 2), nullable=False),
        sa.Column("adjusted_edge", sa.Numeric(8, 6), nullable=False),
        sa.Column("minimum_adjusted_edge", sa.Numeric(8, 6), nullable=False),
        sa.Column("entry_cap", sa.Numeric(18, 2), nullable=False),
        sa.Column("aggregate_cap", sa.Numeric(18, 2), nullable=False),
        sa.Column("execution_mode", sa.String(10), nullable=False),
        sa.Column("live_trading_enabled", sa.Boolean(), nullable=False),
        sa.Column("policy_version", sa.String(100), nullable=False),
        sa.Column("policy_fingerprint", sa.String(64), nullable=False),
        sa.Column("audit", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["scenario_id"], ["nfl_pilot_scenarios.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["preflight_id"], ["nfl_paper_preflights.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["opportunity_id"], ["nfl_paper_opportunities.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("idempotency_key", name="uq_nfl_pilot_entries_idempotency"),
        sa.UniqueConstraint("scenario_id", "preflight_id", name="uq_nfl_pilot_entries_scenario_preflight"),
        sa.CheckConstraint("execution_mode = 'paper' AND NOT live_trading_enabled AND status = 'filled'", name="ck_nfl_pilot_entries_paper_only"),
        sa.CheckConstraint("direction IN ('yes', 'no') AND quantity > 0", name="ck_nfl_pilot_entries_side"),
        sa.CheckConstraint("total_cost > 0 AND gross_cost > 0 AND estimated_fee >= 0 AND total_cost = gross_cost + estimated_fee", name="ck_nfl_pilot_entries_costs"),
        sa.CheckConstraint("entry_cap > 0 AND aggregate_cap > 0 AND total_cost <= entry_cap AND total_cost <= aggregate_cap", name="ck_nfl_pilot_entries_caps"),
        sa.CheckConstraint("adjusted_edge >= minimum_adjusted_edge AND length(policy_fingerprint) = 64 AND jsonb_typeof(audit) = 'object'", name="ck_nfl_pilot_entries_policy"),
    )
    op.create_index("ix_nfl_pilot_entries_scenario_entered", "nfl_pilot_entries", ["scenario_id", "entered_at"])


def downgrade() -> None:
    raise RuntimeError("Refusing to discard NFL paper-entry audit history")
