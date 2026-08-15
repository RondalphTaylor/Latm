from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.risk import RiskEvaluationInput, RiskPolicy
from app.services.position_sizing.repository import CurrentOpportunityContext
from app.services.position_sizing.service import opportunity_semantic_skip_reason
from app.services.risk.engine import DeterministicRiskEngine
from app.services.risk.repository import RiskEvaluationContext, RiskRepository


class RiskRunResult(BaseModel):
    """Audit summary for one bounded deterministic risk run."""

    model_config = ConfigDict(frozen=True)

    risk_policy_name: str
    risk_policy_version: str
    examined: int = Field(ge=0)
    generated: int = Field(ge=0)
    persisted: int = Field(ge=0)
    decision_counts: dict[str, int]


class RiskService:
    """Revalidate proposals and persist risk-only authorization evidence."""

    def __init__(
        self,
        *,
        repository: RiskRepository,
        policy: RiskPolicy,
        runtime_trading_mode: str,
        active_sizing_strategy_version: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._policy = policy
        self._engine = DeterministicRiskEngine(policy)
        self._runtime_trading_mode = runtime_trading_mode
        self._active_sizing_strategy_version = active_sizing_strategy_version
        self._clock = clock or (lambda: datetime.now(UTC))

    async def run(
        self,
        *,
        proposal_id: UUID | None,
        portfolio_id: UUID | None,
        limit: int,
        offset: int,
    ) -> RiskRunResult:
        """Evaluate every selected proposal, including stale proposals, fail closed."""
        evaluated_at = self._clock()
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise ValueError("risk clock must return a timezone-aware datetime")
        proposal_ids = await self._repository.list_proposal_ids(
            proposal_id=proposal_id,
            portfolio_id=portfolio_id,
            limit=limit,
            offset=offset,
        )
        if proposal_id is not None and not proposal_ids:
            raise LookupError("position-size proposal not found")
        if (
            portfolio_id is not None
            and not proposal_ids
            and not await self._repository.portfolio_exists(portfolio_id)
        ):
            raise LookupError("portfolio not found")
        counts: Counter[str] = Counter()
        persisted = 0
        for selected_proposal_id in proposal_ids:
            context = await self._repository.get_evaluation_context(
                proposal_id=selected_proposal_id,
                as_of=evaluated_at,
            )
            if context is None:
                raise RuntimeError("selected proposal disappeared before risk evaluation")
            snapshot_before = self._snapshot_state(context)
            source = self._evaluation_input(context, evaluated_at)
            decision = self._engine.evaluate(source)
            result = await self._repository.persist_decision(decision, context)
            counts[decision.decision.value] += 1
            persisted += int(result.created)
            snapshot_after = await self._repository.get_latest_snapshot(context.portfolio.id)
            if (
                snapshot_after is None
                or self._snapshot_record_state(snapshot_after) != snapshot_before
            ):
                raise RuntimeError("risk evaluation mutated the paper portfolio balance")
        return RiskRunResult(
            risk_policy_name=self._policy.policy_name,
            risk_policy_version=self._engine.policy_version,
            examined=len(proposal_ids),
            generated=len(proposal_ids),
            persisted=persisted,
            decision_counts=dict(sorted(counts.items())),
        )

    def _evaluation_input(
        self,
        context: RiskEvaluationContext,
        evaluated_at: datetime,
    ) -> RiskEvaluationInput:
        proposal = context.proposal
        opportunity = context.opportunity
        latest_snapshot = context.latest_snapshot
        semantic_context = CurrentOpportunityContext(
            opportunity=opportunity,
            market=context.market,
            event=context.event,
            forecast=context.source_forecast,
        )
        return RiskEvaluationInput(
            proposal_id=proposal.id,
            portfolio_id=proposal.portfolio_id,
            proposal_snapshot_id=proposal.portfolio_snapshot_id,
            latest_snapshot_id=latest_snapshot.id,
            opportunity_id=proposal.opportunity_id,
            market_id=proposal.market_id,
            outcome_team_id=proposal.outcome_team_id,
            direction=proposal.direction,
            runtime_trading_mode=self._runtime_trading_mode,
            proposal_execution_mode=proposal.execution_mode,
            proposal_state=proposal.state,
            confidence_basis=proposal.confidence_basis,
            portfolio_execution_mode=context.portfolio.execution_mode,
            portfolio_status=context.portfolio.status,
            portfolio_is_active=context.portfolio.is_active,
            proposal_strategy_name=proposal.strategy_name,
            proposal_strategy_version=proposal.strategy_version,
            active_sizing_strategy_version=self._active_sizing_strategy_version,
            proposal_input_fingerprint=proposal.input_fingerprint,
            opportunity_input_fingerprint=opportunity.input_fingerprint,
            proposal_source_is_consistent=self._proposal_source_is_consistent(context),
            opportunity_is_current=context.opportunity_is_current,
            opportunity_semantics_are_current=(
                opportunity_semantic_skip_reason(semantic_context) is None
            ),
            opportunity_status=opportunity.status,
            opportunity_trade_candidate_min_raw_edge=(opportunity.trade_candidate_min_raw_edge),
            opportunity_valid_until=opportunity.valid_until,
            snapshot_state_fingerprint=latest_snapshot.state_fingerprint,
            snapshot_starting_bankroll=latest_snapshot.starting_bankroll,
            snapshot_current_bankroll=latest_snapshot.current_bankroll,
            snapshot_cash_balance=latest_snapshot.cash_balance,
            snapshot_reserved_capital=latest_snapshot.reserved_capital,
            snapshot_committed_capital=latest_snapshot.committed_capital,
            snapshot_available_bankroll=latest_snapshot.available_bankroll,
            snapshot_realized_pnl=latest_snapshot.realized_pnl,
            proposal_available_bankroll=proposal.available_bankroll,
            proposed_capital=proposal.proposed_capital,
            proposed_exposure_fraction=proposal.proposed_exposure_fraction,
            current_authorized_capital=context.current_authorized_capital,
            duplicate_active_intent_exists=(context.duplicate_active_intent_exists),
            reference_price=proposal.reference_price,
            model_probability=proposal.model_probability,
            raw_edge=proposal.raw_edge,
            market_status=context.market.status,
            market_close_time=context.market.close_time,
            event_status=context.event.status,
            event_postponed=context.event.postponed,
            event_start_time=context.event.scheduled_start_time,
            source_match_id=context.source_match.id,
            latest_match_id=context.latest_match.id,
            latest_match_status=context.latest_match.status,
            latest_match_eligible=context.latest_match.automatic_trading_eligible,
            latest_match_confidence=context.latest_match.confidence,
            source_market_price_id=context.source_price.id,
            latest_market_price_id=context.latest_price.id,
            market_price_retrieved_at=context.source_price.retrieved_at,
            source_forecast_id=context.source_forecast.id,
            latest_operational_forecast_id=context.latest_forecast.id,
            forecast_generated_at=context.source_forecast.generated_at,
            evaluated_at=evaluated_at,
        )

    @staticmethod
    def _proposal_source_is_consistent(context: RiskEvaluationContext) -> bool:
        proposal = context.proposal
        opportunity = context.opportunity
        return (
            proposal.portfolio_id == context.proposal_snapshot.portfolio_id
            and proposal.opportunity_id == opportunity.id
            and proposal.market_id == opportunity.market_id
            and proposal.outcome_team_id == opportunity.outcome_team_id
            and proposal.direction == opportunity.direction
            and proposal.reference_price == opportunity.market_probability
            and proposal.model_probability == opportunity.model_probability
            and proposal.raw_edge == opportunity.raw_edge
            and proposal.opportunity_strategy_name == opportunity.strategy_name
            and proposal.opportunity_strategy_version == opportunity.strategy_version
            and proposal.opportunity_input_fingerprint == opportunity.input_fingerprint
            and proposal.opportunity_evaluated_at == opportunity.evaluated_at
            and proposal.opportunity_valid_until == opportunity.valid_until
        )

    @staticmethod
    def _snapshot_state(context: RiskEvaluationContext) -> tuple[object, ...]:
        return RiskService._snapshot_record_state(context.latest_snapshot)

    @staticmethod
    def _snapshot_record_state(record: object) -> tuple[object, ...]:
        required = (
            "id",
            "portfolio_id",
            "sequence",
            "state_fingerprint",
            "starting_bankroll",
            "current_bankroll",
            "cash_balance",
            "reserved_capital",
            "committed_capital",
            "available_bankroll",
            "realized_pnl",
        )
        return tuple(getattr(record, field) for field in required)
