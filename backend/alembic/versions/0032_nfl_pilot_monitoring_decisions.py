"""Add immutable NFL pilot monitoring decisions."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0032_nfl_pilot_monitoring"
down_revision = "0031_nfl_pilot_quote_checks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nfl_pilot_monitoring_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recommendation", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(100), nullable=False),
        sa.Column("requires_attention", sa.Boolean(), nullable=False),
        sa.Column("remaining_edge", sa.Numeric(8, 6)),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("execution_mode", sa.String(10), nullable=False),
        sa.Column("live_trading_enabled", sa.Boolean(), nullable=False),
        sa.Column("audit", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["position_id"], ["nfl_pilot_positions.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("idempotency_key", name="uq_nfl_pilot_monitoring_decision_key"),
        sa.CheckConstraint(
            "recommendation IN ('hold', 'reduce', 'close')",
            name="ck_nfl_pilot_monitoring_decision_action",
        ),
        sa.CheckConstraint(
            "execution_mode = 'paper' AND NOT live_trading_enabled",
            name="ck_nfl_pilot_monitoring_decision_paper",
        ),
    )
    op.create_index(
        "ix_nfl_pilot_monitoring_decision_position_evaluated",
        "nfl_pilot_monitoring_decisions",
        ["position_id", "evaluated_at"],
    )


def downgrade() -> None:
    raise RuntimeError("Refusing to discard NFL paper monitoring decisions")
