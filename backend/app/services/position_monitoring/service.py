from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid5

from app.domain.portfolio import PortfolioMode, PortfolioSnapshot, PortfolioSnapshotReason
from app.domain.position_monitoring import (
    MonitoredPositionStatus,
    PositionAccountingState,
    PositionMonitoringAction,
    PositionMonitoringDecision,
    PositionMonitoringInput,
    PositionMonitoringPolicy,
)
from app.models.execution import PaperPositionRecord, PositionEventRecord
from app.models.portfolio import PortfolioSnapshotRecord
from app.services.position_monitoring.engine import DeterministicPositionMonitoringEngine
from app.services.position_monitoring.repository import (
    PortfolioPositionTotals,
    PositionLineage,
    PositionMonitoringRepository,
    PositionMonitoringSources,
)
from app.services.position_sizing.repository import (
    portfolio_snapshot_record_id,
    portfolio_state_fingerprint,
)

_LATM_POSITION_EVENT_NAMESPACE = UUID("1f25d2f5-6d4a-40b8-9b17-18de11f2c4fd")


class PositionMonitoringConflictError(ValueError):
    """The requested position cannot enter a new monitoring transition."""


@dataclass(frozen=True)
class PositionMonitoringResult:
    """New or idempotently replayed result for one position."""

    event: PositionEventRecord
    position: PaperPositionRecord
    snapshot: PortfolioSnapshotRecord | None
    created: bool


@dataclass(frozen=True)
class PositionMonitoringRunResult:
    """Bounded external-scheduler run across open paper positions."""

    examined: int
    results: tuple[PositionMonitoringResult, ...]
    decision_counts: dict[str, int]
    reason_counts: dict[str, int]

    @property
    def created(self) -> int:
        return sum(item.created for item in self.results)

    @property
    def replayed(self) -> int:
        return len(self.results) - self.created

    @property
    def snapshots_appended(self) -> int:
        return sum(item.created and item.snapshot is not None for item in self.results)


def position_event_record_id(
    *, position_id: UUID, policy_version: str, input_fingerprint: str
) -> UUID:
    """Return a stable event identity for one semantic monitoring input."""
    return uuid5(
        _LATM_POSITION_EVENT_NAMESPACE,
        f"event:{position_id}:{policy_version}:{input_fingerprint}",
    )


