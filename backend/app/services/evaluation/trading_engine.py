from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.domain.trading_evaluation import (
    EntryLineage,
    EntryLineagePerformance,
    PositionPerformanceFact,
    SnapshotDrawdown,
    TradingEvaluationInput,
    TradingEvaluationPolicy,
    TradingEvaluationSnapshot,
    TradingPerformanceEvaluation,
    TradingPositionStatus,
)

TRADING_PERFORMANCE_FORMULA = (
    "net_pnl=snapshot_total-starting=realized+unrealized;"
    "return=net_pnl/starting;win_rate=wins/completed_including_breakeven;"
    "trade_return=terminal_realized/original_total_cost;"
    "drawdown=max_sequence_peak_to_trough_fraction"
)


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def trading_evaluation_policy_fingerprint(policy: TradingEvaluationPolicy) -> str:
    """Hash every formula and precision decision that defines the evaluation."""
    return _canonical_hash(
        {
            "policy": policy.model_dump(mode="json"),
            "formula": TRADING_PERFORMANCE_FORMULA,
            "pnl_source": "authoritative_portfolio_snapshot",
            "completed_unit": "one_terminal_position_per_filled_opening_trade",
            "entry_edge_mean": "arithmetic_filled_position_mean",
            "breakeven_win_rate_denominator": "included",
            "drawdown_sampling": "portfolio_snapshot_sequence",
        }
    )


def effective_trading_evaluation_version(policy: TradingEvaluationPolicy) -> str:
    """Return a configuration-bound evaluation version."""
    fingerprint = trading_evaluation_policy_fingerprint(policy)
    return f"{policy.code_version}+cfg.{fingerprint[:12]}"


@dataclass(frozen=True)
class _CohortMetrics:
    position_count: int
    open_position_count: int
    completed_position_count: int
    winning_position_count: int
    losing_position_count: int
    breakeven_position_count: int
    net_pnl: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    win_rate: Decimal | None
    average_raw_entry_edge: Decimal | None
    average_adjusted_entry_edge: Decimal | None
    average_terminal_return: Decimal | None
    aggregate_return_on_cost: Decimal | None
    completed_cost_basis: Decimal


def _lineage_key(lineage: EntryLineage) -> tuple[str, ...]:
    return (
        str(lineage.model_version_id),
        lineage.model_name,
        lineage.model_version,
        lineage.model_configuration_fingerprint,
        lineage.opportunity_strategy_name,
        lineage.opportunity_strategy_version,
        lineage.opportunity_policy_fingerprint,
        lineage.sizing_strategy_name,
        lineage.sizing_strategy_version,
        lineage.sizing_policy_fingerprint,
        lineage.risk_policy_name,
        lineage.risk_policy_version,
        lineage.risk_policy_fingerprint,
        lineage.execution_policy_name,
        lineage.execution_policy_version,
        lineage.execution_policy_fingerprint,
        lineage.market_type,
    )


