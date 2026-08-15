"""Create append-only deterministic risk decisions.

Revision ID: 0008_risk_engine
Revises: 0007_portfolio_sizing
Create Date: 2026-08-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008_risk_engine"
down_revision: str | None = "0007_portfolio_sizing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add risk authorization history and future-proof proposal representation."""
    op.drop_constraint(
        "ck_position_size_proposals_exposure",
        "position_size_proposals",
        type_="check",
    )
    op.create_check_constraint(
        "ck_position_size_proposals_exposure",
        "position_size_proposals",
        "target_exposure_fraction > 0 "
        "AND proposed_exposure_fraction > 0 "
        "AND proposed_exposure_fraction <= target_exposure_fraction "
        "AND target_exposure_fraction <= max_exposure_fraction "
        "AND max_exposure_fraction <= 1",
    )
    op.create_table(
        "risk_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("position_size_proposal_id", sa.Uuid(), nullable=False),
        sa.Column("portfolio_id", sa.Uuid(), nullable=False),
        sa.Column("portfolio_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("market_id", sa.Uuid(), nullable=False),
        sa.Column("outcome_team_id", sa.Uuid(), nullable=False),
        sa.Column("market_event_match_id", sa.Uuid(), nullable=False),
        sa.Column("market_price_id", sa.Uuid(), nullable=False),
        sa.Column("base_forecast_id", sa.Uuid(), nullable=False),
        sa.Column("execution_mode", sa.String(length=10), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("decision", sa.String(length=40), nullable=False),
        sa.Column("escalation_band", sa.String(length=50), nullable=False),
        sa.Column("primary_reason_code", sa.String(length=100), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("all_required_checks_passed", sa.Boolean(), nullable=False),
        sa.Column("hard_failure_count", sa.Integer(), nullable=False),
        sa.Column(
            "failed_rules",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "check_results",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("proposed_capital", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column(
            "proposal_available_bankroll",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
        ),
        sa.Column(
            "current_available_bankroll",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
        ),
        sa.Column(
            "current_authorized_capital",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
        ),
        sa.Column(
            "remaining_authorizable_bankroll",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
        ),
        sa.Column(
            "proposed_exposure_fraction",
            sa.Numeric(precision=12, scale=10),
            nullable=False,
        ),
        sa.Column(
            "recomputed_exposure_fraction",
            sa.Numeric(precision=12, scale=10),
            nullable=False,
        ),
        sa.Column("reference_price", sa.Numeric(precision=7, scale=6), nullable=False),
        sa.Column("model_probability", sa.Numeric(precision=7, scale=6), nullable=False),
        sa.Column("raw_edge", sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column("edge_basis", sa.String(length=30), nullable=False),
        sa.Column("adjusted_edge_basis", sa.String(length=30), nullable=False),
        sa.Column("confidence_basis", sa.String(length=30), nullable=False),
        sa.Column("liquidity_basis", sa.String(length=40), nullable=False),
        sa.Column("match_confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("market_price_age_seconds", sa.Integer(), nullable=False),
        sa.Column("forecast_age_seconds", sa.Integer(), nullable=False),
        sa.Column("risk_policy_name", sa.String(length=50), nullable=False),
        sa.Column("risk_policy_version", sa.String(length=100), nullable=False),
        sa.Column("risk_policy_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "auto_approve_exposure_max",
            sa.Numeric(precision=12, scale=10),
            nullable=False,
        ),
        sa.Column(
            "high_confidence_auto_approve_max",
            sa.Numeric(precision=12, scale=10),
            nullable=False,
        ),
        sa.Column("min_raw_edge", sa.Numeric(precision=12, scale=10), nullable=False),
        sa.Column(
            "min_match_confidence",
            sa.Numeric(precision=12, scale=10),
            nullable=False,
        ),
        sa.Column("max_market_price_age_seconds", sa.Integer(), nullable=False),
        sa.Column(
            "max_operational_forecast_age_seconds",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column("authorization_ttl_seconds", sa.Integer(), nullable=False),
        sa.Column("proposal_strategy_name", sa.String(length=50), nullable=False),
        sa.Column("proposal_strategy_version", sa.String(length=100), nullable=False),
        sa.Column("proposal_input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("opportunity_input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorization_valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "audit_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.CheckConstraint(
            "hard_failure_count >= 0 "
            "AND hard_failure_count = jsonb_array_length(failed_rules) "
            "AND jsonb_array_length(check_results) > 0",
            name="ck_risk_decisions_check_counts",
        ),
        sa.CheckConstraint(
            "confidence_basis = 'not_available' "
            "AND adjusted_edge_basis = 'not_available' "
            "AND liquidity_basis = 'not_evaluated_phase7' "
            "AND edge_basis = 'raw_edge'",
            name="ck_risk_decisions_evidence_bases",
        ),
        sa.CheckConstraint(
            "proposed_exposure_fraction > 0 AND proposed_exposure_fraction <= 1 "
            "AND recomputed_exposure_fraction >= 0 "
            "AND recomputed_exposure_fraction <= 1",
            name="ck_risk_decisions_exposure",
        ),
        sa.CheckConstraint(
            "length(risk_policy_fingerprint) = 64 "
            "AND length(proposal_input_fingerprint) = 64 "
            "AND length(opportunity_input_fingerprint) = 64 "
            "AND length(input_fingerprint) = 64",
            name="ck_risk_decisions_fingerprints",
        ),
        sa.CheckConstraint(
            "match_confidence >= 0 AND match_confidence <= 1",
            name="ck_risk_decisions_match_confidence",
        ),
        sa.CheckConstraint(
            "(decision = 'reject' AND all_required_checks_passed = false "
            "AND hard_failure_count > 0 AND authorization_valid_until IS NULL) OR "
            "(decision = 'auto_approve' AND all_required_checks_passed = true "
            "AND hard_failure_count = 0 "
            "AND proposed_exposure_fraction < auto_approve_exposure_max "
            "AND authorization_valid_until IS NOT NULL) OR "
            "(decision = 'require_human_approval' "
            "AND all_required_checks_passed = true AND hard_failure_count = 0 "
            "AND proposed_exposure_fraction >= auto_approve_exposure_max "
            "AND authorization_valid_until IS NOT NULL)",
            name="ck_risk_decisions_outcome_consistency",
        ),
        sa.CheckConstraint(
            "execution_mode = 'paper'",
            name="ck_risk_decisions_paper_only",
        ),
        sa.CheckConstraint(
            "direction IN ('yes', 'no')",
            name="ck_risk_decisions_direction",
        ),
        sa.CheckConstraint(
            "auto_approve_exposure_max > 0 "
            "AND auto_approve_exposure_max < high_confidence_auto_approve_max "
            "AND high_confidence_auto_approve_max <= 1",
            name="ck_risk_decisions_policy_exposure",
        ),
        sa.CheckConstraint(
            "min_raw_edge >= 0 AND min_raw_edge <= 1 "
            "AND min_match_confidence >= 0 AND min_match_confidence <= 1 "
            "AND max_market_price_age_seconds > 0 "
            "AND max_operational_forecast_age_seconds > 0 "
            "AND authorization_ttl_seconds > 0",
            name="ck_risk_decisions_policy_limits",
        ),
        sa.CheckConstraint(
            "reference_price > 0 AND reference_price < 1 "
            "AND model_probability >= 0 AND model_probability <= 1 "
            "AND raw_edge >= -1 AND raw_edge <= 1",
            name="ck_risk_decisions_probability_values",
        ),
        sa.CheckConstraint(
            "proposed_capital > 0 AND proposal_available_bankroll > 0 "
            "AND current_available_bankroll >= 0 "
            "AND current_authorized_capital >= 0",
            name="ck_risk_decisions_capital",
        ),
        sa.CheckConstraint(
            "decision IN ('reject', 'auto_approve', 'require_human_approval')",
            name="ck_risk_decisions_decision",
        ),
        sa.CheckConstraint(
            "escalation_band IN ('hard_rejection', 'automatic', "
            "'medium_confidence_unavailable', 'large_exposure')",
            name="ck_risk_decisions_escalation_band",
        ),
        sa.CheckConstraint(
            "authorization_valid_until IS NULL OR authorization_valid_until >= evaluated_at",
            name="ck_risk_decisions_validity",
        ),
        sa.ForeignKeyConstraint(["base_forecast_id"], ["base_forecasts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["market_event_match_id"], ["market_event_matches.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["market_price_id"], ["market_prices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["opportunity_id"], ["opportunities.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["outcome_team_id"], ["teams.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["portfolio_snapshot_id"], ["portfolio_snapshots.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["position_size_proposal_id"], ["position_size_proposals.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "position_size_proposal_id",
            "risk_policy_version",
            "input_fingerprint",
            name="uq_risk_decisions_semantic_input",
        ),
    )
    op.create_index(
        "ix_risk_decisions_active_intent",
        "risk_decisions",
        [
            "portfolio_id",
            "market_id",
            "direction",
            "outcome_team_id",
            "authorization_valid_until",
        ],
    )
    op.create_index(
        "ix_risk_decisions_decision_evaluated",
        "risk_decisions",
        ["decision", "evaluated_at"],
    )
    op.create_index(
        "ix_risk_decisions_market_evaluated",
        "risk_decisions",
        ["market_id", "evaluated_at"],
    )
    op.create_index(
        "ix_risk_decisions_portfolio_evaluated",
        "risk_decisions",
        ["portfolio_id", "evaluated_at"],
    )
    op.create_index(
        "ix_risk_decisions_proposal_evaluated",
        "risk_decisions",
        ["position_size_proposal_id", "evaluated_at"],
    )


def downgrade() -> None:
    """Remove risk history and restore the original Phase 6 structural cap."""
    op.drop_index("ix_risk_decisions_proposal_evaluated", table_name="risk_decisions")
    op.drop_index("ix_risk_decisions_portfolio_evaluated", table_name="risk_decisions")
    op.drop_index("ix_risk_decisions_market_evaluated", table_name="risk_decisions")
    op.drop_index("ix_risk_decisions_decision_evaluated", table_name="risk_decisions")
    op.drop_index("ix_risk_decisions_active_intent", table_name="risk_decisions")
    op.drop_table("risk_decisions")
    op.drop_constraint(
        "ck_position_size_proposals_exposure",
        "position_size_proposals",
        type_="check",
    )
    op.create_check_constraint(
        "ck_position_size_proposals_exposure",
        "position_size_proposals",
        "target_exposure_fraction > 0 "
        "AND proposed_exposure_fraction > 0 "
        "AND proposed_exposure_fraction <= target_exposure_fraction "
        "AND target_exposure_fraction <= max_exposure_fraction "
        "AND max_exposure_fraction < 0.10",
    )
