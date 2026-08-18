from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid5

from app.domain.execution import (
    PaperExecutionDecision,
    PaperExecutionInput,
    PaperExecutionPolicy,
    PaperTradeStatus,
)
from app.domain.portfolio import PortfolioMode, PortfolioSnapshot, PortfolioSnapshotReason
from app.domain.risk import RiskDecisionType, RiskPolicy
from app.models.execution import PaperPositionRecord, PaperTradeRecord
from app.models.portfolio import PortfolioSnapshotRecord
from app.models.risk import RiskDecisionRecord
from app.services.execution.engine import ImmediatePaperExecutionEngine
from app.services.execution.repository import PaperExecutionRepository
from app.services.position_sizing.repository import (
    portfolio_snapshot_record_id,
    portfolio_state_fingerprint,
)
from app.services.risk.engine import DeterministicRiskEngine
from app.services.risk.service import build_risk_evaluation_input

_LATM_EXECUTION_NAMESPACE = UUID("17483122-6916-46ca-9da2-f0a967631eb8")


class PaperExecutionConflictError(ValueError):
    """The selected evidence is not an automatic execution authorization."""


@dataclass(frozen=True)
class PaperExecutionResult:
    """New or idempotently replayed terminal paper execution."""

    trade: PaperTradeRecord
    position: PaperPositionRecord | None
    snapshot: PortfolioSnapshotRecord | None
    created: bool


def paper_trade_record_id(risk_decision_id: UUID) -> UUID:
    return uuid5(_LATM_EXECUTION_NAMESPACE, f"trade:{risk_decision_id}")


def paper_position_record_id(trade_id: UUID) -> UUID:
    return uuid5(_LATM_EXECUTION_NAMESPACE, f"position:{trade_id}")