class PaperTradingEvaluationEngine:
    """Compute deterministic paper performance from a reconciled immutable input view."""

    def __init__(self, policy: TradingEvaluationPolicy | None = None) -> None:
        self.policy = policy or TradingEvaluationPolicy()
        self.policy_fingerprint = trading_evaluation_policy_fingerprint(self.policy)
        self.evaluation_version = effective_trading_evaluation_version(self.policy)
        self._ratio_quantum = Decimal("1").scaleb(-self.policy.ratio_decimal_places)

    def evaluate(self, source: TradingEvaluationInput) -> TradingPerformanceEvaluation:
        """Return portfolio, completed-position, drawdown, and entry-lineage metrics."""
        snapshots = tuple(sorted(source.snapshots, key=lambda item: item.sequence))
        head = snapshots[-1]
        cohort = self._cohort_metrics(source.positions)
        net_total_pnl = head.total_portfolio_value - head.starting_bankroll
        groups = self._entry_lineage_groups(source.positions)
        warnings = [
            "maximum drawdown is snapshot-sampled and may miss intraperiod losses",
        ]
        if any(item.includes_non_executable_mark for item in snapshots):
            warnings.append(
                "one or more snapshot values include a non-executable directional-ask fallback mark"
            )
        if cohort.open_position_count:
            warnings.append("open-position P&L excludes hypothetical future exit fees and slippage")
        input_fingerprint = _canonical_hash(
            {
                "source": source.model_dump(mode="json", exclude={"evaluated_at"}),
                "policy_fingerprint": self.policy_fingerprint,
            }
        )
        return TradingPerformanceEvaluation(
            portfolio_id=source.portfolio_id,
            execution_mode="paper",
            currency="USD",
            as_of_snapshot_id=head.id,
            as_of_sequence=head.sequence,
            as_of=head.captured_at,
            calculated_at=source.evaluated_at,
            starting_bankroll=head.starting_bankroll,
            net_total_pnl=net_total_pnl,
            realized_pnl=head.realized_pnl,
            unrealized_pnl=head.unrealized_pnl,
            return_on_starting_bankroll=self._ratio(
                net_total_pnl,
                head.starting_bankroll,
            ),
            realized_return_on_starting_bankroll=self._ratio(
                head.realized_pnl,
                head.starting_bankroll,
            ),
            unrealized_return_on_starting_bankroll=self._ratio(
                head.unrealized_pnl,
                head.starting_bankroll,
            ),
            profitable=net_total_pnl > 0,
            position_count=cohort.position_count,
            open_position_count=cohort.open_position_count,
            completed_position_count=cohort.completed_position_count,
            winning_position_count=cohort.winning_position_count,
            losing_position_count=cohort.losing_position_count,
            breakeven_position_count=cohort.breakeven_position_count,
            win_rate=cohort.win_rate,
            average_raw_entry_edge=cohort.average_raw_entry_edge,
            average_adjusted_entry_edge=cohort.average_adjusted_entry_edge,
            average_terminal_return=cohort.average_terminal_return,
            aggregate_return_on_cost=cohort.aggregate_return_on_cost,
            completed_cost_basis=cohort.completed_cost_basis,
            maximum_drawdown=self._maximum_drawdown(snapshots),
            entry_lineage_groups=groups,
            evaluation_policy_name=self.policy.evaluation_name,
            evaluation_policy_version=self.evaluation_version,
            evaluation_policy_fingerprint=self.policy_fingerprint,
            input_fingerprint=input_fingerprint,
            warnings=tuple(warnings),
        )

    def _cohort_metrics(self, facts: Iterable[PositionPerformanceFact]) -> _CohortMetrics:
        positions = tuple(facts)
        completed = tuple(
            item for item in positions if item.status is not TradingPositionStatus.OPEN
        )
        wins = sum(item.realized_pnl > 0 for item in completed)
        losses = sum(item.realized_pnl < 0 for item in completed)
        breakevens = len(completed) - wins - losses
        realized_pnl = sum(
            (item.realized_pnl for item in positions),
            start=Decimal("0.00"),
        )
        unrealized_pnl = sum(
            (item.unrealized_pnl for item in positions),
            start=Decimal("0.00"),
        )
        completed_cost_basis = sum(
            (item.original_total_cost_basis for item in completed),
            start=Decimal("0.00"),
        )
        terminal_returns = tuple(
            item.realized_pnl / item.original_total_cost_basis for item in completed
        )
        return _CohortMetrics(
            position_count=len(positions),
            open_position_count=len(positions) - len(completed),
            completed_position_count=len(completed),
            winning_position_count=wins,
            losing_position_count=losses,
            breakeven_position_count=breakevens,
            net_pnl=realized_pnl + unrealized_pnl,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            win_rate=(self._ratio(Decimal(wins), Decimal(len(completed))) if completed else None),
            average_raw_entry_edge=self._mean(item.raw_entry_edge for item in positions),
            average_adjusted_entry_edge=self._mean(item.adjusted_entry_edge for item in positions),
            average_terminal_return=self._mean(terminal_returns),
            aggregate_return_on_cost=(
                self._ratio(
                    sum(
                        (item.realized_pnl for item in completed),
                        start=Decimal("0.00"),
                    ),
                    completed_cost_basis,
                )
                if completed
                else None
            ),
            completed_cost_basis=completed_cost_basis,
        )

    def _entry_lineage_groups(
        self,
        positions: tuple[PositionPerformanceFact, ...],
    ) -> tuple[EntryLineagePerformance, ...]:
        grouped: defaultdict[tuple[str, ...], list[PositionPerformanceFact]] = defaultdict(list)
        lineages: dict[tuple[str, ...], EntryLineage] = {}
        for position in positions:
            key = _lineage_key(position.lineage)
            grouped[key].append(position)
            lineages[key] = position.lineage

        results: list[EntryLineagePerformance] = []
        for key in sorted(grouped):
            metrics = self._cohort_metrics(grouped[key])
            results.append(
                EntryLineagePerformance(
                    lineage=lineages[key],
                    position_count=metrics.position_count,
                    open_position_count=metrics.open_position_count,
                    completed_position_count=metrics.completed_position_count,
                    winning_position_count=metrics.winning_position_count,
                    losing_position_count=metrics.losing_position_count,
                    breakeven_position_count=metrics.breakeven_position_count,
                    net_pnl=metrics.net_pnl,
                    realized_pnl=metrics.realized_pnl,
                    unrealized_pnl=metrics.unrealized_pnl,
                    profitable=metrics.net_pnl > 0,
                    win_rate=metrics.win_rate,
                    average_raw_entry_edge=metrics.average_raw_entry_edge,
                    average_adjusted_entry_edge=metrics.average_adjusted_entry_edge,
                    average_terminal_return=metrics.average_terminal_return,
                    aggregate_return_on_cost=metrics.aggregate_return_on_cost,
                    completed_cost_basis=metrics.completed_cost_basis,
                )
            )
        return tuple(results)

    def _maximum_drawdown(
        self,
        snapshots: tuple[TradingEvaluationSnapshot, ...],
    ) -> SnapshotDrawdown:
        peak = snapshots[0]
        max_peak = peak
        max_trough = peak
        max_amount = Decimal("0.00")
        max_fraction = Decimal("0")
        for snapshot in snapshots:
            if snapshot.total_portfolio_value > peak.total_portfolio_value:
                peak = snapshot
            amount = peak.total_portfolio_value - snapshot.total_portfolio_value
            fraction = amount / peak.total_portfolio_value
            if fraction > max_fraction:
                max_fraction = fraction
                max_amount = amount
                max_peak = peak
                max_trough = snapshot
        return SnapshotDrawdown(
            amount=max_amount,
            fraction=self._quantize(max_fraction),
            peak_snapshot_id=max_peak.id,
            trough_snapshot_id=max_trough.id,
            peak_value=max_peak.total_portfolio_value,
            trough_value=max_trough.total_portfolio_value,
            peak_at=max_peak.captured_at,
            trough_at=max_trough.captured_at,
        )

    def _mean(self, values: Iterable[Decimal]) -> Decimal | None:
        items = tuple(values)
        if not items:
            return None
        return self._quantize(sum(items, start=Decimal("0")) / len(items))

    def _ratio(self, numerator: Decimal, denominator: Decimal) -> Decimal:
        if denominator <= 0:
            raise ValueError("performance ratio denominator must be positive")
        return self._quantize(numerator / denominator)

    def _quantize(self, value: Decimal) -> Decimal:
        return value.quantize(self._ratio_quantum, rounding=ROUND_HALF_UP)
