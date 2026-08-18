from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from pydantic import JsonValue, ValidationError

from app.domain.position_monitoring import (
    MonitoredPositionStatus,
    PositionAccountingState,
    PositionMonitoringAction,
    PositionMonitoringInput,
    PositionMonitoringPolicy,
    cumulative_basis_allocation,
)
from app.services.position_monitoring.engine import (
    DeterministicPositionMonitoringEngine,
    effective_position_monitoring_policy_version,
    position_monitoring_policy_fingerprint,
)

NOW = datetime(2026, 8, 18, 16, 0, tzinfo=UTC)


def accounting_state(
    *,
    initial_quantity: int = 10,
    disposed_quantity: int = 0,
    remaining_quantity: int = 10,
    original_gross: Decimal = Decimal("4.00"),
    original_fees: Decimal = Decimal("0.10"),
    remaining_gross: Decimal = Decimal("4.00"),
    remaining_fees: Decimal = Decimal("0.10"),
    mark_price: Decimal = Decimal("0.400000"),
    market_value: Decimal = Decimal("4.00"),
    unrealized_pnl: Decimal = Decimal("-0.10"),
    realized_pnl: Decimal = Decimal("0.00"),
) -> PositionAccountingState:
    return PositionAccountingState(
        status=MonitoredPositionStatus.OPEN,
        initial_quantity=initial_quantity,
        disposed_quantity=disposed_quantity,
        remaining_quantity=remaining_quantity,
        original_gross_cost_basis=original_gross,
        original_entry_fees=original_fees,
        original_total_cost_basis=original_gross + original_fees,
        remaining_gross_cost_basis=remaining_gross,
        remaining_entry_fees=remaining_fees,
        remaining_total_cost_basis=remaining_gross + remaining_fees,
        mark_price=mark_price,
        mark_basis="entry_execution",
        market_value=market_value,
        unrealized_pnl=unrealized_pnl,
        realized_pnl=realized_pnl,
    )


def monitoring_input(**updates: object) -> PositionMonitoringInput:
    source = PositionMonitoringInput(
        position_id=UUID(int=1),
        portfolio_id=UUID(int=2),
        portfolio_snapshot_id=UUID(int=3),
        market_id=UUID(int=4),
        outcome_team_id=UUID(int=5),
        direction="yes",
        runtime_trading_mode="paper",
        position_execution_mode="paper",
        position=accounting_state(),
        market_event_match_id=UUID(int=9),
        market_status="active",
        event_status="scheduled",
        event_postponed=False,
        event_start_time=NOW + timedelta(hours=2),
        event_semantics_are_current=True,
        market_price_id=UUID(int=6),
        market_price_is_current=True,
        market_price_retrieved_at=NOW - timedelta(seconds=30),
        yes_bid=Decimal("0.550000"),
        no_bid=Decimal("0.440000"),
        forecast_id=UUID(int=7),
        forecast_is_current=True,
        forecast_generated_at=NOW - timedelta(minutes=5),
        model_probability=Decimal("0.600000"),
        evaluated_at=NOW,
    )
    return source.model_copy(update=updates)


def engine(
    policy: PositionMonitoringPolicy | None = None,
) -> DeterministicPositionMonitoringEngine:
    return DeterministicPositionMonitoringEngine(policy or PositionMonitoringPolicy())


def test_hold_at_exact_threshold_updates_bid_mark_and_snapshot_delta() -> None:
    decision = engine().evaluate(monitoring_input(model_probability=Decimal("0.580000")))

    assert decision.action is PositionMonitoringAction.HOLD
    assert decision.reason_code == "minimum_hold_edge_met"
    assert decision.hold_edge == Decimal("0.030000")
    assert decision.economics is None
    assert decision.after.remaining_quantity == 10
    assert decision.after.mark_price == Decimal("0.550000")
    assert decision.after.mark_basis == "directional_bid"
    assert decision.after.market_value == Decimal("5.50")
    assert decision.after.unrealized_pnl == Decimal("1.40")
    assert decision.portfolio_delta.current_bankroll == Decimal("0.00")
    assert decision.portfolio_delta.cash_balance == Decimal("0.00")
    assert decision.portfolio_delta.committed_capital == Decimal("0.00")
    assert decision.portfolio_delta.unrealized_pnl == Decimal("1.50")
    assert decision.portfolio_delta.open_position_value == Decimal("1.50")
    assert decision.portfolio_delta.total_portfolio_value == Decimal("1.50")


