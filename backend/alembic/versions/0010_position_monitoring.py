"""Add official market resolutions and auditable position monitoring.

Revision ID: 0010_position_monitoring
Revises: 0009_paper_execution
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010_position_monitoring"
down_revision: str | None = "0009_paper_execution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PHASE9_SNAPSHOT_REASONS = (
    "paper_position_marked",
    "paper_position_reduced",
    "paper_position_closed",
    "paper_position_settled",
)


def _create_market_resolutions() -> None:
    op.create_table(
        "market_resolutions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("market_id", sa.Uuid(), nullable=False),
        sa.Column("result", sa.String(length=10), nullable=False),
        sa.Column("yes_payout", sa.Numeric(precision=7, scale=6), nullable=False),
        sa.Column("no_payout", sa.Numeric(precision=7, scale=6), nullable=False),
        sa.Column("resolution_type", sa.String(length=30), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "source_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.CheckConstraint(
            "result IN ('yes', 'no')",
            name="ck_market_resolutions_result",
        ),
        sa.CheckConstraint(
            "resolution_type = 'standard_binary' AND source = 'official_provider'",
            name="ck_market_resolutions_source",
        ),
        sa.CheckConstraint(
            "yes_payout >= 0 AND yes_payout <= 1 "
            "AND no_payout >= 0 AND no_payout <= 1 "
            "AND yes_payout + no_payout = 1 "
            "AND ((result = 'yes' AND yes_payout = 1 AND no_payout = 0) "
            "OR (result = 'no' AND yes_payout = 0 AND no_payout = 1))",
            name="ck_market_resolutions_binary_payout",
        ),
        sa.CheckConstraint(
            "settled_at <= retrieved_at",
            name="ck_market_resolutions_times",
        ),
        sa.CheckConstraint(
            "length(input_fingerprint) = 64",
            name="ck_market_resolutions_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["market_id"],
            ["markets.id"],
            name="market_resolutions_market_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "market_id",
            "input_fingerprint",
            name="uq_market_resolutions_semantic_input",
        ),
    )
    op.create_index(
        "ix_market_resolutions_market_settled",
        "market_resolutions",
        ["market_id", "settled_at"],
    )


def _widen_position_projection() -> None:
    additions = (
        sa.Column("initial_quantity", sa.Integer(), nullable=True),
        sa.Column("disposed_quantity", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.Column("original_gross_cost_basis", sa.Numeric(18, 2), nullable=True),
        sa.Column("original_entry_fees", sa.Numeric(18, 2), nullable=True),
        sa.Column("original_total_cost_basis", sa.Numeric(18, 2), nullable=True),
        sa.Column("latest_base_forecast_id", sa.Uuid(), nullable=True),
        sa.Column("market_resolution_id", sa.Uuid(), nullable=True),
        sa.Column("projection_fingerprint", sa.String(64), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in additions:
        op.add_column("positions", column)

    op.execute(
        "UPDATE positions AS p SET "
        "initial_quantity = p.quantity, disposed_quantity = 0, version = 0, "
        "original_gross_cost_basis = p.gross_cost_basis, "
        "original_entry_fees = p.entry_fees, "
        "original_total_cost_basis = p.total_cost_basis, "
        "latest_base_forecast_id = t.base_forecast_id, "
        "projection_fingerprint = p.input_fingerprint "
        "FROM trades AS t WHERE t.id = p.opening_trade_id"
    )
    for column_name in (
        "initial_quantity",
        "disposed_quantity",
        "version",
        "original_gross_cost_basis",
        "original_entry_fees",
        "original_total_cost_basis",
        "projection_fingerprint",
    ):
        op.alter_column("positions", column_name, nullable=False)

    op.create_foreign_key(
        "positions_latest_base_forecast_id_fkey",
        "positions",
        "base_forecasts",
        ["latest_base_forecast_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "positions_market_resolution_id_fkey",
        "positions",
        "market_resolutions",
        ["market_resolution_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    for constraint_name in (
        "ck_positions_status",
        "ck_positions_quantity",
        "ck_positions_prices",
        "ck_positions_mark_basis",
        "ck_positions_accounting",
        "ck_positions_fingerprint",
    ):
        # Older Phase 8 development databases predate the mark-basis check even
        # though they carry the final 0009 revision identifier.
        op.drop_constraint(
            constraint_name,
            "positions",
            type_="check",
            if_exists=True,
        )

    op.create_check_constraint(
        "ck_positions_status",
        "positions",
        "status IN ('open', 'closed', 'settled')",
    )
    op.create_check_constraint(
        "ck_positions_quantity",
        "positions",
        "initial_quantity >= 1 AND quantity >= 0 AND disposed_quantity >= 0 "
        "AND initial_quantity = quantity + disposed_quantity",
    )
    op.create_check_constraint("ck_positions_version", "positions", "version >= 0")
    op.create_check_constraint(
        "ck_positions_prices",
        "positions",
        "average_entry_price > 0 AND average_entry_price < 1 "
        "AND mark_price >= 0 AND mark_price <= 1",
    )
    op.create_check_constraint(
        "ck_positions_mark_basis",
        "positions",
        "mark_basis IN ('directional_bid', 'directional_ask_fallback', "
        "'exit_execution', 'settlement_payout')",
    )
    op.create_check_constraint(
        "ck_positions_accounting",
        "positions",
        "original_gross_cost_basis >= 0 AND original_entry_fees >= 0 "
        "AND original_total_cost_basis = original_gross_cost_basis + original_entry_fees "
        "AND gross_cost_basis >= 0 AND entry_fees >= 0 "
        "AND total_cost_basis = gross_cost_basis + entry_fees "
        "AND gross_cost_basis <= original_gross_cost_basis "
        "AND entry_fees <= original_entry_fees "
        "AND total_cost_basis <= original_total_cost_basis "
        "AND market_value >= 0 "
        "AND unrealized_pnl = market_value - total_cost_basis",
    )
    op.create_check_constraint(
        "ck_positions_lifecycle",
        "positions",
        "(status = 'open' AND quantity >= 1 AND total_cost_basis > 0 "
        "AND closed_at IS NULL AND settled_at IS NULL "
        "AND market_resolution_id IS NULL "
        "AND mark_basis IN ('directional_bid', 'directional_ask_fallback')) OR "
        "(status = 'closed' AND quantity = 0 AND gross_cost_basis = 0 "
        "AND entry_fees = 0 AND total_cost_basis = 0 "
        "AND market_value = 0 AND unrealized_pnl = 0 "
        "AND closed_at IS NOT NULL AND settled_at IS NULL "
        "AND market_resolution_id IS NULL AND mark_basis = 'exit_execution') OR "
        "(status = 'settled' AND quantity = 0 AND gross_cost_basis = 0 "
        "AND entry_fees = 0 AND total_cost_basis = 0 "
        "AND market_value = 0 AND unrealized_pnl = 0 "
        "AND closed_at IS NULL AND settled_at IS NOT NULL "
        "AND market_resolution_id IS NOT NULL "
        "AND mark_basis = 'settlement_payout')",
    )
    op.create_check_constraint(
        "ck_positions_fingerprint",
        "positions",
        "length(input_fingerprint) = 64 AND length(projection_fingerprint) = 64",
    )


def _expand_snapshot_reasons() -> None:
    op.drop_constraint(
        "ck_portfolio_snapshots_reason",
        "portfolio_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        "ck_portfolio_snapshots_reason",
        "portfolio_snapshots",
        "reason IN ('created', 'paper_entry_filled', 'paper_position_marked', "
        "'paper_position_reduced', 'paper_position_closed', 'paper_position_settled')",
    )


def _create_position_events() -> None:
    op.create_table(
        "position_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("position_id", sa.Uuid(), nullable=False),
        sa.Column("opening_trade_id", sa.Uuid(), nullable=False),
        sa.Column("portfolio_id", sa.Uuid(), nullable=False),
        sa.Column("market_id", sa.Uuid(), nullable=False),
        sa.Column("outcome_team_id", sa.Uuid(), nullable=False),
        sa.Column("market_price_id", sa.Uuid(), nullable=True),
        sa.Column("base_forecast_id", sa.Uuid(), nullable=True),
        sa.Column("market_resolution_id", sa.Uuid(), nullable=True),
        sa.Column("portfolio_snapshot_before_id", sa.Uuid(), nullable=False),
        sa.Column("portfolio_snapshot_after_id", sa.Uuid(), nullable=True),
        sa.Column("execution_mode", sa.String(length=10), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("reason_code", sa.String(length=100), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("all_required_checks_passed", sa.Boolean(), nullable=False),
        sa.Column("state_changed", sa.Boolean(), nullable=False),
        sa.Column("failed_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("check_results", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("position_version_before", sa.Integer(), nullable=False),
        sa.Column("position_version_after", sa.Integer(), nullable=False),
        sa.Column("status_before", sa.String(length=20), nullable=False),
        sa.Column("status_after", sa.String(length=20), nullable=False),
        sa.Column("quantity_before", sa.Integer(), nullable=False),
        sa.Column("action_quantity", sa.Integer(), nullable=False),
        sa.Column("quantity_after", sa.Integer(), nullable=False),
        sa.Column("gross_cost_basis_before", sa.Numeric(18, 2), nullable=False),
        sa.Column("entry_fees_before", sa.Numeric(18, 2), nullable=False),
        sa.Column("total_cost_basis_before", sa.Numeric(18, 2), nullable=False),
        sa.Column("allocated_gross_cost_basis", sa.Numeric(18, 2), nullable=False),
        sa.Column("allocated_entry_fees", sa.Numeric(18, 2), nullable=False),
        sa.Column("allocated_total_cost_basis", sa.Numeric(18, 2), nullable=False),
        sa.Column("gross_cost_basis_after", sa.Numeric(18, 2), nullable=False),
        sa.Column("entry_fees_after", sa.Numeric(18, 2), nullable=False),
        sa.Column("total_cost_basis_after", sa.Numeric(18, 2), nullable=False),
        sa.Column("reference_price", sa.Numeric(7, 6), nullable=True),
        sa.Column("exit_price", sa.Numeric(7, 6), nullable=True),
        sa.Column("exit_slippage_bps", sa.Numeric(10, 2), nullable=True),
        sa.Column(
            "exit_slippage_amount_per_contract",
            sa.Numeric(7, 6),
            nullable=True,
        ),
        sa.Column("reference_gross_proceeds", sa.Numeric(18, 2), nullable=True),
        sa.Column("slippage_cost", sa.Numeric(18, 2), nullable=True),
        sa.Column("gross_proceeds", sa.Numeric(18, 2), nullable=True),
        sa.Column("exit_fee_bps", sa.Numeric(10, 2), nullable=True),
        sa.Column("exit_fee_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("net_proceeds", sa.Numeric(18, 2), nullable=True),
        sa.Column("settlement_payout_per_contract", sa.Numeric(7, 6), nullable=True),
        sa.Column("model_probability", sa.Numeric(7, 6), nullable=True),
        sa.Column("hold_edge", sa.Numeric(8, 6), nullable=True),
        sa.Column("after_mark_price", sa.Numeric(7, 6), nullable=False),
        sa.Column("after_mark_basis", sa.String(length=40), nullable=False),
        sa.Column("after_market_value", sa.Numeric(18, 2), nullable=False),
        sa.Column("after_unrealized_pnl", sa.Numeric(18, 2), nullable=False),
        sa.Column("realized_pnl_before", sa.Numeric(18, 2), nullable=False),
        sa.Column("realized_pnl_increment", sa.Numeric(18, 2), nullable=False),
        sa.Column("realized_pnl_cumulative", sa.Numeric(18, 2), nullable=False),
        sa.Column("policy_name", sa.String(length=50), nullable=False),
        sa.Column("policy_version", sa.String(length=100), nullable=False),
        sa.Column("policy_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "position_projection_fingerprint_before",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "position_projection_fingerprint_after",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("audit_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "execution_mode = 'paper'",
            name="ck_position_events_paper_only",
        ),
        sa.CheckConstraint(
            "decision IN ('hold', 'reduce', 'close', 'settle')",
            name="ck_position_events_decision",
        ),
        sa.CheckConstraint(
            "status_before = 'open' AND status_after IN ('open', 'closed', 'settled')",
            name="ck_position_events_statuses",
        ),
        sa.CheckConstraint(
            "position_version_before >= 0 AND "
            "((state_changed = true "
            "AND position_version_after = position_version_before + 1) OR "
            "(state_changed = false "
            "AND position_version_after = position_version_before "
            "AND position_projection_fingerprint_after "
            "= position_projection_fingerprint_before))",
            name="ck_position_events_versions",
        ),
        sa.CheckConstraint(
            "quantity_before >= 1 AND action_quantity >= 0 "
            "AND action_quantity <= quantity_before "
            "AND quantity_after = quantity_before - action_quantity",
            name="ck_position_events_quantities",
        ),
        sa.CheckConstraint(
            "gross_cost_basis_before >= 0 AND entry_fees_before >= 0 "
            "AND total_cost_basis_before = gross_cost_basis_before + entry_fees_before "
            "AND allocated_gross_cost_basis >= 0 AND allocated_entry_fees >= 0 "
            "AND allocated_total_cost_basis = allocated_gross_cost_basis "
            "+ allocated_entry_fees "
            "AND gross_cost_basis_after >= 0 AND entry_fees_after >= 0 "
            "AND total_cost_basis_after = gross_cost_basis_after + entry_fees_after "
            "AND gross_cost_basis_before = allocated_gross_cost_basis "
            "+ gross_cost_basis_after "
            "AND entry_fees_before = allocated_entry_fees + entry_fees_after "
            "AND total_cost_basis_before = allocated_total_cost_basis "
            "+ total_cost_basis_after",
            name="ck_position_events_cost_basis",
        ),
        sa.CheckConstraint(
            "realized_pnl_cumulative = realized_pnl_before + realized_pnl_increment",
            name="ck_position_events_realized_pnl",
        ),
        sa.CheckConstraint(
            "after_mark_price >= 0 AND after_mark_price <= 1 "
            "AND after_mark_basis IN ('directional_bid', 'directional_ask_fallback', "
            "'exit_execution', 'settlement_payout') AND after_market_value >= 0 "
            "AND after_unrealized_pnl = after_market_value - total_cost_basis_after",
            name="ck_position_events_after_mark",
        ),
        sa.CheckConstraint(
            "(state_changed = true AND portfolio_snapshot_after_id IS NOT NULL) OR "
            "(state_changed = false AND portfolio_snapshot_after_id IS NULL)",
            name="ck_position_events_snapshot_effect",
        ),
        sa.CheckConstraint(
            "jsonb_array_length(check_results) > 0 AND "
            "((all_required_checks_passed = true "
            "AND jsonb_array_length(failed_rules) = 0) OR "
            "(all_required_checks_passed = false "
            "AND jsonb_array_length(failed_rules) > 0))",
            name="ck_position_events_check_results",
        ),
        sa.CheckConstraint(
            "(reference_price IS NULL OR (reference_price >= 0 AND reference_price <= 1)) "
            "AND (exit_price IS NULL OR (exit_price >= 0 AND exit_price < 1)) "
            "AND (model_probability IS NULL OR "
            "(model_probability >= 0 AND model_probability <= 1)) "
            "AND (hold_edge IS NULL OR (hold_edge >= -1 AND hold_edge <= 1)) "
            "AND (exit_slippage_bps IS NULL OR exit_slippage_bps >= 0) "
            "AND (exit_slippage_amount_per_contract IS NULL "
            "OR exit_slippage_amount_per_contract >= 0) "
            "AND (exit_fee_bps IS NULL OR exit_fee_bps >= 0)",
            name="ck_position_events_market_values",
        ),
        sa.CheckConstraint(
            "(decision = 'hold' AND action_quantity = 0 "
            "AND quantity_after = quantity_before AND status_after = 'open' "
            "AND after_mark_basis IN ('directional_bid', 'directional_ask_fallback') "
            "AND allocated_total_cost_basis = 0 AND reference_price IS NULL "
            "AND exit_price IS NULL AND exit_slippage_bps IS NULL "
            "AND exit_slippage_amount_per_contract IS NULL "
            "AND reference_gross_proceeds IS NULL AND slippage_cost IS NULL "
            "AND gross_proceeds IS NULL AND exit_fee_bps IS NULL "
            "AND exit_fee_amount IS NULL "
            "AND net_proceeds IS NULL AND settlement_payout_per_contract IS NULL "
            "AND realized_pnl_increment = 0) OR "
            "(decision = 'reduce' AND action_quantity > 0 "
            "AND action_quantity < quantity_before AND status_after = 'open' "
            "AND after_mark_basis IN ('directional_bid', 'directional_ask_fallback') "
            "AND reference_price IS NOT NULL AND exit_price IS NOT NULL "
            "AND exit_slippage_bps IS NOT NULL "
            "AND exit_slippage_amount_per_contract IS NOT NULL "
            "AND reference_gross_proceeds IS NOT NULL "
            "AND slippage_cost IS NOT NULL AND gross_proceeds IS NOT NULL "
            "AND exit_fee_bps IS NOT NULL "
            "AND exit_fee_amount IS NOT NULL AND net_proceeds IS NOT NULL "
            "AND settlement_payout_per_contract IS NULL "
            "AND market_resolution_id IS NULL) OR "
            "(decision = 'close' AND action_quantity = quantity_before "
            "AND quantity_after = 0 AND status_after = 'closed' "
            "AND after_mark_basis = 'exit_execution' "
            "AND reference_price IS NOT NULL AND exit_price IS NOT NULL "
            "AND exit_slippage_bps IS NOT NULL "
            "AND exit_slippage_amount_per_contract IS NOT NULL "
            "AND reference_gross_proceeds IS NOT NULL "
            "AND slippage_cost IS NOT NULL AND gross_proceeds IS NOT NULL "
            "AND exit_fee_bps IS NOT NULL "
            "AND exit_fee_amount IS NOT NULL AND net_proceeds IS NOT NULL "
            "AND settlement_payout_per_contract IS NULL "
            "AND market_resolution_id IS NULL) OR "
            "(decision = 'settle' AND action_quantity = quantity_before "
            "AND quantity_after = 0 AND status_after = 'settled' "
            "AND after_mark_basis = 'settlement_payout' "
            "AND exit_price IS NULL AND exit_slippage_bps IS NULL "
            "AND exit_slippage_amount_per_contract IS NULL "
            "AND reference_gross_proceeds IS NULL AND slippage_cost IS NULL "
            "AND exit_fee_bps IS NULL AND exit_fee_amount IS NULL "
            "AND settlement_payout_per_contract IS NOT NULL "
            "AND reference_price = settlement_payout_per_contract "
            "AND gross_proceeds IS NOT NULL AND net_proceeds = gross_proceeds "
            "AND market_resolution_id IS NOT NULL)",
            name="ck_position_events_decision_shape",
        ),
        sa.CheckConstraint(
            "(decision = 'hold') OR "
            "(decision IN ('reduce', 'close') "
            "AND reference_gross_proceeds >= 0 AND slippage_cost >= 0 "
            "AND exit_slippage_amount_per_contract = reference_price - exit_price "
            "AND reference_gross_proceeds = gross_proceeds + slippage_cost "
            "AND gross_proceeds >= 0 AND exit_fee_amount >= 0 "
            "AND net_proceeds = gross_proceeds - exit_fee_amount "
            "AND realized_pnl_increment = net_proceeds - allocated_total_cost_basis) OR "
            "(decision = 'settle' AND settlement_payout_per_contract >= 0 "
            "AND settlement_payout_per_contract <= 1 "
            "AND gross_proceeds = settlement_payout_per_contract * action_quantity "
            "AND realized_pnl_increment = net_proceeds - allocated_total_cost_basis)",
            name="ck_position_events_proceeds",
        ),
        sa.CheckConstraint(
            "(decision IN ('hold', 'reduce') AND quantity_after >= 1 "
            "AND total_cost_basis_after > 0) OR "
            "(decision IN ('close', 'settle') AND quantity_after = 0 "
            "AND gross_cost_basis_after = 0 AND entry_fees_after = 0 "
            "AND total_cost_basis_after = 0 AND after_market_value = 0 "
            "AND after_unrealized_pnl = 0)",
            name="ck_position_events_terminal_state",
        ),
        sa.CheckConstraint(
            "length(policy_fingerprint) = 64 AND length(input_fingerprint) = 64 "
            "AND length(position_projection_fingerprint_before) = 64 "
            "AND length(position_projection_fingerprint_after) = 64",
            name="ck_position_events_fingerprints",
        ),
        sa.CheckConstraint(
            "evaluated_at <= recorded_at "
            "AND (executed_at IS NULL OR evaluated_at <= executed_at) "
            "AND ((decision = 'hold' AND executed_at IS NULL) "
            "OR (decision <> 'hold' AND executed_at IS NOT NULL))",
            name="ck_position_events_times",
        ),
        sa.ForeignKeyConstraint(
            ["position_id"],
            ["positions.id"],
            name="position_events_position_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["opening_trade_id"],
            ["trades.id"],
            name="position_events_opening_trade_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_id"],
            ["portfolios.id"],
            name="position_events_portfolio_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["market_id"],
            ["markets.id"],
            name="position_events_market_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["outcome_team_id"],
            ["teams.id"],
            name="position_events_outcome_team_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["market_price_id"],
            ["market_prices.id"],
            name="position_events_market_price_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["base_forecast_id"],
            ["base_forecasts.id"],
            name="position_events_base_forecast_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["market_resolution_id"],
            ["market_resolutions.id"],
            name="position_events_market_resolution_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_snapshot_before_id"],
            ["portfolio_snapshots.id"],
            name="position_events_portfolio_snapshot_before_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["portfolio_snapshot_after_id"],
            ["portfolio_snapshots.id"],
            name="position_events_portfolio_snapshot_after_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "position_id",
            "policy_version",
            "input_fingerprint",
            name="uq_position_events_semantic_input",
        ),
    )
    op.create_index(
        "ix_position_events_position_evaluated",
        "position_events",
        ["position_id", "evaluated_at"],
    )
    op.create_index(
        "ix_position_events_portfolio_evaluated",
        "position_events",
        ["portfolio_id", "evaluated_at"],
    )
    op.create_index(
        "ix_position_events_market_evaluated",
        "position_events",
        ["market_id", "evaluated_at"],
    )
    op.create_index(
        "ix_position_events_decision_evaluated",
        "position_events",
        ["decision", "evaluated_at"],
    )


def upgrade() -> None:
    """Add the Phase 9 resolution, projection, event, and snapshot schema."""
    _create_market_resolutions()
    _widen_position_projection()
    _expand_snapshot_reasons()
    _create_position_events()


def _delete_phase9_and_descendant_state() -> None:
    """Remove states at or after a Phase 9 snapshot before restoring Phase 8."""
    cutoff = (
        "WITH cutoffs AS ("
        "SELECT portfolio_id, min(sequence) AS first_sequence "
        "FROM portfolio_snapshots WHERE reason IN ("
        "'paper_position_marked', 'paper_position_reduced', "
        "'paper_position_closed', 'paper_position_settled') "
        "GROUP BY portfolio_id) "
    )
    op.execute(
        cutoff
        + "DELETE FROM positions AS p USING trades AS t, "
        "portfolio_snapshots AS s, cutoffs AS c "
        "WHERE p.opening_trade_id = t.id "
        "AND t.portfolio_snapshot_after_id = s.id "
        "AND s.portfolio_id = c.portfolio_id AND s.sequence >= c.first_sequence"
    )
    op.execute(
        cutoff
        + "DELETE FROM trades AS t USING portfolio_snapshots AS s, cutoffs AS c "
        "WHERE (t.portfolio_snapshot_before_id = s.id "
        "OR t.portfolio_snapshot_after_id = s.id) "
        "AND s.portfolio_id = c.portfolio_id AND s.sequence >= c.first_sequence"
    )
    op.execute(
        cutoff
        + "DELETE FROM risk_decisions AS r USING portfolio_snapshots AS s, cutoffs AS c "
        "WHERE r.portfolio_snapshot_id = s.id "
        "AND s.portfolio_id = c.portfolio_id AND s.sequence >= c.first_sequence"
    )
    op.execute(
        cutoff
        + "DELETE FROM position_size_proposals AS p "
        "USING portfolio_snapshots AS s, cutoffs AS c "
        "WHERE p.portfolio_snapshot_id = s.id "
        "AND s.portfolio_id = c.portfolio_id AND s.sequence >= c.first_sequence"
    )
    op.execute(
        cutoff
        + "DELETE FROM portfolio_snapshots AS s USING cutoffs AS c "
        "WHERE s.portfolio_id = c.portfolio_id AND s.sequence >= c.first_sequence"
    )


def _restore_phase8_positions() -> None:
    op.execute(
        "UPDATE positions AS p SET status = 'open', initial_quantity = t.executed_quantity, "
        "quantity = t.executed_quantity, disposed_quantity = 0, version = 0, "
        "original_gross_cost_basis = t.gross_cost, original_entry_fees = t.fee_amount, "
        "original_total_cost_basis = t.total_cost, gross_cost_basis = t.gross_cost, "
        "entry_fees = t.fee_amount, total_cost_basis = t.total_cost, "
        "mark_price = t.mark_price, mark_basis = t.mark_basis, "
        "market_value = t.market_value, unrealized_pnl = t.unrealized_pnl, "
        "realized_pnl = 0, latest_base_forecast_id = t.base_forecast_id, "
        "market_resolution_id = NULL, projection_fingerprint = p.input_fingerprint, "
        "updated_at = p.opened_at, closed_at = NULL, settled_at = NULL "
        "FROM trades AS t WHERE t.id = p.opening_trade_id"
    )


def downgrade() -> None:
    """Remove monitoring state and restore the exact Phase 8 projection."""
    for index_name in (
        "ix_position_events_decision_evaluated",
        "ix_position_events_market_evaluated",
        "ix_position_events_portfolio_evaluated",
        "ix_position_events_position_evaluated",
    ):
        op.drop_index(index_name, table_name="position_events")
    op.drop_table("position_events")

    _delete_phase9_and_descendant_state()
    _restore_phase8_positions()

    op.drop_constraint("ck_positions_lifecycle", "positions", type_="check")
    op.drop_constraint("ck_positions_version", "positions", type_="check")
    for constraint_name in (
        "ck_positions_status",
        "ck_positions_quantity",
        "ck_positions_prices",
        "ck_positions_mark_basis",
        "ck_positions_accounting",
        "ck_positions_fingerprint",
    ):
        op.drop_constraint(constraint_name, "positions", type_="check")

    op.drop_constraint(
        "positions_market_resolution_id_fkey",
        "positions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "positions_latest_base_forecast_id_fkey",
        "positions",
        type_="foreignkey",
    )
    for column_name in (
        "settled_at",
        "closed_at",
        "projection_fingerprint",
        "market_resolution_id",
        "latest_base_forecast_id",
        "original_total_cost_basis",
        "original_entry_fees",
        "original_gross_cost_basis",
        "version",
        "disposed_quantity",
        "initial_quantity",
    ):
        op.drop_column("positions", column_name)

    op.create_check_constraint("ck_positions_status", "positions", "status = 'open'")
    op.create_check_constraint("ck_positions_quantity", "positions", "quantity >= 1")
    op.create_check_constraint(
        "ck_positions_prices",
        "positions",
        "average_entry_price > 0 AND average_entry_price < 1 "
        "AND mark_price >= 0 AND mark_price < 1",
    )
    op.create_check_constraint(
        "ck_positions_mark_basis",
        "positions",
        "mark_basis IN ('directional_bid', 'directional_ask_fallback')",
    )
    op.create_check_constraint(
        "ck_positions_accounting",
        "positions",
        "gross_cost_basis >= 0 AND entry_fees >= 0 "
        "AND total_cost_basis = gross_cost_basis + entry_fees "
        "AND market_value >= 0 "
        "AND unrealized_pnl = market_value - total_cost_basis "
        "AND realized_pnl = 0",
    )
    op.create_check_constraint(
        "ck_positions_fingerprint",
        "positions",
        "length(input_fingerprint) = 64",
    )

    op.drop_constraint(
        "ck_portfolio_snapshots_reason",
        "portfolio_snapshots",
        type_="check",
    )
    op.create_check_constraint(
        "ck_portfolio_snapshots_reason",
        "portfolio_snapshots",
        "reason IN ('created', 'paper_entry_filled')",
    )

    op.drop_index("ix_market_resolutions_market_settled", table_name="market_resolutions")
    op.drop_table("market_resolutions")
