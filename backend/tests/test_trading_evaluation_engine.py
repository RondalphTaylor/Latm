from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain.trading_evaluation import (
    EntryLineage,
    PositionPerformanceFact,
    TradingEvaluationInput,
    TradingEvaluationPolicy,
    TradingEvaluationSnapshot,
    TradingPositionStatus,
)
from app.services.evaluation.trading_engine import (
    PaperTradingEvaluationEngine,
    effective_trading_evaluation_version,
    trading_evaluation_policy_fingerprint,
)

START = datetime(2026, 8, 18, 12, tzinfo=UTC)
EVALUATED_AT = START + timedelta(hours=4)
PORTFOLIO_ID = UUID("a0000000-0000-0000-0000-000000000001")


def lineage(*, alternate: bool = False) -> EntryLineage:
    marker = "b" if alternate else "a"
    return EntryLineage(
        model_version_id=UUID(
            "a0000000-0000-0000-0000-000000000102"
            if alternate
            else "a0000000-0000-0000-0000-000000000101"
        ),
        model_name="nba_elo",
        model_version="2.0.0+cfg.bbbbbbbbbbbb" if alternate else "1.0.0+cfg.aaaaaaaaaaaa",
        model_configuration_fingerprint=marker * 64,
        opportunity_strategy_name="raw_edge",
        opportunity_strategy_version=(
            "2.0.0+cfg.bbbbbbbbbbbb" if alternate else "1.0.0+cfg.aaaaaaaaaaaa"
        ),
        opportunity_policy_fingerprint=marker * 64,
        sizing_strategy_name="raw_edge_bands",
        sizing_strategy_version=(
            "2.0.0+cfg.bbbbbbbbbbbb" if alternate else "1.0.0+cfg.aaaaaaaaaaaa"
        ),
        sizing_policy_fingerprint=marker * 64,
        risk_policy_name="mvp_risk",
        risk_policy_version=("2.0.0+cfg.bbbbbbbbbbbb" if alternate else "1.0.0+cfg.aaaaaaaaaaaa"),
        risk_policy_fingerprint=marker * 64,
        execution_policy_name="paper_immediate_fill",
        execution_policy_version=(
            "2.0.0+cfg.bbbbbbbbbbbb" if alternate else "1.0.0+cfg.aaaaaaaaaaaa"
        ),
        execution_policy_fingerprint=marker * 64,
        market_type="binary",
    )


def snapshot(
    *,
    sequence: int,
    realized_pnl: Decimal,
    unrealized_pnl: Decimal,
    previous_snapshot_id: UUID | None,
    fallback_mark: bool = False,
) -> TradingEvaluationSnapshot:
    return TradingEvaluationSnapshot(
        id=UUID(f"a0000000-0000-0000-0000-{sequence + 1:012d}"),
        portfolio_id=PORTFOLIO_ID,
        sequence=sequence,
        previous_snapshot_id=previous_snapshot_id,
        starting_bankroll=Decimal("1000.00"),
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        total_portfolio_value=Decimal("1000.00") + realized_pnl + unrealized_pnl,
        state_fingerprint=f"{sequence}" * 64,
        captured_at=START + timedelta(hours=sequence),
        includes_non_executable_mark=fallback_mark,
    )


def position(
    *,
    index: int,
    status: TradingPositionStatus,
    cost: Decimal,
    realized_pnl: Decimal,
    unrealized_pnl: Decimal,
    raw_edge: Decimal,
    adjusted_edge: Decimal,
    alternate_lineage: bool = False,
) -> PositionPerformanceFact:
    return PositionPerformanceFact(
        position_id=UUID(f"a1000000-0000-0000-0000-{index:012d}"),
        opening_trade_id=UUID(f"a2000000-0000-0000-0000-{index:012d}"),
        portfolio_id=PORTFOLIO_ID,
        status=status,
        original_total_cost_basis=cost,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        raw_entry_edge=raw_edge,
        adjusted_entry_edge=adjusted_edge,
        executed_at=START + timedelta(minutes=index),
        terminal_at=(None if status is TradingPositionStatus.OPEN else START + timedelta(hours=3)),
        lineage=lineage(alternate=alternate_lineage),
    )


