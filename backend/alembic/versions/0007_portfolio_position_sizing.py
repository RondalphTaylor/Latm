"""Create paper portfolios and advisory position-size proposals.

Revision ID: 0007_portfolio_sizing
Revises: 0006_opportunities
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_portfolio_sizing"
down_revision: str | None = "0006_opportunities"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create paper-only capital state and pre-risk sizing audit tables."""
    op.create_table(
        "portfolios",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("execution_mode", sa.String(length=10), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("starting_bankroll", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("creation_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("currency = 'USD'", name="ck_portfolios_currency"),
        sa.CheckConstraint(
            "length(creation_fingerprint) = 64",
            name="ck_portfolios_creation_fingerprint",
        ),
        sa.CheckConstraint("execution_mode = 'paper'", name="ck_portfolios_paper_only"),
        sa.CheckConstraint(
            "starting_bankroll > 0",
            name="ck_portfolios_starting_bankroll",
        ),
        sa.CheckConstraint("status = 'active'", name="ck_portfolios_status"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_portfolios_idempotency_key"),
        sa.UniqueConstraint("name", name="uq_portfolios_name"),
    )
    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("portfolio_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("execution_mode", sa.String(length=10), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("starting_bankroll", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("current_bankroll", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("cash_balance", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("reserved_capital", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("committed_capital", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("available_bankroll", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("reason", sa.String(length=30), nullable=False),
        sa.Column("state_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "available_bankroll = cash_balance - reserved_capital",
            name="ck_portfolio_snapshots_available_bankroll",
        ),
        sa.CheckConstraint(
            "cash_balance = current_bankroll - committed_capital",
            name="ck_portfolio_snapshots_cash_balance",
        ),
        sa.CheckConstraint(
            "(reason <> 'created') OR (sequence = 0 "
            "AND current_bankroll = starting_bankroll "
            "AND cash_balance = starting_bankroll "
            "AND available_bankroll = starting_bankroll "
            "AND reserved_capital = 0 AND committed_capital = 0 AND realized_pnl = 0)",
            name="ck_portfolio_snapshots_created_state",
        ),
        sa.CheckConstraint(
            "currency = 'USD'",
            name="ck_portfolio_snapshots_currency",
        ),
        sa.CheckConstraint(
            "current_bankroll = starting_bankroll + realized_pnl",
            name="ck_portfolio_snapshots_current_bankroll",
        ),
        sa.CheckConstraint(
            "length(state_fingerprint) = 64",
            name="ck_portfolio_snapshots_state_fingerprint",
        ),
        sa.CheckConstraint(
            "starting_bankroll > 0 AND current_bankroll >= 0 "
            "AND cash_balance >= 0 AND reserved_capital >= 0 "
            "AND committed_capital >= 0 AND available_bankroll >= 0",
            name="ck_portfolio_snapshots_nonnegative_balances",
        ),
        sa.CheckConstraint(
            "execution_mode = 'paper'",
            name="ck_portfolio_snapshots_paper_only",
        ),
        sa.CheckConstraint(
            "reason = 'created'",
            name="ck_portfolio_snapshots_reason",
        ),
        sa.CheckConstraint("sequence >= 0", name="ck_portfolio_snapshots_sequence"),
        sa.CheckConstraint(
            "committed_capital + reserved_capital <= current_bankroll",
            name="ck_portfolio_snapshots_total_capital",
        ),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolios.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "portfolio_id",
            name="uq_portfolio_snapshots_id_portfolio",
        ),
        sa.UniqueConstraint(
            "portfolio_id",
            "sequence",
            name="uq_portfolio_snapshots_sequence",
        ),
    )
    op.create_index(
        "ix_portfolio_snapshots_portfolio_captured",
        "portfolio_snapshots",
        ["portfolio_id", "captured_at"],
    )
    op.create_table(
        "position_size_proposals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("portfolio_id", sa.Uuid(), nullable=False),
        sa.Column("portfolio_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("market_id", sa.Uuid(), nullable=False),
        sa.Column("outcome_team_id", sa.Uuid(), nullable=False),
        sa.Column("execution_mode", sa.String(length=10), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("confidence_basis", sa.String(length=30), nullable=False),
        sa.Column("reference_price", sa.Numeric(precision=7, scale=6), nullable=False),
        sa.Column("model_probability", sa.Numeric(precision=7, scale=6), nullable=False),
        sa.Column("raw_edge", sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column("available_bankroll", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("target_exposure_fraction", sa.Numeric(precision=7, scale=6), nullable=False),
        sa.Column(
            "proposed_exposure_fraction",
            sa.Numeric(precision=12, scale=10),
            nullable=False,
        ),
        sa.Column("proposed_capital", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("strategy_name", sa.String(length=50), nullable=False),
        sa.Column("strategy_version", sa.String(length=100), nullable=False),
        sa.Column("candidate_min_raw_edge", sa.Numeric(precision=7, scale=6), nullable=False),
        sa.Column("strong_min_raw_edge", sa.Numeric(precision=7, scale=6), nullable=False),
        sa.Column("very_strong_min_raw_edge", sa.Numeric(precision=7, scale=6), nullable=False),
        sa.Column(
            "candidate_exposure_fraction",
            sa.Numeric(precision=7, scale=6),
            nullable=False,
        ),
        sa.Column(
            "strong_exposure_fraction",
            sa.Numeric(precision=7, scale=6),
            nullable=False,
        ),
        sa.Column(
            "very_strong_exposure_fraction",
            sa.Numeric(precision=7, scale=6),
            nullable=False,
        ),
        sa.Column("max_exposure_fraction", sa.Numeric(precision=7, scale=6), nullable=False),
        sa.Column("policy_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("opportunity_strategy_name", sa.String(length=50), nullable=False),
        sa.Column("opportunity_strategy_version", sa.String(length=100), nullable=False),
        sa.Column("opportunity_input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("opportunity_evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("opportunity_valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("proposed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column(
            "audit_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.CheckConstraint(
            "proposed_exposure_fraction = trunc(proposed_capital / available_bankroll, 10)",
            name="ck_position_size_proposals_actual_exposure",
        ),
        sa.CheckConstraint(
            "available_bankroll > 0 AND proposed_capital > 0 "
            "AND proposed_capital <= available_bankroll",
            name="ck_position_size_proposals_capital",
        ),
        sa.CheckConstraint(
            "confidence_basis = 'not_available'",
            name="ck_position_size_proposals_confidence",
        ),
        sa.CheckConstraint(
            "direction IN ('yes', 'no')",
            name="ck_position_size_proposals_direction",
        ),
        sa.CheckConstraint(
            "candidate_min_raw_edge < strong_min_raw_edge "
            "AND strong_min_raw_edge < very_strong_min_raw_edge",
            name="ck_position_size_proposals_edge_bands",
        ),
        sa.CheckConstraint(
            "target_exposure_fraction > 0 "
            "AND proposed_exposure_fraction > 0 "
            "AND proposed_exposure_fraction <= target_exposure_fraction "
            "AND target_exposure_fraction <= max_exposure_fraction "
            "AND max_exposure_fraction < 0.10",
            name="ck_position_size_proposals_exposure",
        ),
        sa.CheckConstraint(
            "candidate_exposure_fraction < strong_exposure_fraction "
            "AND strong_exposure_fraction < very_strong_exposure_fraction "
            "AND very_strong_exposure_fraction <= max_exposure_fraction",
            name="ck_position_size_proposals_exposure_bands",
        ),
        sa.CheckConstraint(
            "length(policy_fingerprint) = 64 "
            "AND length(input_fingerprint) = 64 "
            "AND length(opportunity_input_fingerprint) = 64",
            name="ck_position_size_proposals_fingerprints",
        ),
        sa.CheckConstraint(
            "execution_mode = 'paper'",
            name="ck_position_size_proposals_paper_only",
        ),
        sa.CheckConstraint(
            "reference_price > 0 AND reference_price < 1 "
            "AND model_probability >= 0 AND model_probability <= 1",
            name="ck_position_size_proposals_probabilities",
        ),
        sa.CheckConstraint(
            "raw_edge >= 0 AND raw_edge <= 1 AND raw_edge = model_probability - reference_price",
            name="ck_position_size_proposals_raw_edge",
        ),
        sa.CheckConstraint(
            "state = 'awaiting_risk'",
            name="ck_position_size_proposals_state",
        ),
        sa.CheckConstraint(
            "opportunity_evaluated_at <= proposed_at AND proposed_at <= opportunity_valid_until",
            name="ck_position_size_proposals_times",
        ),
        sa.ForeignKeyConstraint(["market_id"], ["markets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["opportunity_id"], ["opportunities.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["outcome_team_id"], ["teams.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["portfolio_snapshot_id", "portfolio_id"],
            ["portfolio_snapshots.id", "portfolio_snapshots.portfolio_id"],
            name="fk_position_size_proposals_snapshot_portfolio",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "portfolio_snapshot_id",
            "opportunity_id",
            "strategy_version",
            "input_fingerprint",
            name="uq_position_size_proposals_semantic_input",
        ),
    )
    op.create_index(
        "ix_position_size_proposals_opportunity",
        "position_size_proposals",
        ["opportunity_id"],
    )
    op.create_index(
        "ix_position_size_proposals_portfolio_proposed",
        "position_size_proposals",
        ["portfolio_id", "proposed_at"],
    )
    op.create_index(
        "ix_position_size_proposals_state_proposed",
        "position_size_proposals",
        ["state", "proposed_at"],
    )


def downgrade() -> None:
    """Drop advisory sizing and paper-portfolio state."""
    op.drop_index(
        "ix_position_size_proposals_state_proposed",
        table_name="position_size_proposals",
    )
    op.drop_index(
        "ix_position_size_proposals_portfolio_proposed",
        table_name="position_size_proposals",
    )
    op.drop_index(
        "ix_position_size_proposals_opportunity",
        table_name="position_size_proposals",
    )
    op.drop_table("position_size_proposals")
    op.drop_index(
        "ix_portfolio_snapshots_portfolio_captured",
        table_name="portfolio_snapshots",
    )
    op.drop_table("portfolio_snapshots")
    op.drop_table("portfolios")