def test_nonpositive_edge_closes_with_exact_rounded_exit_accounting() -> None:
    decision = engine().evaluate(monitoring_input(model_probability=Decimal("0.550000")))

    assert decision.action is PositionMonitoringAction.CLOSE
    assert decision.reason_code == "hold_edge_nonpositive"
    assert decision.after.status is MonitoredPositionStatus.CLOSED
    assert decision.after.remaining_quantity == 0
    assert decision.after.mark_price == Decimal("0.547500")
    assert decision.after.mark_basis == "exit_execution"
    assert decision.after.realized_pnl == Decimal("1.36")
    assert decision.economics is not None
    assert decision.economics.reference_price == Decimal("0.550000")
    assert decision.economics.execution_price == Decimal("0.547500")
    assert decision.economics.reference_gross_proceeds == Decimal("5.50")
    assert decision.economics.gross_proceeds == Decimal("5.47")
    assert decision.economics.slippage_cost == Decimal("0.03")
    assert decision.economics.exit_fee == Decimal("0.01")
    assert decision.economics.net_proceeds == Decimal("5.46")
    assert decision.economics.allocated_total_cost_basis == Decimal("4.10")
    assert decision.economics.realized_pnl_increment == Decimal("1.36")
    assert decision.portfolio_delta.current_bankroll == Decimal("1.36")
    assert decision.portfolio_delta.cash_balance == Decimal("5.46")
    assert decision.portfolio_delta.committed_capital == Decimal("-4.10")
    assert decision.portfolio_delta.unrealized_pnl == Decimal("0.10")
    assert decision.portfolio_delta.open_position_value == Decimal("-4.00")
    assert decision.portfolio_delta.total_portfolio_value == Decimal("1.46")


def test_forecast_at_half_closes_when_positive_edge_is_below_threshold() -> None:
    decision = engine().evaluate(
        monitoring_input(yes_bid=Decimal("0.490000"), model_probability=Decimal("0.500000"))
    )

    assert decision.action is PositionMonitoringAction.CLOSE
    assert decision.reason_code == "forecast_reversed_below_hold_threshold"
    assert decision.hold_edge == Decimal("0.010000")


def test_positive_subthreshold_edge_reduces_by_ceiling_fraction() -> None:
    state = accounting_state(
        initial_quantity=5,
        remaining_quantity=5,
        original_gross=Decimal("1.00"),
        original_fees=Decimal("0.02"),
        remaining_gross=Decimal("1.00"),
        remaining_fees=Decimal("0.02"),
        market_value=Decimal("2.00"),
        unrealized_pnl=Decimal("0.98"),
    )

    decision = engine().evaluate(
        monitoring_input(position=state, model_probability=Decimal("0.560000"))
    )

    assert decision.action is PositionMonitoringAction.REDUCE
    assert decision.economics is not None
    assert decision.economics.disposed_quantity == 3
    assert decision.economics.reference_gross_proceeds == Decimal("1.65")
    assert decision.economics.gross_proceeds == Decimal("1.64")
    assert decision.economics.slippage_cost == Decimal("0.01")
    assert decision.economics.exit_fee == Decimal("0.01")
    assert decision.economics.net_proceeds == Decimal("1.63")
    assert decision.economics.allocated_gross_cost_basis == Decimal("0.60")
    assert decision.economics.allocated_entry_fees == Decimal("0.01")
    assert decision.economics.realized_pnl_increment == Decimal("1.02")
    assert decision.after.status is MonitoredPositionStatus.OPEN
    assert decision.after.disposed_quantity == 3
    assert decision.after.remaining_quantity == 2
    assert decision.after.remaining_gross_cost_basis == Decimal("0.40")
    assert decision.after.remaining_entry_fees == Decimal("0.01")
    assert decision.after.remaining_total_cost_basis == Decimal("0.41")
    assert decision.after.market_value == Decimal("1.10")
    assert decision.after.unrealized_pnl == Decimal("0.69")
    assert decision.after.realized_pnl == Decimal("1.02")


def test_repeated_reductions_use_cumulative_original_basis_allocation() -> None:
    state = accounting_state(
        initial_quantity=5,
        disposed_quantity=3,
        remaining_quantity=2,
        original_gross=Decimal("1.00"),
        original_fees=Decimal("0.02"),
        remaining_gross=Decimal("0.40"),
        remaining_fees=Decimal("0.01"),
        mark_price=Decimal("0.550000"),
        market_value=Decimal("1.10"),
        unrealized_pnl=Decimal("0.69"),
        realized_pnl=Decimal("1.02"),
    )

    decision = engine().evaluate(
        monitoring_input(position=state, model_probability=Decimal("0.560000"))
    )

    assert decision.action is PositionMonitoringAction.REDUCE
    assert decision.economics is not None
    assert decision.economics.disposed_quantity == 1
    assert decision.economics.allocated_gross_cost_basis == Decimal("0.20")
    assert decision.economics.allocated_entry_fees == Decimal("0.00")
    assert decision.economics.allocated_total_cost_basis == Decimal("0.20")
    assert decision.after.disposed_quantity == 4
    assert decision.after.remaining_quantity == 1
    assert decision.after.remaining_gross_cost_basis == Decimal("0.20")
    assert decision.after.remaining_entry_fees == Decimal("0.01")
    assert decision.after.remaining_total_cost_basis == Decimal("0.21")


