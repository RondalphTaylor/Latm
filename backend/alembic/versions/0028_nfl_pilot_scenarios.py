"""Add frozen NFL paper-pilot scenario settings."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0028_nfl_pilot_scenarios"
down_revision = "0027_nfl_paper_preflights"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nfl_pilot_scenarios",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scenario_key", sa.String(100), nullable=False),
        sa.Column("portfolio_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile", sa.String(20), nullable=False),
        sa.Column("execution_mode", sa.String(10), nullable=False),
        sa.Column("starting_bankroll", sa.Numeric(18, 2), nullable=False),
        sa.Column("per_entry_exposure", sa.Numeric(8, 6), nullable=False),
        sa.Column("aggregate_exposure", sa.Numeric(8, 6), nullable=False),
        sa.Column("minimum_adjusted_edge", sa.Numeric(8, 6), nullable=False),
        sa.Column("live_trading_enabled", sa.Boolean(), nullable=False),
        sa.Column("policy_version", sa.String(100), nullable=False),
        sa.Column("policy_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("audit", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("portfolio_id", name="uq_nfl_pilot_scenarios_portfolio"),
        sa.UniqueConstraint("scenario_key", name="uq_nfl_pilot_scenarios_key"),
        sa.CheckConstraint(
            "execution_mode = 'paper' AND NOT live_trading_enabled",
            name="ck_nfl_pilot_scenarios_paper",
        ),
        sa.CheckConstraint(
            "profile IN ('conservative', 'baseline', 'assertive')",
            name="ck_nfl_pilot_scenarios_profile",
        ),
        sa.CheckConstraint(
            "per_entry_exposure > 0 AND per_entry_exposure < aggregate_exposure AND aggregate_exposure <= 1",
            name="ck_nfl_pilot_scenarios_exposure",
        ),
        sa.CheckConstraint(
            "length(policy_fingerprint) = 64 AND jsonb_typeof(audit) = 'object'",
            name="ck_nfl_pilot_scenarios_audit",
        ),
    )


def downgrade() -> None:
    raise RuntimeError("Refusing to discard frozen NFL pilot settings")
