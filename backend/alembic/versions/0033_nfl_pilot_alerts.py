"""Add deduplicated NFL pilot alert journal."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0033_nfl_pilot_alerts"
down_revision = "0032_nfl_pilot_monitoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nfl_pilot_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("decision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("message", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("execution_mode", sa.String(10), nullable=False),
        sa.Column("live_trading_enabled", sa.Boolean(), nullable=False),
        sa.Column("audit", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["decision_id"], ["nfl_pilot_monitoring_decisions.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("decision_id", name="uq_nfl_pilot_alerts_decision"),
        sa.CheckConstraint(
            "execution_mode = 'paper' AND NOT live_trading_enabled",
            name="ck_nfl_pilot_alerts_paper",
        ),
    )
    op.create_index("ix_nfl_pilot_alerts_created", "nfl_pilot_alerts", ["created_at"])


def downgrade() -> None:
    raise RuntimeError("Refusing to discard NFL paper alert history")