def test_single_contract_reduction_is_promoted_to_close() -> None:
    state = accounting_state(
        initial_quantity=1,
        remaining_quantity=1,
        original_gross=Decimal("0.40"),
        original_fees=Decimal("0.01"),
        remaining_gross=Decimal("0.40"),
        remaining_fees=Decimal("0.01"),
        market_value=Decimal("0.40"),
        unrealized_pnl=Decimal("-0.01"),
    )

    decision = engine().evaluate(
        monitoring_input(position=state, model_probability=Decimal("0.560000"))
    )

    assert decision.action is PositionMonitoringAction.CLOSE
    assert decision.reason_code == "single_contract_cannot_reduce"
    assert decision.economics is not None
    assert decision.economics.disposed_quantity == 1


def test_no_position_uses_direct_no_bid_for_edge_and_exit() -> None:
    decision = engine().evaluate(
        monitoring_input(
            direction="no",
            yes_bid=Decimal("0.100000"),
            no_bid=Decimal("0.600000"),
            model_probability=Decimal("0.600000"),
        )
    )

    assert decision.action is PositionMonitoringAction.CLOSE
    assert decision.economics is not None
    assert decision.economics.reference_price == Decimal("0.600000")
    assert decision.economics.execution_price == Decimal("0.597500")


def test_final_resolution_settles_before_freshness_and_market_gates() -> None:
    decision = engine().evaluate(
        monitoring_input(
            market_status="closed",
            event_status="final",
            event_start_time=NOW - timedelta(hours=4),
            event_semantics_are_current=False,
            market_price_id=None,
            market_price_is_current=False,
            market_price_retrieved_at=None,
            yes_bid=None,
            forecast_id=None,
            forecast_is_current=False,
            forecast_generated_at=None,
            model_probability=None,
            official_resolution_id=UUID(int=8),
            official_resolution_is_final=True,
            official_held_side_payout=Decimal("1.000000"),
        )
    )

    assert decision.action is PositionMonitoringAction.SETTLE
    assert decision.after.status is MonitoredPositionStatus.SETTLED
    assert decision.after.mark_price == Decimal("1.000000")
    assert decision.after.mark_basis == "settlement_payout"
    assert decision.after.realized_pnl == Decimal("5.90")
    assert decision.economics is not None
    assert decision.economics.gross_proceeds == Decimal("10.00")
    assert decision.economics.slippage_cost == Decimal("0.00")
    assert decision.economics.exit_fee == Decimal("0.00")
    assert decision.economics.net_proceeds == Decimal("10.00")
    assert decision.portfolio_delta.current_bankroll == Decimal("5.90")
    assert decision.portfolio_delta.cash_balance == Decimal("10.00")
    assert decision.portfolio_delta.total_portfolio_value == Decimal("6.00")


def test_zero_payout_settlement_realizes_the_entire_remaining_basis_loss() -> None:
    decision = engine().evaluate(
        monitoring_input(
            market_status="closed",
            official_resolution_id=UUID(int=8),
            official_resolution_is_final=True,
            official_held_side_payout=Decimal("0.000000"),
        )
    )

    assert decision.action is PositionMonitoringAction.SETTLE
    assert decision.economics is not None
    assert decision.economics.net_proceeds == Decimal("0.00")
    assert decision.economics.realized_pnl_increment == Decimal("-4.10")
    assert decision.after.realized_pnl == Decimal("-4.10")
    assert decision.portfolio_delta.total_portfolio_value == Decimal("-4.00")


def test_final_resolution_without_explicit_payout_holds() -> None:
    decision = engine().evaluate(
        monitoring_input(
            market_status="closed",
            official_resolution_id=UUID(int=8),
            official_resolution_is_final=True,
            official_held_side_payout=None,
        )
    )

    assert decision.action is PositionMonitoringAction.HOLD
    assert decision.reason_code == "official_resolution_payout_unavailable"
    assert decision.after == decision.before