class PaperExecutionService:
    """Revalidate one authorization and apply a paper-only entry atomically."""

    def __init__(
        self,
        *,
        repository: PaperExecutionRepository,
        risk_policy: RiskPolicy,
        execution_policy: PaperExecutionPolicy,
        runtime_trading_mode: str,
        active_sizing_strategy_version: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._risk_policy = risk_policy
        self._risk_engine = DeterministicRiskEngine(risk_policy)
        self._execution_policy = execution_policy
        self._execution_engine = ImmediatePaperExecutionEngine(execution_policy)
        self._runtime_trading_mode = runtime_trading_mode
        self._active_sizing_strategy_version = active_sizing_strategy_version
        self._clock = clock

    async def execute(self, risk_decision_id: UUID) -> PaperExecutionResult:
        existing = await self._repository.get_trade_for_risk(risk_decision_id)
        if existing is not None:
            return await self._replay(existing)
        risk = await self._repository.get_risk_decision(risk_decision_id)
        if risk is None:
            raise LookupError("risk decision not found")
        if (
            risk.decision != RiskDecisionType.AUTO_APPROVE.value
            or not risk.all_required_checks_passed
        ):
            raise PaperExecutionConflictError(
                "only an automatic risk approval may enter paper execution"
            )
        portfolio = await self._repository.lock_portfolio(risk.portfolio_id)
        if portfolio is None:
            raise RuntimeError("risk decision references a missing portfolio")
        await self._repository.lock_execution_parents(
            market_id=risk.market_id,
            proposal_id=risk.position_size_proposal_id,
        )
        locked_risk = await self._repository.lock_risk_decision(risk.id)
        if locked_risk is None:
            raise RuntimeError("risk decision disappeared while acquiring execution locks")
        risk = locked_risk
        attempted_at = (
            self._clock() if self._clock is not None else await self._repository.database_time()
        )
        if attempted_at.tzinfo is None or attempted_at.utcoffset() is None:
            raise ValueError("paper execution clock must return a timezone-aware datetime")

        # A concurrent request can only pass the pre-lock read before this request commits.
        existing = await self._repository.get_trade_for_risk(risk_decision_id)
        if existing is not None:
            return await self._replay(existing)
        context = await self._repository.get_risk_context(
            proposal_id=risk.position_size_proposal_id,
            as_of=attempted_at,
        )
        if context is None:
            raise RuntimeError("risk decision references a missing proposal")
        revalidated_source = build_risk_evaluation_input(
            context,
            evaluated_at=attempted_at,
            runtime_trading_mode=self._runtime_trading_mode,
            active_sizing_strategy_version=self._active_sizing_strategy_version,
        )
        revalidated_risk = self._risk_engine.evaluate(revalidated_source)
        latest_risk_id = await self._repository.latest_risk_id(risk.position_size_proposal_id)
        open_position_exists = await self._repository.has_open_market_position(
            portfolio_id=risk.portfolio_id,
            market_id=risk.market_id,
        )
        price = context.latest_price
        ask = price.yes_ask if risk.direction == "yes" else price.no_ask
        bid = price.yes_bid if risk.direction == "yes" else price.no_bid
        execution_input = PaperExecutionInput(
            risk_decision_id=risk.id,
            position_size_proposal_id=risk.position_size_proposal_id,
            portfolio_id=risk.portfolio_id,
            portfolio_snapshot_id=risk.portfolio_snapshot_id,
            opportunity_id=risk.opportunity_id,
            market_id=risk.market_id,
            outcome_team_id=risk.outcome_team_id,
            market_event_match_id=context.latest_match.id,
            market_price_id=context.latest_price.id,
            base_forecast_id=context.latest_forecast.id,
            direction=risk.direction,
            runtime_trading_mode=self._runtime_trading_mode,
            risk_execution_mode=risk.execution_mode,
            risk_decision=risk.decision,
            risk_all_required_checks_passed=risk.all_required_checks_passed,
            risk_is_latest=latest_risk_id == risk.id,
            risk_policy_is_active=(
                risk.risk_policy_version == self._risk_engine.policy_version
                and risk.risk_policy_fingerprint == self._risk_engine.policy_fingerprint
            ),
            risk_revalidation_decision=revalidated_risk.decision.value,
            risk_input_fingerprint=risk.input_fingerprint,
            revalidated_risk_input_fingerprint=revalidated_risk.input_fingerprint,
            authorization_valid_until=risk.authorization_valid_until,
            no_prior_execution=True,
            no_open_market_position=not open_position_exists,
            latest_snapshot_id=context.latest_snapshot.id,
            current_available_bankroll=context.latest_snapshot.available_bankroll,
            proposed_capital=risk.proposed_capital,
            reference_price=risk.reference_price,
            current_directional_ask=ask,
            current_directional_bid=bid,
            model_probability=risk.model_probability,
            raw_edge=risk.raw_edge,
            minimum_adjusted_edge=max(
                self._risk_policy.min_raw_edge,
                context.opportunity.trade_candidate_min_raw_edge,
            ),
            attempted_at=attempted_at,
        )
        decision = self._execution_engine.evaluate(execution_input)
        trade_id = paper_trade_record_id(risk.id)
        if decision.status is PaperTradeStatus.REJECTED:
            trade = self._trade_record(
                trade_id=trade_id,
                risk=risk,
                decision=decision,
                snapshot_after_id=None,
            )
            await self._repository.persist_rejection(trade)
            return PaperExecutionResult(trade=trade, position=None, snapshot=None, created=True)

        assert decision.total_cost is not None
        assert decision.market_value is not None
        assert decision.unrealized_pnl is not None
        latest = context.latest_snapshot
        snapshot = PortfolioSnapshot(
            id=portfolio_snapshot_record_id(risk.portfolio_id, latest.sequence + 1),
            portfolio_id=risk.portfolio_id,
            sequence=latest.sequence + 1,
            mode=PortfolioMode.PAPER,
            currency=latest.currency,
            starting_bankroll=latest.starting_bankroll,
            current_bankroll=latest.current_bankroll,
            cash_balance=latest.cash_balance - decision.total_cost,
            reserved_capital=latest.reserved_capital,
            committed_capital=latest.committed_capital + decision.total_cost,
            available_bankroll=latest.available_bankroll - decision.total_cost,
            realized_pnl=latest.realized_pnl,
            open_position_value=latest.open_position_value + decision.market_value,
            unrealized_pnl=latest.unrealized_pnl + decision.unrealized_pnl,
            total_portfolio_value=(
                latest.cash_balance
                - decision.total_cost
                + latest.open_position_value
                + decision.market_value
            ),
            previous_snapshot_id=latest.id,
            reason=PortfolioSnapshotReason.PAPER_ENTRY_FILLED,
            state_fingerprint="0" * 64,
            captured_at=attempted_at,
        )
        snapshot = snapshot.model_copy(
            update={"state_fingerprint": portfolio_state_fingerprint(snapshot)}
        )
        snapshot_record = self._snapshot_record(snapshot)
        trade = self._trade_record(
            trade_id=trade_id,
            risk=risk,
            decision=decision,
            snapshot_after_id=snapshot.id,
        )
        position = self._position_record(
            position_id=paper_position_record_id(trade_id),
            trade_id=trade_id,
            risk=risk,
            decision=decision,
        )
        await self._repository.persist_fill(
            snapshot=snapshot_record,
            trade=trade,
            position=position,
        )
        return PaperExecutionResult(
            trade=trade,
            position=position,
            snapshot=snapshot_record,
            created=True,
        )

    async def _replay(self, trade: PaperTradeRecord) -> PaperExecutionResult:
        position = await self._repository.get_position_for_trade(trade.id)
        snapshot = (
            await self._repository.get_snapshot(trade.portfolio_snapshot_after_id)
            if trade.portfolio_snapshot_after_id is not None
            else None
        )
        return PaperExecutionResult(
            trade=trade,
            position=position,
            snapshot=snapshot,
            created=False,
        )

    def _trade_record(
        self,
        *,
        trade_id: UUID,
        risk: RiskDecisionRecord,
        decision: PaperExecutionDecision,
        snapshot_after_id: UUID | None,
    ) -> PaperTradeRecord:
        return PaperTradeRecord(
            id=trade_id,
            risk_decision_id=risk.id,
            position_size_proposal_id=risk.position_size_proposal_id,
            portfolio_id=risk.portfolio_id,
            portfolio_snapshot_before_id=risk.portfolio_snapshot_id,
            portfolio_snapshot_after_id=snapshot_after_id,
            opportunity_id=risk.opportunity_id,
            market_id=risk.market_id,
            outcome_team_id=risk.outcome_team_id,
            market_event_match_id=risk.market_event_match_id,
            market_price_id=risk.market_price_id,
            base_forecast_id=risk.base_forecast_id,
            execution_mode="paper",
            action="buy",
            direction=risk.direction,
            status=decision.status.value,
            reason_code=decision.reason_code,
            reason=decision.reason,
            failed_rules=list(decision.failed_rules),
            check_results=[item.model_dump(mode="json") for item in decision.checks],
            proposed_capital=decision.requested_capital,
            reference_price=decision.reference_price,
            execution_price=decision.execution_price,
            slippage_bps=self._execution_policy.slippage_bps,
            slippage_amount_per_contract=decision.slippage_amount_per_contract,
            requested_quantity=decision.requested_quantity,
            executed_quantity=decision.executed_quantity,
            reference_gross_cost=decision.reference_gross_cost,
            gross_cost=decision.gross_cost,
            slippage_cost=decision.slippage_cost,
            fee_bps=self._execution_policy.fee_bps,
            fee_amount=decision.fee_amount,
            total_cost=decision.total_cost,
            unused_capital=decision.unused_capital,
            effective_unit_cost=decision.effective_unit_cost,
            model_probability=risk.model_probability,
            raw_edge=risk.raw_edge,
            adjusted_edge=decision.adjusted_edge,
            mark_price=decision.mark_price,
            mark_basis=decision.mark_basis.value if decision.mark_basis is not None else None,
            market_value=decision.market_value,
            unrealized_pnl=decision.unrealized_pnl,
            sizing_strategy_version=risk.proposal_strategy_version,
            risk_policy_version=risk.risk_policy_version,
            execution_policy_name=decision.execution_policy_name,
            execution_policy_version=decision.execution_policy_version,
            execution_policy_fingerprint=decision.execution_policy_fingerprint,
            risk_input_fingerprint=risk.input_fingerprint,
            input_fingerprint=decision.input_fingerprint,
            attempted_at=decision.attempted_at,
            executed_at=(
                decision.attempted_at if decision.status is PaperTradeStatus.FILLED else None
            ),
            audit_snapshot=decision.audit_snapshot,
        )

    @staticmethod
    def _position_record(
        *,
        position_id: UUID,
        trade_id: UUID,
        risk: RiskDecisionRecord,
        decision: PaperExecutionDecision,
    ) -> PaperPositionRecord:
        assert decision.executed_quantity is not None
        assert decision.execution_price is not None
        assert decision.gross_cost is not None
        assert decision.fee_amount is not None
        assert decision.total_cost is not None
        assert decision.mark_price is not None
        assert decision.mark_basis is not None
        assert decision.market_value is not None
        assert decision.unrealized_pnl is not None
        return PaperPositionRecord(
            id=position_id,
            opening_trade_id=trade_id,
            portfolio_id=risk.portfolio_id,
            market_id=risk.market_id,
            outcome_team_id=risk.outcome_team_id,
            market_price_id=risk.market_price_id,
            execution_mode="paper",
            direction=risk.direction,
            status="open",
            quantity=decision.executed_quantity,
            average_entry_price=decision.execution_price,
            gross_cost_basis=decision.gross_cost,
            entry_fees=decision.fee_amount,
            total_cost_basis=decision.total_cost,
            mark_price=decision.mark_price,
            mark_basis=decision.mark_basis.value,
            market_value=decision.market_value,
            unrealized_pnl=decision.unrealized_pnl,
            realized_pnl=Decimal("0.00"),
            input_fingerprint=decision.input_fingerprint,
            opened_at=decision.attempted_at,
            updated_at=decision.attempted_at,
        )

    @staticmethod
    def _snapshot_record(snapshot: PortfolioSnapshot) -> PortfolioSnapshotRecord:
        values = snapshot.model_dump(mode="python")
        values["execution_mode"] = snapshot.mode.value
        values["reason"] = snapshot.reason.value
        del values["mode"]
        return PortfolioSnapshotRecord(**values)
