"""Add NFL-only paper position marks and official settlement history."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0030_nfl_pilot_lifecycle"
down_revision = "0029_nfl_pilot_entries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nfl_pilot_positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("market_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("direction", sa.String(3), nullable=False), sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("total_cost_basis", sa.Numeric(18, 2), nullable=False), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("mark_price", sa.Numeric(8, 6)), sa.Column("market_value", sa.Numeric(18, 2), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(18, 2), nullable=False), sa.Column("realized_pnl", sa.Numeric(18, 2), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True)), sa.Column("official_resolution_id", postgresql.UUID(as_uuid=True)),
        sa.Column("execution_mode", sa.String(10), nullable=False), sa.Column("live_trading_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("audit", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["entry_id"], ["nfl_pilot_entries.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["scenario_id"], ["nfl_pilot_scenarios.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["official_resolution_id"], ["market_resolutions.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("entry_id", name="uq_nfl_pilot_positions_entry"),
        sa.CheckConstraint("execution_mode = 'paper' AND NOT live_trading_enabled AND status IN ('open', 'settled')", name="ck_nfl_pilot_positions_paper"),
        sa.CheckConstraint("direction IN ('yes', 'no') AND quantity > 0", name="ck_nfl_pilot_positions_side"),
        sa.CheckConstraint("total_cost_basis > 0 AND market_value >= 0", name="ck_nfl_pilot_positions_values"), sa.CheckConstraint("jsonb_typeof(audit) = 'object'", name="ck_nfl_pilot_positions_audit"),
    )
    op.create_table(
        "nfl_pilot_position_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("market_price_id", postgresql.UUID(as_uuid=True)), sa.Column("official_resolution_id", postgresql.UUID(as_uuid=True)),
        sa.Column("event_type", sa.String(20), nullable=False), sa.Column("mark_price", sa.Numeric(8, 6)), sa.Column("market_value", sa.Numeric(18, 2), nullable=False), sa.Column("unrealized_pnl", sa.Numeric(18, 2), nullable=False), sa.Column("realized_pnl", sa.Numeric(18, 2), nullable=False), sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False), sa.Column("execution_mode", sa.String(10), nullable=False), sa.Column("live_trading_enabled", sa.Boolean(), nullable=False), sa.Column("audit", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["position_id"], ["nfl_pilot_positions.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["market_price_id"], ["market_prices.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["official_resolution_id"], ["market_resolutions.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("idempotency_key", name="uq_nfl_pilot_position_events_idempotency"), sa.UniqueConstraint("position_id", "market_price_id", name="uq_nfl_pilot_position_events_mark"), sa.UniqueConstraint("position_id", "official_resolution_id", name="uq_nfl_pilot_position_events_resolution"),
        sa.CheckConstraint("event_type IN ('mark', 'settlement')", name="ck_nfl_pilot_position_events_type"), sa.CheckConstraint("execution_mode = 'paper' AND NOT live_trading_enabled", name="ck_nfl_pilot_position_events_paper"), sa.CheckConstraint("jsonb_typeof(audit) = 'object'", name="ck_nfl_pilot_position_events_audit"),
    )
    op.create_index("ix_nfl_pilot_position_events_position_recorded", "nfl_pilot_position_events", ["position_id", "recorded_at"])


def downgrade() -> None:
    raise RuntimeError("Refusing to discard NFL paper lifecycle audit history")