@pytest.mark.parametrize(
    ("updates", "reason_code"),
    [
        ({"event_semantics_are_current": False}, "event_semantics_invalid"),
        ({"market_price_is_current": False}, "market_price_not_current"),
        (
            {"market_price_retrieved_at": NOW - timedelta(seconds=901)},
            "market_price_stale",
        ),
        ({"market_price_retrieved_at": NOW + timedelta(seconds=1)}, "market_price_stale"),
        ({"yes_bid": None}, "directional_bid_unavailable"),
        ({"forecast_is_current": False}, "forecast_not_current"),
        ({"forecast_generated_at": NOW - timedelta(seconds=86401)}, "forecast_stale"),
        ({"forecast_generated_at": NOW + timedelta(seconds=1)}, "forecast_stale"),
        ({"event_start_time": NOW}, "event_not_pregame"),
        ({"event_postponed": True}, "event_not_pregame"),
        ({"market_status": "closed"}, "market_closed_unresolved"),
    ],
)
def test_invalid_or_unsafe_monitoring_inputs_hold_without_remarking(
    updates: dict[str, object], reason_code: str
) -> None:
    decision = engine().evaluate(monitoring_input(**updates))

    assert decision.action is PositionMonitoringAction.HOLD
    assert decision.reason_code == reason_code
    assert decision.after == decision.before
    assert decision.economics is None
    assert all(value == 0 for value in decision.portfolio_delta.model_dump().values())


def test_monitoring_is_paper_only() -> None:
    decision = engine().evaluate(monitoring_input(runtime_trading_mode="live"))

    assert decision.action is PositionMonitoringAction.HOLD
    assert decision.reason_code == "paper_only"
    assert decision.after == decision.before


def test_fingerprint_is_stable_across_retry_and_projection_mutation() -> None:
    source = monitoring_input(model_probability=Decimal("0.560000"))
    first = engine().evaluate(source)
    assert first.action is PositionMonitoringAction.REDUCE

    later_same_source = source.model_copy(update={"evaluated_at": NOW + timedelta(seconds=1)})
    changed_projection = later_same_source.model_copy(update={"position": first.after})
    retried = engine().evaluate(changed_projection)

    assert retried.action is PositionMonitoringAction.REDUCE
    assert retried.before.remaining_quantity != first.before.remaining_quantity
    assert retried.input_fingerprint == first.input_fingerprint


def test_fingerprint_changes_when_same_source_crosses_freshness_boundary() -> None:
    source = monitoring_input(model_probability=Decimal("0.560000"))
    fresh = engine().evaluate(source)
    stale = engine().evaluate(
        source.model_copy(update={"evaluated_at": NOW + timedelta(seconds=901)})
    )

    assert fresh.action is PositionMonitoringAction.REDUCE
    assert stale.action is PositionMonitoringAction.HOLD
    assert stale.reason_code == "market_price_stale"
    assert stale.input_fingerprint != fresh.input_fingerprint


def test_fingerprint_and_audit_capture_exact_latest_match_source() -> None:
    source = monitoring_input()
    baseline = engine().evaluate(source)
    changed = engine().evaluate(source.model_copy(update={"market_event_match_id": UUID(int=10)}))

    assert baseline.market_event_match_id == UUID(int=9)
    audit_source = cast(dict[str, JsonValue], baseline.audit_snapshot["source"])
    assert audit_source["market_event_match_id"] == str(UUID(int=9))
    assert changed.input_fingerprint != baseline.input_fingerprint


def test_policy_fingerprint_and_version_bind_effective_configuration() -> None:
    baseline = PositionMonitoringPolicy()
    changed = baseline.model_copy(update={"exit_fee_bps": Decimal("20.00")})

    assert position_monitoring_policy_fingerprint(baseline) != (
        position_monitoring_policy_fingerprint(changed)
    )
    assert effective_position_monitoring_policy_version(baseline).startswith("1.0.0+cfg.")
    assert effective_position_monitoring_policy_version(baseline) != (
        effective_position_monitoring_policy_version(changed)
    )


def test_cumulative_basis_allocation_is_path_independent_and_exact_at_terminal() -> None:
    assert cumulative_basis_allocation(
        original_amount=Decimal("0.02"), disposed_quantity=3, initial_quantity=5
    ) == Decimal("0.01")
    assert cumulative_basis_allocation(
        original_amount=Decimal("0.02"), disposed_quantity=4, initial_quantity=5
    ) == Decimal("0.01")
    assert cumulative_basis_allocation(
        original_amount=Decimal("0.02"), disposed_quantity=5, initial_quantity=5
    ) == Decimal("0.02")


def test_accounting_state_rejects_non_cumulative_remaining_basis() -> None:
    with pytest.raises(ValidationError, match="remaining gross basis"):
        accounting_state(
            initial_quantity=5,
            disposed_quantity=3,
            remaining_quantity=2,
            original_gross=Decimal("1.00"),
            original_fees=Decimal("0.02"),
            remaining_gross=Decimal("0.41"),
            remaining_fees=Decimal("0.01"),
            market_value=Decimal("1.10"),
            unrealized_pnl=Decimal("0.68"),
        )
