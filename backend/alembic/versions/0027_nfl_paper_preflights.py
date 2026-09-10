"""Add immutable, execution-blocked NFL cost preflights."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0027_nfl_paper_preflights"
down_revision = "0026_nfl_paper_opportunities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nfl_paper_preflights",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key", sa.String(length=100), nullable=False, unique=True),
        sa.Column("opportunity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("market_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("direction", sa.String(length=3), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capital_cap", sa.Numeric(18, 2), nullable=False),
        sa.Column("expected_payout", sa.Numeric(8, 6), nullable=False),
        sa.Column("direct_ask", sa.Numeric(18, 8), nullable=False),
        sa.Column("raw_edge", sa.Numeric(8, 6), nullable=False),
        sa.Column("execution_price", sa.Numeric(8, 6)),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("gross_cost", sa.Numeric(18, 2), nullable=False),
        sa.Column("estimated_fee", sa.Numeric(18, 2), nullable=False),
        sa.Column("total_cost", sa.Numeric(18, 2), nullable=False),
        sa.Column("effective_unit_cost", sa.Numeric(8, 6)),
        sa.Column("adjusted_edge", sa.Numeric(8, 6)),
        sa.Column("sizing_status", sa.String(length=30), nullable=False),
        sa.Column("risk_decision", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=100), nullable=False),
        sa.Column("execution_mode", sa.String(length=10), nullable=False),
        sa.Column("promotion_state", sa.String(length=20), nullable=False),
        sa.Column("execution_enabled", sa.Boolean(), nullable=False),
        sa.Column("policy_version", sa.String(length=100), nullable=False),
        sa.Column("policy_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("audit", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], ["nfl_paper_opportunities.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "execution_mode = 'paper' AND promotion_state = 'blocked' AND risk_decision = 'reject' AND NOT execution_enabled",
            name="ck_nfl_paper_preflight_safety",
        ),
        sa.CheckConstraint(
            "direction IN ('yes', 'no') AND sizing_status IN ('cost_qualified', 'cost_disqualified', 'ineligible')",
            name="ck_nfl_paper_preflight_state",
        ),
        sa.CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$' AND policy_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_nfl_paper_preflight_identity",
        ),
        sa.CheckConstraint(
            "capital_cap > 0 AND quantity >= 0 AND gross_cost >= 0 AND estimated_fee >= 0 AND total_cost = gross_cost + estimated_fee AND total_cost <= capital_cap",
            name="ck_nfl_paper_preflight_costs",
        ),
        sa.CheckConstraint(
            "(quantity = 0 AND effective_unit_cost IS NULL AND adjusted_edge IS NULL) OR (quantity > 0 AND execution_price > 0 AND execution_price < 1 AND effective_unit_cost > 0 AND effective_unit_cost < 1 AND adjusted_edge = round(expected_payout - effective_unit_cost, 6))",
            name="ck_nfl_paper_preflight_math",
        ),
        sa.CheckConstraint("jsonb_typeof(audit) = 'object'", name="ck_nfl_paper_preflight_audit"),
    )
    op.create_index("ix_nfl_paper_preflights_reviewed", "nfl_paper_preflights", ["reviewed_at"])


def downgrade() -> None:
    raise RuntimeError("Refusing to discard immutable NFL paper preflight audit history")