def position_projection_fingerprint(position: PaperPositionRecord) -> str:
    """Hash the complete current financial projection and source provenance."""
    payload = {
        "id": str(position.id),
        "status": position.status,
        "version": position.version,
        "initial_quantity": position.initial_quantity,
        "quantity": position.quantity,
        "disposed_quantity": position.disposed_quantity,
        "original_gross_cost_basis": str(position.original_gross_cost_basis),
        "original_entry_fees": str(position.original_entry_fees),
        "original_total_cost_basis": str(position.original_total_cost_basis),
        "gross_cost_basis": str(position.gross_cost_basis),
        "entry_fees": str(position.entry_fees),
        "total_cost_basis": str(position.total_cost_basis),
        "market_price_id": str(position.market_price_id),
        "latest_base_forecast_id": (
            str(position.latest_base_forecast_id)
            if position.latest_base_forecast_id is not None
            else None
        ),
        "market_resolution_id": (
            str(position.market_resolution_id)
            if position.market_resolution_id is not None
            else None
        ),
        "mark_price": str(position.mark_price),
        "mark_basis": position.mark_basis,
        "market_value": str(position.market_value),
        "unrealized_pnl": str(position.unrealized_pnl),
        "realized_pnl": str(position.realized_pnl),
        "closed_at": position.closed_at.isoformat() if position.closed_at else None,
        "settled_at": position.settled_at.isoformat() if position.settled_at else None,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class PositionMonitoringService:
    """Reevaluate and atomically transition provider-free paper positions."""

    def __init__(
        self,
        *,
        repository: PositionMonitoringRepository,
        policy: PositionMonitoringPolicy,
        runtime_trading_mode: str,
    ) -> None:
        self._repository = repository
        self._policy = policy
        self._engine = DeterministicPositionMonitoringEngine(policy)
        self._runtime_trading_mode = runtime_trading_mode

    async def run(
        self,
        *,
        position_id: UUID | None,
        portfolio_id: UUID | None,
        limit: int,
        offset: int,
    ) -> PositionMonitoringRunResult:
        if position_id is not None:
            position_ids = [position_id]
        else:
            position_ids = await self._repository.list_open_position_ids(
                portfolio_id=portfolio_id,
                limit=limit,
                offset=offset,
            )
        results: list[PositionMonitoringResult] = []
        for selected_id in position_ids:
            results.append(await self.evaluate(selected_id))
        decisions = Counter(item.event.decision for item in results)
        reasons = Counter(item.event.reason_code for item in results)
        return PositionMonitoringRunResult(
            examined=len(position_ids),
            results=tuple(results),
            decision_counts=dict(sorted(decisions.items())),
            reason_counts=dict(sorted(reasons.items())),
        )

    async def evaluate(self, position_id: UUID) -> PositionMonitoringResult:
        lineage = await self._repository.get_lineage(position_id)
        if lineage is None:
            raise LookupError("position not found")
        if lineage.position.status != "open":
            return await self._replay_terminal(lineage.position)
        if lineage.opening_match.sports_event_id is None:
            raise RuntimeError("position opening match has no sports event")

        portfolio = await self._repository.lock_portfolio(lineage.position.portfolio_id)
        market = await self._repository.lock_market(lineage.position.market_id)
        event = await self._repository.lock_event(lineage.opening_match.sports_event_id)
        if portfolio is None or market is None or event is None:
            raise RuntimeError("position parent lineage disappeared while locking")
        position = await self._repository.lock_position(position_id)
        latest_snapshot = await self._repository.lock_latest_snapshot(portfolio.id)
        if position is None or latest_snapshot is None:
            raise RuntimeError("position or portfolio ledger disappeared while locking")
        sources = await self._repository.lock_sources(
            market=market,
            event=event,
            opening_forecast=lineage.opening_forecast,
        )
        evaluated_at = await self._repository.database_time()
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("position monitoring clock must be timezone-aware")

        if position.status != "open":
            return await self._replay_terminal(position)
        self._validate_lineage(lineage, position)
        before_totals = await self._repository.portfolio_position_totals(portfolio.id)
        self._validate_portfolio_totals(latest_snapshot, before_totals)
        source = self._monitoring_input(
            position=position,
            lineage=lineage,
            sources=sources,
            snapshot=latest_snapshot,
            evaluated_at=evaluated_at,
        )
        decision = self._engine.evaluate(source)
        existing = await self._repository.get_event_by_input(
            position_id=position.id,
            policy_version=decision.policy_version,
            input_fingerprint=decision.input_fingerprint,
        )
        if existing is not None:
            return await self._replay(existing, position)

        projection_before = position.projection_fingerprint
        state_changed = decision.after != decision.before
        position_version_before = position.version
        if state_changed:
            self._apply_projection(position, decision, evaluated_at)
            projection_after = position_projection_fingerprint(position)
            position.projection_fingerprint = projection_after
        else:
            projection_after = projection_before
        snapshot = (
            self._next_snapshot(latest_snapshot, decision, evaluated_at) if state_changed else None
        )
        event_record = self._event_record(
            lineage=lineage,
            decision=decision,
            model_probability=source.model_probability,
            position_version_before=position_version_before,
            projection_before=projection_before,
            projection_after=projection_after,
            snapshot_after_id=snapshot.id if snapshot is not None else None,
            state_changed=state_changed,
            recorded_at=evaluated_at,
        )
        try:
            await self._repository.stage_event(event=event_record, snapshot=snapshot)
            after_totals = await self._repository.portfolio_position_totals(portfolio.id)
            expected_snapshot = snapshot or latest_snapshot
            self._validate_portfolio_totals(expected_snapshot, after_totals)
            await self._repository.commit()
        except Exception:
            await self._repository.rollback()
            raise
        return PositionMonitoringResult(
            event=event_record,
            position=position,
            snapshot=snapshot,
            created=True,
        )

    async def _replay_terminal(self, position: PaperPositionRecord) -> PositionMonitoringResult:
        event = await self._repository.latest_event_for_position(position.id)
        if event is None:
            raise PositionMonitoringConflictError("terminal position has no monitoring event")
        return await self._replay(event, position)

    async def _replay(
        self,
        event: PositionEventRecord,
        position: PaperPositionRecord,
    ) -> PositionMonitoringResult:
        snapshot = (
            await self._repository.get_snapshot(event.portfolio_snapshot_after_id)
            if event.portfolio_snapshot_after_id is not None
            else None
        )
        return PositionMonitoringResult(
            event=event,
            position=position,
            snapshot=snapshot,
            created=False,
        )

    def _monitoring_input(
        self,
        *,
        position: PaperPositionRecord,
        lineage: PositionLineage,
        sources: PositionMonitoringSources,
        snapshot: PortfolioSnapshotRecord,
        evaluated_at: datetime,
    ) -> PositionMonitoringInput:
        latest_match = sources.latest_match
        match_current = (
            latest_match is not None
            and latest_match.status == "matched"
            and latest_match.automatic_trading_eligible
            and latest_match.sports_event_id == sources.event.id
        )
        price = sources.latest_price
        forecast = sources.latest_forecast
        model_probability: Decimal | None = None
        forecast_oriented = False
        if forecast is not None:
            if position.outcome_team_id == forecast.home_team_id:
                model_probability = forecast.home_win_probability
                forecast_oriented = True
            elif position.outcome_team_id == forecast.away_team_id:
                model_probability = forecast.away_win_probability
                forecast_oriented = True
        resolution = sources.official_resolution
        held_payout = None
        if resolution is not None:
            held_payout = (
                resolution.yes_payout if position.direction == "yes" else resolution.no_payout
            )
        return PositionMonitoringInput(
            position_id=position.id,
            portfolio_id=position.portfolio_id,
            portfolio_snapshot_id=snapshot.id,
            market_id=position.market_id,
            outcome_team_id=position.outcome_team_id,
            direction=position.direction,
            runtime_trading_mode=self._runtime_trading_mode,
            position_execution_mode=position.execution_mode,
            position=PositionAccountingState(
                status=MonitoredPositionStatus(position.status),
                initial_quantity=position.initial_quantity,
                disposed_quantity=position.disposed_quantity,
                remaining_quantity=position.quantity,
                original_gross_cost_basis=position.original_gross_cost_basis,
                original_entry_fees=position.original_entry_fees,
                original_total_cost_basis=position.original_total_cost_basis,
                remaining_gross_cost_basis=position.gross_cost_basis,
                remaining_entry_fees=position.entry_fees,
                remaining_total_cost_basis=position.total_cost_basis,
                mark_price=position.mark_price,
                mark_basis=position.mark_basis,
                market_value=position.market_value,
                unrealized_pnl=position.unrealized_pnl,
                realized_pnl=position.realized_pnl,
            ),
            market_status=sources.market.status.lower(),
            event_status=sources.event.status.lower(),
            event_postponed=sources.event.postponed,
            event_start_time=sources.event.scheduled_start_time,
            event_semantics_are_current=match_current,
            market_event_match_id=(latest_match.id if latest_match is not None else None),
            market_price_id=price.id if price is not None else None,
            market_price_is_current=price is not None,
            market_price_retrieved_at=price.retrieved_at if price is not None else None,
            yes_bid=price.yes_bid if price is not None else None,
            no_bid=price.no_bid if price is not None else None,
            forecast_id=forecast.id if forecast is not None else None,
            forecast_is_current=forecast is not None and forecast_oriented,
            forecast_generated_at=forecast.generated_at if forecast is not None else None,
            model_probability=model_probability,
            official_resolution_id=resolution.id if resolution is not None else None,
            official_resolution_is_final=resolution is not None,
            official_held_side_payout=held_payout,
            evaluated_at=evaluated_at,
        )

    @staticmethod
    def _validate_lineage(lineage: PositionLineage, position: PaperPositionRecord) -> None:
        trade = lineage.opening_trade
        if (
            trade.status != "filled"
            or trade.execution_mode != "paper"
            or position.execution_mode != "paper"
            or trade.portfolio_id != position.portfolio_id
            or trade.market_id != position.market_id
            or trade.outcome_team_id != position.outcome_team_id
            or trade.direction != position.direction
        ):
            raise RuntimeError("position projection does not match its filled paper entry")

    @staticmethod
    def _validate_portfolio_totals(
        snapshot: PortfolioSnapshotRecord,
        totals: PortfolioPositionTotals,
    ) -> None:
        if (
            snapshot.committed_capital != totals.committed_capital
            or snapshot.open_position_value != totals.open_position_value
            or snapshot.unrealized_pnl != totals.unrealized_pnl
            or snapshot.realized_pnl != totals.realized_pnl
        ):
            raise RuntimeError("portfolio snapshot does not reconcile with position projections")

    @staticmethod
    def _apply_projection(
        position: PaperPositionRecord,
        decision: PositionMonitoringDecision,
        applied_at: datetime,
    ) -> None:
        after = decision.after
        position.status = after.status.value
        position.quantity = after.remaining_quantity
        position.disposed_quantity = after.disposed_quantity
        position.gross_cost_basis = after.remaining_gross_cost_basis
        position.entry_fees = after.remaining_entry_fees
        position.total_cost_basis = after.remaining_total_cost_basis
        position.mark_price = after.mark_price
        position.mark_basis = after.mark_basis
        position.market_value = after.market_value
        position.unrealized_pnl = after.unrealized_pnl
        position.realized_pnl = after.realized_pnl
        if decision.market_price_id is not None:
            position.market_price_id = decision.market_price_id
        if decision.forecast_id is not None:
            position.latest_base_forecast_id = decision.forecast_id
        position.market_resolution_id = (
            decision.official_resolution_id
            if decision.action is PositionMonitoringAction.SETTLE
            else None
        )
        position.version += 1
        position.updated_at = applied_at
        position.closed_at = (
            applied_at if decision.action is PositionMonitoringAction.CLOSE else None
        )
        position.settled_at = (
            applied_at if decision.action is PositionMonitoringAction.SETTLE else None
        )

    @staticmethod
    def _next_snapshot(
        latest: PortfolioSnapshotRecord,
        decision: PositionMonitoringDecision,
        captured_at: datetime,
    ) -> PortfolioSnapshotRecord:
        delta = decision.portfolio_delta
        reason_by_action = {
            PositionMonitoringAction.HOLD: PortfolioSnapshotReason.PAPER_POSITION_MARKED,
            PositionMonitoringAction.REDUCE: PortfolioSnapshotReason.PAPER_POSITION_REDUCED,
            PositionMonitoringAction.CLOSE: PortfolioSnapshotReason.PAPER_POSITION_CLOSED,
            PositionMonitoringAction.SETTLE: PortfolioSnapshotReason.PAPER_POSITION_SETTLED,
        }
        snapshot = PortfolioSnapshot(
            id=portfolio_snapshot_record_id(latest.portfolio_id, latest.sequence + 1),
            portfolio_id=latest.portfolio_id,
            sequence=latest.sequence + 1,
            mode=PortfolioMode.PAPER,
            currency=latest.currency,
            starting_bankroll=latest.starting_bankroll,
            current_bankroll=latest.current_bankroll + delta.current_bankroll,
            cash_balance=latest.cash_balance + delta.cash_balance,
            reserved_capital=latest.reserved_capital + delta.reserved_capital,
            committed_capital=latest.committed_capital + delta.committed_capital,
            available_bankroll=latest.available_bankroll + delta.available_bankroll,
            realized_pnl=latest.realized_pnl + delta.realized_pnl,
            open_position_value=latest.open_position_value + delta.open_position_value,
            unrealized_pnl=latest.unrealized_pnl + delta.unrealized_pnl,
            total_portfolio_value=latest.total_portfolio_value + delta.total_portfolio_value,
            previous_snapshot_id=latest.id,
            reason=reason_by_action[decision.action],
            state_fingerprint="0" * 64,
            captured_at=captured_at,
        )
        snapshot = snapshot.model_copy(
            update={"state_fingerprint": portfolio_state_fingerprint(snapshot)}
        )
        values = snapshot.model_dump(mode="python")
        values["execution_mode"] = snapshot.mode.value
        values["reason"] = snapshot.reason.value
        del values["mode"]
        return PortfolioSnapshotRecord(**values)

    def _event_record(
        self,
        *,
        lineage: PositionLineage,
        decision: PositionMonitoringDecision,
        model_probability: Decimal | None,
        position_version_before: int,
        projection_before: str,
        projection_after: str,
        snapshot_after_id: UUID | None,
        state_changed: bool,
        recorded_at: datetime,
    ) -> PositionEventRecord:
        economics = decision.economics
        is_settlement = decision.action is PositionMonitoringAction.SETTLE
        required_rules = (
            {"paper_only", "position_open", "official_resolution_complete"}
            if is_settlement
            else {item.rule for item in decision.checks}
        )
        failed_rules = [
            item.rule for item in decision.checks if item.rule in required_rules and not item.passed
        ]
        return PositionEventRecord(
            id=position_event_record_id(
                position_id=decision.position_id,
                policy_version=decision.policy_version,
                input_fingerprint=decision.input_fingerprint,
            ),
            position_id=decision.position_id,
            opening_trade_id=lineage.opening_trade.id,
            portfolio_id=decision.portfolio_id,
            market_id=decision.market_id,
            outcome_team_id=decision.outcome_team_id,
            market_price_id=decision.market_price_id,
            base_forecast_id=decision.forecast_id,
            market_resolution_id=decision.official_resolution_id if is_settlement else None,
            portfolio_snapshot_before_id=decision.portfolio_snapshot_id,
            portfolio_snapshot_after_id=snapshot_after_id,
            execution_mode="paper",
            decision=decision.action.value,
            reason_code=decision.reason_code,
            reason=decision.reason,
            all_required_checks_passed=not failed_rules,
            state_changed=state_changed,
            failed_rules=failed_rules,
            check_results=[item.model_dump(mode="json") for item in decision.checks],
            position_version_before=position_version_before,
            position_version_after=position_version_before + int(state_changed),
            status_before=decision.before.status.value,
            status_after=decision.after.status.value,
            quantity_before=decision.before.remaining_quantity,
            action_quantity=economics.disposed_quantity if economics is not None else 0,
            quantity_after=decision.after.remaining_quantity,
            gross_cost_basis_before=decision.before.remaining_gross_cost_basis,
            entry_fees_before=decision.before.remaining_entry_fees,
            total_cost_basis_before=decision.before.remaining_total_cost_basis,
            allocated_gross_cost_basis=(
                economics.allocated_gross_cost_basis if economics else Decimal("0.00")
            ),
            allocated_entry_fees=(economics.allocated_entry_fees if economics else Decimal("0.00")),
            allocated_total_cost_basis=(
                economics.allocated_total_cost_basis if economics else Decimal("0.00")
            ),
            gross_cost_basis_after=decision.after.remaining_gross_cost_basis,
            entry_fees_after=decision.after.remaining_entry_fees,
            total_cost_basis_after=decision.after.remaining_total_cost_basis,
            reference_price=economics.reference_price if economics else None,
            exit_price=(economics.execution_price if economics and not is_settlement else None),
            exit_slippage_bps=(
                self._policy.exit_slippage_bps if economics and not is_settlement else None
            ),
            exit_slippage_amount_per_contract=(
                economics.reference_price - economics.execution_price
                if economics and not is_settlement
                else None
            ),
            reference_gross_proceeds=(
                economics.reference_gross_proceeds if economics and not is_settlement else None
            ),
            slippage_cost=(economics.slippage_cost if economics and not is_settlement else None),
            gross_proceeds=economics.gross_proceeds if economics else None,
            exit_fee_bps=(self._policy.exit_fee_bps if economics and not is_settlement else None),
            exit_fee_amount=(economics.exit_fee if economics and not is_settlement else None),
            net_proceeds=economics.net_proceeds if economics else None,
            settlement_payout_per_contract=(
                economics.execution_price if economics and is_settlement else None
            ),
            model_probability=model_probability,
            hold_edge=decision.hold_edge,
            after_mark_price=decision.after.mark_price,
            after_mark_basis=decision.after.mark_basis,
            after_market_value=decision.after.market_value,
            after_unrealized_pnl=decision.after.unrealized_pnl,
            realized_pnl_before=decision.before.realized_pnl,
            realized_pnl_increment=(
                economics.realized_pnl_increment if economics else Decimal("0.00")
            ),
            realized_pnl_cumulative=decision.after.realized_pnl,
            policy_name=decision.policy_name,
            policy_version=decision.policy_version,
            policy_fingerprint=decision.policy_fingerprint,
            input_fingerprint=decision.input_fingerprint,
            position_projection_fingerprint_before=projection_before,
            position_projection_fingerprint_after=projection_after,
            evaluated_at=decision.evaluated_at,
            executed_at=(decision.evaluated_at if economics is not None else None),
            recorded_at=recorded_at,
            audit_snapshot=decision.audit_snapshot,
        )
