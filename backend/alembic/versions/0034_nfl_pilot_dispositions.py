"""Add recommendation-gated paper-only NFL pilot dispositions."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0034_nfl_pilot_dispositions"
down_revision = "0033_nfl_pilot_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "nfl_pilot_positions", sa.Column("remaining_quantity", sa.Integer(), nullable=True)
    )
    op.add_column(
        "nfl_pilot_positions", sa.Column("disposed_quantity", sa.Integer(), nullable=True)
    )
    op.add_column(
        "nfl_pilot_positions", sa.Column("remaining_cost_basis", sa.Numeric(18, 2), nullable=True)
    )
    op.execute(
        "UPDATE nfl_pilot_positions SET remaining_quantity = quantity, disposed_quantity = 0, "
        "remaining_cost_basis = total_cost_basis"
    )
    op.alter_column("nfl_pilot_positions", "remaining_quantity", nullable=False)
    op.alter_column("nfl_pilot_positions", "disposed_quantity", nullable=False)
    op.alter_column("nfl_pilot_positions", "remaining_cost_basis", nullable=False)
    op.drop_constraint("ck_nfl_pilot_positions_paper", "nfl_pilot_positions", type_="check")
    op.drop_constraint("ck_nfl_pilot_positions_values", "nfl_pilot_positions", type_="check")
    op.create_check_constraint(
        "ck_nfl_pilot_positions_paper",
        "nfl_pilot_positions",
        "execution_mode = 'paper' AND NOT live_trading_enabled AND status IN ('open', 'closed', 'settled')",
    )
    op.create_check_constraint(
        "ck_nfl_pilot_positions_values",
        "nfl_pilot_positions",
        "total_cost_basis > 0 AND remaining_quantity >= 0 AND disposed_quantity >= 0 AND "
        "remaining_quantity + disposed_quantity = quantity AND remaining_cost_basis >= 0 AND "
        "market_value >= 0 AND (status = 'open' OR (status IN ('closed', 'settled') AND "
        "remaining_quantity = 0 AND remaining_cost_basis = 0 AND market_value = 0))",
    )
    op.create_table(
        "nfl_pilot_disposition_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("market_price_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("execution_price", sa.Numeric(8, 6), nullable=False),
        sa.Column("gross_proceeds", sa.Numeric(18, 2), nullable=False),
        sa.Column("allocated_cost_basis", sa.Numeric(18, 2), nullable=False),
        sa.Column("realized_pnl_increment", sa.Numeric(18, 2), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("execution_mode", sa.String(10), nullable=False),
        sa.Column("live_trading_enabled", sa.Boolean(), nullable=False),
        sa.Column("audit", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["decision_id"], ["nfl_pilot_monitoring_decisions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["position_id"], ["nfl_pilot_positions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["market_price_id"], ["market_prices.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("idempotency_key", name="uq_nfl_pilot_disposition_events_key"),
        sa.UniqueConstraint("decision_id", name="uq_nfl_pilot_disposition_events_decision"),
        sa.CheckConstraint("action IN ('reduce', 'close')", name="ck_nfl_pilot_disposition_action"),
        sa.CheckConstraint(
            "quantity > 0 AND gross_proceeds >= 0 AND allocated_cost_basis >= 0",
            name="ck_nfl_pilot_disposition_values",
        ),
        sa.CheckConstraint(
            "execution_mode = 'paper' AND NOT live_trading_enabled",
            name="ck_nfl_pilot_disposition_paper",
        ),
        sa.CheckConstraint("jsonb_typeof(audit) = 'object'", name="ck_nfl_pilot_disposition_audit"),
    )
    op.create_index(
        "ix_nfl_pilot_disposition_position_recorded",
        "nfl_pilot_disposition_events",
        ["position_id", "recorded_at"],
    )


def downgrade() -> None:
    raise RuntimeError("Refusing to discard NFL paper disposition audit history")
