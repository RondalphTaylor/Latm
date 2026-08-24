"""Add immutable readiness-gated MLB fitted research artifacts.

Revision ID: 0019_mlb_fitted_research_models
Revises: 0018_mlb_backfill_workflow
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0019_mlb_fitted_research_models"
down_revision: str | None = "0018_mlb_backfill_workflow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mlb_fitted_research_models",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("effective_model_version", sa.String(150), nullable=False),
        sa.Column("algorithm", sa.String(100), nullable=False),
        sa.Column("fitting_policy_fingerprint", sa.String(64), nullable=False),
        sa.Column("readiness_policy_fingerprint", sa.String(64), nullable=False),
        sa.Column("split_policy_fingerprint", sa.String(64), nullable=False),
        sa.Column("training_data_fingerprint", sa.String(64), nullable=False),
        sa.Column("model_fingerprint", sa.String(64), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("selected_features", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("selected_regularization_strength", sa.Numeric(12, 6), nullable=False),
        sa.Column("standardized_intercept", sa.Numeric(24, 12), nullable=False),
        sa.Column(
            "standardized_coefficients",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("feature_means", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("feature_scales", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("train_example_count", sa.Integer(), nullable=False),
        sa.Column("validation_example_count", sa.Integer(), nullable=False),
        sa.Column("test_example_count", sa.Integer(), nullable=False),
        sa.Column("validation_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("test_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("candidate_results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("readiness_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("research_only", sa.Boolean(), nullable=False),
        sa.Column("operational_probability_enabled", sa.Boolean(), nullable=False),
        sa.Column("automatic_trading_enabled", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "effective_model_version",
            name="uq_mlb_fitted_research_models_version",
        ),
        sa.UniqueConstraint(
            "model_fingerprint",
            name="uq_mlb_fitted_research_models_fingerprint",
        ),
        sa.UniqueConstraint(
            "input_fingerprint",
            name="uq_mlb_fitted_research_models_input",
        ),
        sa.CheckConstraint(
            "train_example_count >= 500 AND validation_example_count >= 150 "
            "AND test_example_count >= 150",
            name="ck_mlb_fitted_research_models_readiness",
        ),
        sa.CheckConstraint(
            "selected_regularization_strength > 0",
            name="ck_mlb_fitted_research_models_regularization",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(selected_features) = 'array' "
            "AND jsonb_array_length(selected_features) = 8 "
            "AND jsonb_typeof(standardized_coefficients) = 'object' "
            "AND jsonb_typeof(feature_means) = 'object' "
            "AND jsonb_typeof(feature_scales) = 'object' "
            "AND jsonb_typeof(validation_metrics) = 'object' "
            "AND jsonb_typeof(test_metrics) = 'object' "
            "AND jsonb_typeof(candidate_results) = 'array' "
            "AND jsonb_array_length(candidate_results) > 0 "
            "AND jsonb_typeof(readiness_snapshot) = 'object' "
            "AND jsonb_typeof(source_manifest) = 'array'",
            name="ck_mlb_fitted_research_models_json",
        ),
        sa.CheckConstraint(
            "jsonb_array_length(source_manifest) = "
            "train_example_count + validation_example_count + test_example_count",
            name="ck_mlb_fitted_research_models_manifest_count",
        ),
        sa.CheckConstraint(
            "research_only = true AND operational_probability_enabled = false "
            "AND automatic_trading_enabled = false",
            name="ck_mlb_fitted_research_models_safety",
        ),
        sa.CheckConstraint(
            "fitting_policy_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND readiness_policy_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND split_policy_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND training_data_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND model_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_mlb_fitted_research_models_fingerprints",
        ),
    )
    op.create_index(
        "ix_mlb_fitted_research_models_name_fitted",
        "mlb_fitted_research_models",
        ["model_name", "fitted_at"],
    )

    op.create_table(
        "mlb_fitted_research_model_examples",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.Uuid(), nullable=False),
        sa.Column("example_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("split", sa.String(30), nullable=False),
        sa.Column("availability_basis", sa.String(30), nullable=False),
        sa.Column("example_fingerprint", sa.String(64), nullable=False),
        sa.Column("research_only", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["example_id"],
            ["mlb_labeled_feature_examples.id"],
            name="fk_mlb_fitted_model_examples_example",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"],
            ["mlb_fitted_research_models.id"],
            name="fk_mlb_fitted_model_examples_model",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "model_id",
            "example_id",
            name="uq_mlb_fitted_model_examples_example",
        ),
        sa.UniqueConstraint(
            "model_id",
            "ordinal",
            name="uq_mlb_fitted_model_examples_ordinal",
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_mlb_fitted_model_examples_ordinal"),
        sa.CheckConstraint(
            "split IN ('train', 'validation', 'test')",
            name="ck_mlb_fitted_model_examples_split",
        ),
        sa.CheckConstraint(
            "availability_basis IN ('operational_pregame', 'retrospective')",
            name="ck_mlb_fitted_model_examples_basis",
        ),
        sa.CheckConstraint(
            "example_fingerprint ~ '^[0-9a-f]{64}$' AND research_only = true",
            name="ck_mlb_fitted_model_examples_safety",
        ),
    )
    op.create_index(
        "ix_mlb_fitted_model_examples_model_split_ordinal",
        "mlb_fitted_research_model_examples",
        ["model_id", "split", "ordinal"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mlb_fitted_model_examples_model_split_ordinal",
        table_name="mlb_fitted_research_model_examples",
    )
    op.drop_table("mlb_fitted_research_model_examples")
    op.drop_index(
        "ix_mlb_fitted_research_models_name_fitted",
        table_name="mlb_fitted_research_models",
    )
    op.drop_table("mlb_fitted_research_models")
