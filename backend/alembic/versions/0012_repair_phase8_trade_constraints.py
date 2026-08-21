"""Repair finalized Phase 8 paper-trade constraints on early databases.

Revision ID: 0012_phase8_trade_repair
Revises: 0011_evaluation_engine
Create Date: 2026-08-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012_phase8_trade_repair"
down_revision: str | None = "0011_evaluation_engine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TERMINAL_STATE = (
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
    "AND jsonb_array_length(failed_rules) > 0)"
)

_MARK_BASIS = "mark_basis IS NULL OR mark_basis IN ('directional_bid', 'directional_ask_fallback')"

_FILL_ACCOUNTING = (
    "status = 'rejected' OR (execution_price > 0 AND execution_price < 1 "
    "AND reference_gross_cost >= 0 AND gross_cost >= 0 "
    "AND slippage_cost >= 0 "
    "AND gross_cost = reference_gross_cost + slippage_cost "
    "AND fee_amount >= 0 AND total_cost = gross_cost + fee_amount "
    "AND total_cost <= proposed_capital "
    "AND unused_capital = proposed_capital - total_cost "
    "AND market_value >= 0 "
    "AND unrealized_pnl = market_value - total_cost)"
)


def upgrade() -> None:
    """Replace incomplete early checks with the finalized Phase 8 rules."""
    for constraint_name in (
        "ck_trades_terminal_state",
        "ck_trades_mark_basis",
        "ck_trades_fill_accounting",
    ):
        op.drop_constraint(
            constraint_name,
            "trades",
            type_="check",
            if_exists=True,
        )

    op.create_check_constraint(
        "ck_trades_terminal_state",
        "trades",
        _TERMINAL_STATE,
    )
    op.create_check_constraint(
        "ck_trades_mark_basis",
        "trades",
        _MARK_BASIS,
    )
    op.create_check_constraint(
        "ck_trades_fill_accounting",
        "trades",
        _FILL_ACCOUNTING,
    )


def downgrade() -> None:
    """Keep the Phase 8 invariants that revision 0009 already requires."""
