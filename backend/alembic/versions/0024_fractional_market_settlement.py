"""Persist exact official fractional binary settlement without enabling trading.

Revision ID: 0024_fractional_settlement
Revises: 0023_nfl_shadow_evaluations
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024_fractional_settlement"
down_revision: str | None = "0023_nfl_shadow_evaluations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_checks(*, fractional: bool) -> None:
    for name in (
        "ck_market_resolutions_result",
        "ck_market_resolutions_source",
        "ck_market_resolutions_binary_payout",
    ):
        op.drop_constraint(name, "market_resolutions", type_="check")
    op.create_check_constraint(
        "ck_market_resolutions_result",
        "market_resolutions",
        "result IN ('yes', 'no', 'scalar')" if fractional else "result IN ('yes', 'no')",
    )
    op.create_check_constraint(
        "ck_market_resolutions_source",
        "market_resolutions",
        "resolution_type IN ('standard_binary', 'fractional_binary') AND source = 'official_provider'"
        if fractional
        else "resolution_type = 'standard_binary' AND source = 'official_provider'",
    )
    standard = "((result = 'yes' AND yes_payout = 1 AND no_payout = 0) OR (result = 'no' AND yes_payout = 0 AND no_payout = 1))"
    payout_shape = (
        "((resolution_type = 'standard_binary' AND " + standard + ") "
        "OR (resolution_type = 'fractional_binary' AND result = 'scalar' "
        "AND yes_payout > 0 AND yes_payout < 1 AND no_payout > 0 AND no_payout < 1))"
        if fractional
        else standard
    )
    op.create_check_constraint(
        "ck_market_resolutions_binary_payout",
        "market_resolutions",
        "yes_payout >= 0 AND yes_payout <= 1 AND no_payout >= 0 AND no_payout <= 1 "
        "AND yes_payout + no_payout = 1 AND " + payout_shape,
    )


def upgrade() -> None:
    _replace_checks(fractional=True)
    _replace_proceeds_check(floor_to_cents=True)
    op.execute(
        "CREATE FUNCTION reject_market_resolution_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Market resolutions are immutable'; END $$"
    )
    op.execute(
        "CREATE TRIGGER market_resolution_immutable BEFORE UPDATE OR DELETE ON market_resolutions FOR EACH ROW EXECUTE FUNCTION reject_market_resolution_mutation()"
    )


def downgrade() -> None:
    op.execute("LOCK TABLE market_resolutions IN ACCESS EXCLUSIVE MODE")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM market_resolutions WHERE result = 'scalar' OR resolution_type = 'fractional_binary') THEN RAISE EXCEPTION 'Fractional resolution audit data exists; downgrade refused'; END IF; END $$"
    )
    op.execute("DROP TRIGGER market_resolution_immutable ON market_resolutions")
    op.execute("DROP FUNCTION reject_market_resolution_mutation()")
    _replace_checks(fractional=False)
    _replace_proceeds_check(floor_to_cents=False)


def _replace_proceeds_check(*, floor_to_cents: bool) -> None:
    """Match the paper ledger's conservative cent-flooring settlement arithmetic."""
    proceeds = (
        "floor(settlement_payout_per_contract * action_quantity * 100) / 100"
        if floor_to_cents
        else "settlement_payout_per_contract * action_quantity"
    )
    op.drop_constraint("ck_position_events_proceeds", "position_events", type_="check")
    op.create_check_constraint(
        "ck_position_events_proceeds",
        "position_events",
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
        "AND gross_proceeds = " + proceeds + " "
        "AND realized_pnl_increment = net_proceeds - allocated_total_cost_basis)",
    )
