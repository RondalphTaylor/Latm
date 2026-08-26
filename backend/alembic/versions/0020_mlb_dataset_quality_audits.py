"""Add immutable MLB canonical-dataset quality audits.

Revision ID: 0020_mlb_dataset_quality_audits
Revises: 0019_mlb_fitted_research_models
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0020_mlb_dataset_quality_audits"
down_revision: str | None = "0019_mlb_fitted_research_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mlb_dataset_quality_audits",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("policy_name", sa.String(100), nullable=False),
        sa.Column("policy_version", sa.String(100), nullable=False),
        sa.Column("policy_fingerprint", sa.String(64), nullable=False),
        sa.Column("readiness_policy_fingerprint", sa.String(64), nullable=False),
        sa.Column("split_policy_fingerprint", sa.String(64), nullable=False),
        sa.Column("feature_policy_fingerprint", sa.String(64), nullable=False),
        sa.Column("source_data_fingerprint", sa.String(64), nullable=False),
        sa.Column("report_fingerprint", sa.String(64), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("selected_example_count", sa.Integer(), nullable=False),
        sa.Column("operational_example_count", sa.Integer(), nullable=False),
        sa.Column("retrospective_example_count", sa.Integer(), nullable=False),
        sa.Column("unique_event_count", sa.Integer(), nullable=False),
        sa.Column("unique_team_count", sa.Integer(), nullable=False),
        sa.Column("home_win_count", sa.Integer(), nullable=False),
        sa.Column("away_win_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("quality_passed", sa.Boolean(), nullable=False),
        sa.Column("first_scheduled_start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_scheduled_start_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("readiness_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("research_only", sa.Boolean(), nullable=False),
        sa.Column("probability_generated", sa.Boolean(), nullable=False),
        sa.Column("automatic_trading_eligible", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "input_fingerprint",
            name="uq_mlb_dataset_quality_audits_input",
        ),
        sa.CheckConstraint(
            "selected_example_count >= 0 "
            "AND operational_example_count >= 0 "
            "AND retrospective_example_count >= 0 "
            "AND unique_event_count >= 0 "
            "AND unique_team_count >= 0 "
            "AND home_win_count >= 0 "
            "AND away_win_count >= 0 "
            "AND error_count >= 0 "
            "AND warning_count >= 0",
            name="ck_mlb_dataset_quality_audits_counts",
        ),
        sa.CheckConstraint(
            "operational_example_count + retrospective_example_count = selected_example_count "
            "AND home_win_count + away_win_count = selected_example_count "
            "AND unique_event_count <= selected_example_count",
            name="ck_mlb_dataset_quality_audits_reconciliation",
        ),
        sa.CheckConstraint(
            "quality_passed = (error_count = 0)",
            name="ck_mlb_dataset_quality_audits_status",
        ),
        sa.CheckConstraint(
            "(selected_example_count = 0 "
            "AND first_scheduled_start_time IS NULL "
            "AND last_scheduled_start_time IS NULL) OR "
            "(selected_example_count > 0 "
            "AND first_scheduled_start_time IS NOT NULL "
            "AND last_scheduled_start_time IS NOT NULL "
            "AND first_scheduled_start_time <= last_scheduled_start_time)",
            name="ck_mlb_dataset_quality_audits_time_range",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(report) = 'object' "
            "AND jsonb_typeof(readiness_snapshot) = 'object' "
            "AND jsonb_typeof(source_manifest) = 'array' "
            "AND jsonb_array_length(source_manifest) = selected_example_count",
            name="ck_mlb_dataset_quality_audits_json",
        ),
        sa.CheckConstraint(
            "policy_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND readiness_policy_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND split_policy_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND feature_policy_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND source_data_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND report_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_mlb_dataset_quality_audits_fingerprints",
        ),
        sa.CheckConstraint(
            "research_only = true AND probability_generated = false "
            "AND automatic_trading_eligible = false",
            name="ck_mlb_dataset_quality_audits_safety",
        ),
    )
    op.create_index(
        "ix_mlb_dataset_quality_audits_evaluated",
        "mlb_dataset_quality_audits",
        ["evaluated_at"],
    )

    op.create_table(
        "mlb_dataset_quality_audit_examples",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("audit_id", sa.Uuid(), nullable=False),
        sa.Column("example_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("split", sa.String(30), nullable=False),
        sa.Column("availability_basis", sa.String(30), nullable=False),
        sa.Column("example_fingerprint", sa.String(64), nullable=False),
        sa.Column("feature_vector_input_fingerprint", sa.String(64), nullable=False),
        sa.Column("research_only", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["audit_id"],
            ["mlb_dataset_quality_audits.id"],
            name="fk_mlb_dataset_quality_audit_examples_audit",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["example_id"],
            ["mlb_labeled_feature_examples.id"],
            name="fk_mlb_dataset_quality_audit_examples_example",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "audit_id",
            "example_id",
            name="uq_mlb_dataset_quality_audit_examples_example",
        ),
        sa.UniqueConstraint(
            "audit_id",
            "ordinal",
            name="uq_mlb_dataset_quality_audit_examples_ordinal",
        ),
        sa.CheckConstraint(
            "ordinal >= 0",
            name="ck_mlb_dataset_quality_audit_examples_ordinal",
        ),
        sa.CheckConstraint(
            "split IN ('train', 'validation', 'test', 'prospective_holdout') "
            "AND availability_basis IN ('operational_pregame', 'retrospective')",
            name="ck_mlb_dataset_quality_audit_examples_roles",
        ),
        sa.CheckConstraint(
            "example_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND feature_vector_input_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND research_only = true",
            name="ck_mlb_dataset_quality_audit_examples_safety",
        ),
    )
    op.create_index(
        "ix_mlb_dataset_quality_audit_examples_audit_split_ordinal",
        "mlb_dataset_quality_audit_examples",
        ["audit_id", "split", "ordinal"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mlb_dataset_quality_audit_examples_audit_split_ordinal",
        table_name="mlb_dataset_quality_audit_examples",
    )
    op.drop_table("mlb_dataset_quality_audit_examples")
    op.drop_index(
        "ix_mlb_dataset_quality_audits_evaluated",
        table_name="mlb_dataset_quality_audits",
    )
    op.drop_table("mlb_dataset_quality_audits")
