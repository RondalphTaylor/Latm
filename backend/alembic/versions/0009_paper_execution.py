"""Create atomic paper-entry execution records and open positions.

Revision ID: 0009_paper_execution
Revises: 0008_risk_engine
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009_paper_execution"
down_revision: str | None = "0008_risk_engine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add paper fill accounting, immutable attempts, and open positions."""
    op.add_column(
        "portfolio_snapshots",
        sa.Column("open_position_value", sa.Numeric(precision=18, scale=2), nullable=True),
    )
    op.add_column(
        "portfolio_snapshots",
        sa.Column("unrealized_pnl", sa.Numeric(precision=18, scale=2), nullable=True),
    )
    op.add_column(
        "portfolio_snapshots",
        sa.Column("total_portfolio_value", sa.Numeric(precision=18, scale=2), nullable=True),
    )
    op.add_column(
        "portfolio_snapshots",
        sa.Column("previous_snapshot_id", sa.Uuid(), nullable=True),
    )
    op.execute(
        "UPDATE portfolio_snapshots "
        "SET open_position_value = 0, unrealized_pnl = 0, "
        "total_portfolio_value = cash_balance"
    )
    op.alter_column("portfolio_snapshots", "open_position_value", nullable=False)
    op.alter_column("portfolio_snapshots", "unrealized_pnl", nullable=False)
    op.alter_column("portfolio_snapshots", "total_portfolio_value", nullable=False)
    op.create_foreign_key(
        "portfolio_snapshots_previous_snapshot_id_fkey",
        "portfolio_snapshots",
        "portfolio_snapshots",
        ["previous_snapshot_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint(
        "ck_portfolio_snapshots_reason",
        "portfolio_snapshots",
        type_="check",
    )
    op.drop_constraint(
        "ck_portfolio_snapshots_created_state",
        "portfolio_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        "ck_portfolio_snapshots_open_position_value",
        "portfolio_snapshots",
        "open_position_value = committed_capital + unrealized_pnl",
    )
    op.create_check_constraint(
        "ck_portfolio_snapshots_total_portfolio_value",
        "portfolio_snapshots",
        "total_portfolio_value = cash_balance + open_position_value",
    )
    op.create_check_constraint(
        "ck_portfolio_snapshots_reason",
        "portfolio_snapshots",
        "reason IN ('created', 'paper_entry_filled')",
    )
    op.create_check_constraint(
        "ck_portfolio_snapshots_created_state",
        "portfolio_snapshots",
        "(reason <> 'created') OR (sequence = 0 "
        "AND current_bankroll = starting_bankroll "
        "AND cash_balance = starting_bankroll "
        "AND available_bankroll = starting_bankroll "
        "AND reserved_capital = 0 AND committed_capital = 0 AND realized_pnl = 0 "
        "AND open_position_value = 0 AND unrealized_pnl = 0 "
        "AND total_portfolio_value = starting_bankroll "
        "AND previous_snapshot_id IS NULL)",
    )

    op.create_table(
        "trades",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("risk_decision_id", sa.Uuid(), nullable=False),
        sa.Column("position_size_proposal_id", sa.Uuid(), nullable=False),
        sa.Column("portfolio_id", sa.Uuid(), nullable=False),
        sa.Column("portfolio_snapshot_before_id", sa.Uuid(), nullable=False),
        sa.Column("portfolio_snapshot_after_id", sa.Uuid(), nullable=True),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("market_id", sa.Uuid(), nullable=False),
        sa.Column("outcome_team_id", sa.Uuid(), nullable=False),
        sa.Column("market_event_match_id", sa.Uuid(), nullable=False),
        sa.Column("market_price_id", sa.Uuid(), nullable=False),
        sa.Column("base_forecast_id", sa.Uuid(), nullable=False),
        sa.Column("execution_mode", sa.String(length=10), nullable=False),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason_code", sa.String(length=100), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
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
        sa.Column("reference_price", sa.Numeric(precision=7, scale=6), nullable=False),
        sa.Column("execution_price", sa.Numeric(precision=7, scale=6), nullable=True),
        sa.Column("slippage_bps", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column(
            "slippage_amount_per_contract",
            sa.Numeric(precision=7, scale=6),
            nullable=True,
        ),
        sa.Column("requested_quantity", sa.Integer(), nullable=True),
        sa.Column("executed_quantity", sa.Integer(), nullable=True),
        sa.Column("reference_gross_cost", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("gross_cost", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("slippage_cost", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("fee_bps", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("fee_amount", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("total_cost", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("unused_capital", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("effective_unit_cost", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("model_probability", sa.Numeric(precision=7, scale=6), nullable=False),
        sa.Column("raw_edge", sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column("adjusted_edge", sa.Numeric(precision=8, scale=6), nullable=True),
        sa.Column("mark_price", sa.Numeric(precision=7, scale=6), nullable=True),
        sa.Column("mark_basis", sa.String(length=40), nullable=True),
        sa.Column("market_value", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("unrealized_pnl", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("sizing_strategy_version", sa.String(length=100), nullable=False),
        sa.Column("risk_policy_version", sa.String(length=100), nullable=False),
        sa.Column("execution_policy_name", sa.String(length=50), nullable=False),
        sa.Column("execution_policy_version", sa.String(length=100), nullable=False),
        sa.Column("execution_policy_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("risk_input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "audit_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.CheckConstraint("execution_mode = 'paper'", name="ck_trades_paper_only"),
        sa.CheckConstraint("action = 'buy'", name="ck_trades_entry_only"),
        sa.CheckConstraint("direction IN ('yes', 'no')", name="ck_trades_direction"),
        sa.CheckConstraint("status IN ('filled', 'rejected')", name="ck_trades_status"),
        sa.CheckConstraint(
            "(status = 'filled' AND portfolio_snapshot_after_id IS NOT NULL "
            "AND execution_price IS NOT NULL "
            "AND slippage_amount_per_contract IS NOT NULL "
            "AND requested_quantity >= 1 "
            "AND executed_quantity >= 1 AND gross_cost IS NOT NULL "
            "AND reference_gross_cost IS NOT NULL AND slippage_cost IS NOT NULL "
            "AND fee_amount IS NOT NULL AND total_cost IS NOT NULL "
            "AND unused_capital IS NOT NULL AND effective_unit_cost IS NOT NULL "
            "AND adjusted_edge IS NOT NULL AND mark_price IS NOT NULL "
            "AND mark_basis IS NOT NULL AND market_value IS NOT NULL "
            "AND unrealized_pnl IS NOT NULL AND executed_at IS NOT NULL "
            "AND jsonb_array_length(failed_rules) = 0) OR "
            "(status = 'rejected' AND portfolio_snapshot_after_id IS NULL "
            "AND execution_price IS NULL "
            "AND slippage_amount_per_contract IS NULL "
            "AND requested_quantity IS NULL "
            "AND executed_quantity IS NULL AND gross_cost IS NULL "
            "AND reference_gross_cost IS NULL AND slippage_cost IS NULL "
            "AND fee_amount IS NULL AND total_cost IS NULL "
            "AND unused_capital IS NULL AND effective_unit_cost IS NULL "
            "AND adjusted_edge IS NULL AND mark_price IS NULL "
            "AND mark_basis IS NULL AND market_value IS NULL "
            "AND unrealized_pnl IS NULL AND executed_at IS NULL "
            "AND jsonb_array_length(failed_rules) > 0)",
            name="ck_trades_terminal_state",
        ),
        sa.CheckConstraint(
            "proposed_capital > 0 AND reference_price > 0 AND reference_price < 1 "
            "AND slippage_bps >= 0 AND fee_bps >= 0",
            name="ck_trades_input_values",
        ),
        sa.CheckConstraint(
            "mark_basis IS NULL OR mark_basis IN ('directional_bid', 'directional_ask_fallback')",
            name="ck_trades_mark_basis",
        ),
        sa.CheckConstraint(
            "status = 'rejected' OR (execution_price > 0 AND execution_price < 1 "
            "AND reference_gross_cost >= 0 AND gross_cost >= 0 "
            "AND slippage_cost >= 0 "
            "AND gross_cost = reference_gross_cost + slippage_cost "
            "AND fee_amount >= 0 AND total_cost = gross_cost + fee_amount "
            "AND total_cost <= proposed_capital "
            "AND unused_capital = proposed_capital - total_cost "
            "AND market_value >= 0 "
            "AND unrealized_pnl = market_value - total_cost)",
            name="ck_trades_fill_accounting",
        ),
        sa.CheckConstraint(
            "length(execution_policy_fingerprint) = 64 "
            "AND length(risk_input_fingerprint) = 64 "
            "AND length(input_fingerprint) = 64",
            name="ck_trades_fingerprints",
        ),
        sa.ForeignKeyConstraint(
            ["risk_decision_id"],
            ["risk_decisions.id"],
            name="trades_risk_decision_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["position_size_proposal_id"],
            ["position_size_proposals.id"],
            name="trades_position_size_proposal_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.id"],
            name="trades_portfolio_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_snapshot_before_id"],
            ["portfolio_snapshots.id"],
            name="trades_portfolio_snapshot_before_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_snapshot_after_id"],
            ["portfolio_snapshots.id"],
            name="trades_portfolio_snapshot_after_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities.id"],
            name="trades_opportunity_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["market_id"],
            ["markets.id"],
            name="trades_market_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["outcome_team_id"],
            ["teams.id"],
            name="trades_outcome_team_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["market_event_match_id"],
            ["market_event_matches.id"],
            name="trades_market_event_match_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["market_price_id"],
            ["market_prices.id"],
            name="trades_market_price_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["base_forecast_id"],
            ["base_forecasts.id"],
            name="trades_base_forecast_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("risk_decision_id", name="uq_trades_risk_decision"),
    )
    op.create_index(
        "ix_trades_portfolio_attempted",
        "trades",
        ["portfolio_id", "attempted_at"],
    )
    op.create_index(
        "ix_trades_market_attempted",
        "trades",
        ["market_id", "attempted_at"],
    )
    op.create_index(
        "ix_trades_status_attempted",
        "trades",
        ["status", "attempted_at"],
    )

    op.create_table(
        "positions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opening_trade_id", sa.Uuid(), nullable=False),
        sa.Column("portfolio_id", sa.Uuid(), nullable=False),
        sa.Column("market_id", sa.Uuid(), nullable=False),
        sa.Column("outcome_team_id", sa.Uuid(), nullable=False),
        sa.Column("market_price_id", sa.Uuid(), nullable=False),
        sa.Column("execution_mode", sa.String(length=10), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("average_entry_price", sa.Numeric(precision=7, scale=6), nullable=False),
        sa.Column("gross_cost_basis", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("entry_fees", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("total_cost_basis", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("mark_price", sa.Numeric(precision=7, scale=6), nullable=False),
        sa.Column("mark_basis", sa.String(length=40), nullable=False),
        sa.Column("market_value", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("execution_mode = 'paper'", name="ck_positions_paper_only"),
        sa.CheckConstraint("direction IN ('yes', 'no')", name="ck_positions_direction"),
        sa.CheckConstraint("status = 'open'", name="ck_positions_status"),
        sa.CheckConstraint("quantity >= 1", name="ck_positions_quantity"),
        sa.CheckConstraint(
            "average_entry_price > 0 AND average_entry_price < 1 "
            "AND mark_price >= 0 AND mark_price < 1",
            name="ck_positions_prices",
        ),
        sa.CheckConstraint(
            "mark_basis IN ('directional_bid', 'directional_ask_fallback')",
            name="ck_positions_mark_basis",
        ),
        sa.CheckConstraint(
            "gross_cost_basis >= 0 AND entry_fees >= 0 "
            "AND total_cost_basis = gross_cost_basis + entry_fees "
            "AND market_value >= 0 "
            "AND unrealized_pnl = market_value - total_cost_basis "
            "AND realized_pnl = 0",
            name="ck_positions_accounting",
        ),
        sa.CheckConstraint(
            "length(input_fingerprint) = 64",
            name="ck_positions_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["opening_trade_id"],
            ["trades.id"],
            name="positions_opening_trade_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.id"],
            name="positions_portfolio_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["market_id"],
            ["markets.id"],
            name="positions_market_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["outcome_team_id"],
            ["teams.id"],
            name="positions_outcome_team_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["market_price_id"],
            ["market_prices.id"],
            name="positions_market_price_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("opening_trade_id", name="uq_positions_opening_trade"),
    )
    op.create_index(
        "uq_positions_open_portfolio_market",
        "positions",
        ["portfolio_id", "market_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index(
        "ix_positions_market_opened",
        "positions",
        ["market_id", "opened_at"],
    )


def downgrade() -> None:
    """Remove paper execution data and restore Phase 7 snapshot accounting."""
    op.drop_index("ix_positions_market_opened", table_name="positions")
    op.drop_index("uq_positions_open_portfolio_market", table_name="positions")
    op.drop_table("positions")
    op.drop_index("ix_trades_status_attempted", table_name="trades")
    op.drop_index("ix_trades_market_attempted", table_name="trades")
    op.drop_index("ix_trades_portfolio_attempted", table_name="trades")
    op.drop_table("trades")

    op.execute(
        "DELETE FROM risk_decisions WHERE portfolio_snapshot_id IN "
        "(SELECT id FROM portfolio_snapshots WHERE reason = 'paper_entry_filled') "
        "OR position_size_proposal_id IN "
        "(SELECT id FROM position_size_proposals WHERE portfolio_snapshot_id IN "
        "(SELECT id FROM portfolio_snapshots WHERE reason = 'paper_entry_filled'))"
    )
    op.execute(
        "DELETE FROM position_size_proposals WHERE portfolio_snapshot_id IN "
        "(SELECT id FROM portfolio_snapshots WHERE reason = 'paper_entry_filled')"
    )
    op.execute("DELETE FROM portfolio_snapshots WHERE reason = 'paper_entry_filled'")

    op.drop_constraint(
        "ck_portfolio_snapshots_created_state",
        "portfolio_snapshots",
        type_="check",
    )
    op.drop_constraint(
        "ck_portfolio_snapshots_reason",
        "portfolio_snapshots",
        type_="check",
    )
    op.drop_constraint(
        "ck_portfolio_snapshots_total_portfolio_value",
        "portfolio_snapshots",
        type_="check",
    )
    op.drop_constraint(
        "ck_portfolio_snapshots_open_position_value",
        "portfolio_snapshots",
        type_="check",
    )
    op.drop_constraint(
        "portfolio_snapshots_previous_snapshot_id_fkey",
        "portfolio_snapshots",
        type_="foreignkey",
    )
    op.drop_column("portfolio_snapshots", "previous_snapshot_id")
    op.drop_column("portfolio_snapshots", "total_portfolio_value")
    op.drop_column("portfolio_snapshots", "unrealized_pnl")
    op.drop_column("portfolio_snapshots", "open_position_value")
    op.create_check_constraint(
        "ck_portfolio_snapshots_reason",
        "portfolio_snapshots",
        "reason = 'created'",
    )
    op.create_check_constraint(
        "ck_portfolio_snapshots_created_state",
        "portfolio_snapshots",
        "(reason <> 'created') OR (sequence = 0 "
        "AND current_bankroll = starting_bankroll "
        "AND cash_balance = starting_bankroll "
        "AND available_bankroll = starting_bankroll "
        "AND reserved_capital = 0 AND committed_capital = 0 AND realized_pnl = 0)",
    )
