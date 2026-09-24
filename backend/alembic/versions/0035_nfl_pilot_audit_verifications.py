"""Add append-only NFL pilot audit verification journal."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0035_nfl_pilot_audit_verify"
down_revision = "0034_nfl_pilot_dispositions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "nfl_pilot_audit_verifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scenario_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provided_fingerprint", sa.String(64), nullable=False),
        sa.Column("current_fingerprint", sa.String(64), nullable=False),
        sa.Column("matches", sa.Boolean(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("execution_mode", sa.String(10), nullable=False),
        sa.Column("live_trading_enabled", sa.Boolean(), nullable=False),
        sa.Column("audit", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["scenario_id"], ["nfl_pilot_scenarios.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "length(provided_fingerprint) = 64 AND length(current_fingerprint) = 64",
            name="ck_nfl_pilot_audit_verifications_fingerprints",
        ),
        sa.CheckConstraint(
            "execution_mode = 'paper' AND NOT live_trading_enabled",
            name="ck_nfl_pilot_audit_verifications_paper",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(audit) = 'object'", name="ck_nfl_pilot_audit_verifications_audit"
        ),
    )
    op.create_index(
        "ix_nfl_pilot_audit_verifications_scenario_verified",
        "nfl_pilot_audit_verifications",
        ["scenario_id", "verified_at"],
    )


def downgrade() -> None:
    raise RuntimeError("Refusing to discard immutable NFL pilot audit verification history")