def evaluation_input() -> TradingEvaluationInput:
    snapshots = (
        snapshot(
            sequence=0,
            realized_pnl=Decimal("0.00"),
            unrealized_pnl=Decimal("0.00"),
            previous_snapshot_id=None,
        ),
        snapshot(
            sequence=1,
            realized_pnl=Decimal("50.00"),
            unrealized_pnl=Decimal("50.00"),
            previous_snapshot_id=UUID("a0000000-0000-0000-0000-000000000001"),
            fallback_mark=True,
        ),
        snapshot(
            sequence=2,
            realized_pnl=Decimal("-100.00"),
            unrealized_pnl=Decimal("-20.00"),
            previous_snapshot_id=UUID("a0000000-0000-0000-0000-000000000002"),
        ),
        snapshot(
            sequence=3,
            realized_pnl=Decimal("-20.00"),
            unrealized_pnl=Decimal("10.00"),
            previous_snapshot_id=UUID("a0000000-0000-0000-0000-000000000003"),
        ),
    )
    positions = (
        position(
            index=1,
            status=TradingPositionStatus.SETTLED,
            cost=Decimal("100.00"),
            realized_pnl=Decimal("50.00"),
            unrealized_pnl=Decimal("0.00"),
            raw_edge=Decimal("0.120000"),
            adjusted_edge=Decimal("0.100000"),
        ),
        position(
            index=2,
            status=TradingPositionStatus.CLOSED,
            cost=Decimal("200.00"),
            realized_pnl=Decimal("-80.00"),
            unrealized_pnl=Decimal("0.00"),
            raw_edge=Decimal("0.060000"),
            adjusted_edge=Decimal("0.040000"),
        ),
        position(
            index=3,
            status=TradingPositionStatus.SETTLED,
            cost=Decimal("50.00"),
            realized_pnl=Decimal("0.00"),
            unrealized_pnl=Decimal("0.00"),
            raw_edge=Decimal("0.080000"),
            adjusted_edge=Decimal("0.070000"),
            alternate_lineage=True,
        ),
        position(
            index=4,
            status=TradingPositionStatus.OPEN,
            cost=Decimal("100.00"),
            realized_pnl=Decimal("10.00"),
            unrealized_pnl=Decimal("10.00"),
            raw_edge=Decimal("0.100000"),
            adjusted_edge=Decimal("0.080000"),
            alternate_lineage=True,
        ),
    )
    return TradingEvaluationInput(
        portfolio_id=PORTFOLIO_ID,
        snapshots=snapshots,
        positions=positions,
        evaluated_at=EVALUATED_AT,
    )


def test_exact_authoritative_portfolio_and_completed_position_metrics() -> None:
    result = PaperTradingEvaluationEngine().evaluate(evaluation_input())

    assert result.net_total_pnl == Decimal("-10.00")
    assert result.realized_pnl == Decimal("-20.00")
    assert result.unrealized_pnl == Decimal("10.00")
    assert result.return_on_starting_bankroll == Decimal("-0.0100000000")
    assert result.realized_return_on_starting_bankroll == Decimal("-0.0200000000")
    assert result.unrealized_return_on_starting_bankroll == Decimal("0.0100000000")
    assert result.profitable is False
    assert result.position_count == 4
    assert result.open_position_count == 1
    assert result.completed_position_count == 3
    assert result.winning_position_count == 1
    assert result.losing_position_count == 1
    assert result.breakeven_position_count == 1
    assert result.win_rate == Decimal("0.3333333333")
    assert result.average_raw_entry_edge == Decimal("0.0900000000")
    assert result.average_adjusted_entry_edge == Decimal("0.0725000000")
    assert result.average_terminal_return == Decimal("0.0333333333")
    assert result.aggregate_return_on_cost == Decimal("-0.0857142857")
    assert result.completed_cost_basis == Decimal("350.00")


def test_drawdown_uses_sequence_peak_and_trough_and_discloses_mark_limits() -> None:
    result = PaperTradingEvaluationEngine().evaluate(evaluation_input())

    assert result.maximum_drawdown.amount == Decimal("220.00")
    assert result.maximum_drawdown.fraction == Decimal("0.2000000000")
    assert result.maximum_drawdown.peak_snapshot_id == UUID("a0000000-0000-0000-0000-000000000002")
    assert result.maximum_drawdown.trough_snapshot_id == UUID(
        "a0000000-0000-0000-0000-000000000003"
    )
    assert result.maximum_drawdown.peak_at == START + timedelta(hours=1)
    assert result.maximum_drawdown.trough_at == START + timedelta(hours=2)
    assert result.warnings == (
        "maximum drawdown is snapshot-sampled and may miss intraperiod losses",
        "one or more snapshot values include a non-executable directional-ask fallback mark",
        "open-position P&L excludes hypothetical future exit fees and slippage",
    )


