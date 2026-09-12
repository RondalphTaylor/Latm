"""Add immutable NFL pilot quote-quality checks."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0031_nfl_pilot_quote_checks"
down_revision = "0030_nfl_pilot_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nfl_pilot_quote_checks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("market_price_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quote_status", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(100)),
        sa.Column("directional_bid", sa.Numeric(8, 6)),
        sa.Column("directional_ask", sa.Numeric(8, 6)),
        sa.Column("spread", sa.Numeric(8, 6)),
        sa.Column("liquidity", sa.Numeric(24, 4)),
        sa.Column("quote_retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quote_age_seconds", sa.Integer(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("execution_mode", sa.String(10), nullable=False),
        sa.Column("live_trading_enabled", sa.Boolean(), nullable=False),
        sa.Column("audit", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["position_id"], ["nfl_pilot_positions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["market_price_id"], ["market_prices.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("position_id", "market_price_id", name="uq_nfl_pilot_quote_checks_snapshot"),
        sa.CheckConstraint("quote_status IN ('fresh', 'stale', 'unusable')", name="ck_nfl_pilot_quote_checks_status"),
        sa.CheckConstraint("execution_mode = 'paper' AND NOT live_trading_enabled", name="ck_nfl_pilot_quote_checks_paper"),
        sa.CheckConstraint("quote_age_seconds >= 0", name="ck_nfl_pilot_quote_checks_age"),
        sa.CheckConstraint("jsonb_typeof(audit) = 'object'", name="ck_nfl_pilot_quote_checks_audit"),
    )
    op.create_index(
        "ix_nfl_pilot_quote_checks_position_checked",
        "nfl_pilot_quote_checks",
        ["position_id", "checked_at"],
    )


def downgrade() -> None:
    raise RuntimeError("Refusing to discard NFL paper quote-quality audit history")