def test_entry_lineages_partition_each_position_once_without_exit_double_counting() -> None:
    result = PaperTradingEvaluationEngine().evaluate(evaluation_input())

    assert len(result.entry_lineage_groups) == 2
    assert sum(item.position_count for item in result.entry_lineage_groups) == 4
    assert (
        sum(
            (item.net_pnl for item in result.entry_lineage_groups),
            start=Decimal("0.00"),
        )
        == result.net_total_pnl
    )
    first, second = result.entry_lineage_groups
    assert first.lineage.model_version == "1.0.0+cfg.aaaaaaaaaaaa"
    assert first.position_count == 2
    assert first.completed_position_count == 2
    assert first.net_pnl == Decimal("-30.00")
    assert first.win_rate == Decimal("0.5000000000")
    assert second.lineage.model_version == "2.0.0+cfg.bbbbbbbbbbbb"
    assert second.position_count == 2
    assert second.open_position_count == 1
    assert second.net_pnl == Decimal("20.00")


def test_empty_completed_denominators_are_null_not_zero() -> None:
    source = TradingEvaluationInput(
        portfolio_id=PORTFOLIO_ID,
        snapshots=(
            snapshot(
                sequence=0,
                realized_pnl=Decimal("0.00"),
                unrealized_pnl=Decimal("0.00"),
                previous_snapshot_id=None,
            ),
        ),
        evaluated_at=EVALUATED_AT,
    )

    result = PaperTradingEvaluationEngine().evaluate(source)

    assert result.net_total_pnl == Decimal("0.00")
    assert result.return_on_starting_bankroll == Decimal("0E-10")
    assert result.profitable is False
    assert result.win_rate is None
    assert result.average_raw_entry_edge is None
    assert result.average_adjusted_entry_edge is None
    assert result.average_terminal_return is None
    assert result.aggregate_return_on_cost is None
    assert result.entry_lineage_groups == ()
    assert result.maximum_drawdown.amount == Decimal("0.00")
    assert result.maximum_drawdown.peak_snapshot_id == result.maximum_drawdown.trough_snapshot_id


def test_source_validation_rejects_broken_chains_duplicates_and_unreconciled_pnl() -> None:
    source = evaluation_input()
    dumped = source.model_dump(mode="python")
    broken_snapshots = list(dumped["snapshots"])
    broken_snapshots[2]["previous_snapshot_id"] = UUID(int=99)
    with pytest.raises(ValidationError, match="predecessor chain"):
        TradingEvaluationInput.model_validate({**dumped, "snapshots": broken_snapshots})

    duplicate_dump = source.model_dump(mode="python")
    with pytest.raises(ValidationError, match="only once"):
        TradingEvaluationInput.model_validate(
            {
                **duplicate_dump,
                "positions": [
                    *duplicate_dump["positions"],
                    duplicate_dump["positions"][0],
                ],
            }
        )

    unreconciled_snapshots = list(source.model_dump(mode="python")["snapshots"])
    unreconciled_snapshots[-1]["realized_pnl"] = Decimal("-19.00")
    unreconciled_snapshots[-1]["total_portfolio_value"] = Decimal("991.00")
    with pytest.raises(ValidationError, match="realized P&L does not reconcile"):
        TradingEvaluationInput.model_validate(
            {**source.model_dump(mode="python"), "snapshots": unreconciled_snapshots}
        )


def test_terminal_shape_and_paper_only_inputs_fail_closed() -> None:
    with pytest.raises(ValidationError, match="completed performance facts require"):
        PositionPerformanceFact.model_validate(
            {
                **position(
                    index=9,
                    status=TradingPositionStatus.SETTLED,
                    cost=Decimal("10.00"),
                    realized_pnl=Decimal("1.00"),
                    unrealized_pnl=Decimal("0.00"),
                    raw_edge=Decimal("0.100000"),
                    adjusted_edge=Decimal("0.090000"),
                ).model_dump(mode="python"),
                "terminal_at": None,
            }
        )
    with pytest.raises(ValidationError, match="paper"):
        TradingEvaluationInput.model_validate(
            {**evaluation_input().model_dump(mode="python"), "execution_mode": "live"}
        )


def test_policy_precision_changes_version_fingerprint_and_result_precision() -> None:
    baseline = TradingEvaluationPolicy()
    changed = baseline.model_copy(update={"ratio_decimal_places": 8})

    result = PaperTradingEvaluationEngine(changed).evaluate(evaluation_input())

    assert result.win_rate == Decimal("0.33333333")
    assert trading_evaluation_policy_fingerprint(changed) != (
        trading_evaluation_policy_fingerprint(baseline)
    )
    assert effective_trading_evaluation_version(changed) != (
        effective_trading_evaluation_version(baseline)
    )
    assert result.evaluation_policy_fingerprint == trading_evaluation_policy_fingerprint(changed)
    assert (
        result.input_fingerprint
        == PaperTradingEvaluationEngine(changed).evaluate(evaluation_input()).input_fingerprint
    )
