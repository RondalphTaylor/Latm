from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest

from app.domain.portfolio import PortfolioSnapshot, PositionSizingInput, PositionSizingPolicy
from app.domain.risk import RiskDecision, RiskDecisionType, RiskPolicy
from app.models.portfolio import PositionSizeProposalRecord
from app.models.risk import RiskDecisionRecord
from app.services.position_sizing.engine import RulesPositionSizer
from app.services.risk.repository import (
    RiskEvaluationContext,
    RiskPersistResult,
    RiskRepository,
    risk_decision_record_id,
)
from app.services.risk.service import RiskService
from tests.test_opportunity_service import source_bundle
from tests.test_position_sizing_service import opportunity_context, portfolio_bundle

NOW = datetime(2026, 8, 11, 12, 2, tzinfo=UTC)


def risk_context() -> RiskEvaluationContext:
    portfolio = portfolio_bundle()
    current = opportunity_context()
    snapshot = portfolio.snapshot
    domain_snapshot = PortfolioSnapshot(
        id=snapshot.id,
        portfolio_id=snapshot.portfolio_id,
        sequence=snapshot.sequence,
        starting_bankroll=snapshot.starting_bankroll,
        current_bankroll=snapshot.current_bankroll,
        cash_balance=snapshot.cash_balance,
        reserved_capital=snapshot.reserved_capital,
        committed_capital=snapshot.committed_capital,
        available_bankroll=snapshot.available_bankroll,
        realized_pnl=snapshot.realized_pnl,
        open_position_value=getattr(snapshot, "open_position_value", None) or Decimal("0.00"),
        unrealized_pnl=getattr(snapshot, "unrealized_pnl", None) or Decimal("0.00"),
        total_portfolio_value=getattr(snapshot, "total_portfolio_value", None)
        or snapshot.current_bankroll,
        reason=snapshot.reason,
        state_fingerprint=snapshot.state_fingerprint,
        captured_at=snapshot.captured_at,
    )
    proposal = (
        RulesPositionSizer(PositionSizingPolicy())
        .evaluate(
            PositionSizingInput(
                portfolio_snapshot_id=snapshot.id,
                portfolio=domain_snapshot,
                opportunity_id=current.opportunity.id,
                market_id=current.opportunity.market_id,
                outcome_team_id=current.opportunity.outcome_team_id,
                direction=current.opportunity.direction,
                reference_price=current.opportunity.market_probability,
                model_probability=current.opportunity.model_probability,
                raw_edge=current.opportunity.raw_edge,
                opportunity_status=current.opportunity.status,
                opportunity_strategy_name=current.opportunity.strategy_name,
                opportunity_strategy_version=current.opportunity.strategy_version,
                opportunity_input_fingerprint=current.opportunity.input_fingerprint,
                opportunity_evaluated_at=current.opportunity.evaluated_at,
                opportunity_valid_until=current.opportunity.valid_until,
                proposed_at=NOW,
                source_snapshot=current.opportunity.source_snapshot,
            )
        )
        .proposal
    )
    assert proposal is not None
    values = proposal.model_dump(mode="python")
    values["execution_mode"] = proposal.mode.value
    values["state"] = proposal.state.value
    values["confidence_basis"] = proposal.confidence_basis.value
    del values["mode"]
    proposal_record = PositionSizeProposalRecord(
        id=UUID("82000000-0000-0000-0000-000000000001"),
        **values,
    )
    sources = source_bundle()
    assert sources.match is not None and sources.price is not None
    sources.price.retrieved_at = NOW - timedelta(minutes=2)
    return RiskEvaluationContext(
        proposal=proposal_record,
        portfolio=portfolio.portfolio,
        proposal_snapshot=snapshot,
        latest_snapshot=snapshot,
        opportunity=current.opportunity,
        market=current.market,
        event=current.event,
        source_match=sources.match,
        latest_match=sources.match,
        source_price=sources.price,
        latest_price=sources.price,
        source_forecast=current.forecast,
        latest_forecast=current.forecast,
        opportunity_is_current=True,
        current_authorized_capital=Decimal("0.00"),
        duplicate_active_intent_exists=False,
    )


class FakeRiskRepository:
    def __init__(self, context: RiskEvaluationContext | None = None) -> None:
        self.context = context or risk_context()
        self.decisions: list[RiskDecision] = []
        self._fingerprints: set[str] = set()
        self.mutate_balance = False

    async def list_proposal_ids(self, **_: object) -> list[UUID]:
        return [self.context.proposal.id]

    async def portfolio_exists(self, portfolio_id: UUID) -> bool:
        return portfolio_id == self.context.portfolio.id

    async def get_evaluation_context(self, **_: object) -> RiskEvaluationContext:
        return self.context

    async def persist_decision(
        self,
        decision: RiskDecision,
        context: RiskEvaluationContext,
    ) -> RiskPersistResult:
        created = decision.input_fingerprint not in self._fingerprints
        self._fingerprints.add(decision.input_fingerprint)
        self.decisions.append(decision)
        return RiskPersistResult(
            record=RiskDecisionRecord(
                id=risk_decision_record_id(decision),
                **{
                    **decision.model_dump(mode="python"),
                    "decision": decision.decision.value,
                    "escalation_band": decision.escalation_band.value,
                    "failed_rules": list(decision.failed_rules),
                    "check_results": [
                        item.model_dump(mode="json") for item in decision.check_results
                    ],
                    "market_event_match_id": context.latest_match.id,
                    "market_price_id": context.latest_price.id,
                    "base_forecast_id": context.latest_forecast.id,
                },
            ),
            created=created,
        )

    async def get_latest_snapshot(self, _: UUID) -> object:
        if self.mutate_balance:
            changed = self.context.latest_snapshot
            changed.available_bankroll = Decimal("999.99")
            return changed
        return self.context.latest_snapshot


def service(repository: FakeRiskRepository) -> RiskService:
    sizer = RulesPositionSizer(PositionSizingPolicy())
    return RiskService(
        repository=cast(RiskRepository, repository),
        policy=RiskPolicy(),
        runtime_trading_mode="paper",
        active_sizing_strategy_version=sizer.strategy_version,
        clock=lambda: NOW,
    )


def test_service_auto_approves_without_mutating_or_reserving_bankroll() -> None:
    repository = FakeRiskRepository()
    before = repository.context.latest_snapshot.available_bankroll

    result = asyncio.run(
        service(repository).run(proposal_id=None, portfolio_id=None, limit=10, offset=0)
    )

    assert result.examined == result.generated == result.persisted == 1
    assert result.decision_counts == {"auto_approve": 1}
    assert repository.decisions[0].decision is RiskDecisionType.AUTO_APPROVE
    assert repository.decisions[0].authorization_valid_until is not None
    assert repository.context.latest_snapshot.available_bankroll == before
    assert repository.context.latest_snapshot.reserved_capital == Decimal("0.00")


def test_service_rejects_stale_price_and_persists_semantically_idempotently() -> None:
    repository = FakeRiskRepository()
    repository.context.source_price.retrieved_at = NOW - timedelta(minutes=16)

    first = asyncio.run(
        service(repository).run(proposal_id=None, portfolio_id=None, limit=10, offset=0)
    )
    second = asyncio.run(
        service(repository).run(proposal_id=None, portfolio_id=None, limit=10, offset=0)
    )

    assert first.decision_counts == {"reject": 1}
    assert first.persisted == 1
    assert second.persisted == 0
    assert "fresh_market_price" in repository.decisions[0].failed_rules
    assert repository.decisions[0].authorization_valid_until is None


def test_service_detects_any_portfolio_balance_mutation() -> None:
    repository = FakeRiskRepository()
    repository.mutate_balance = True

    with pytest.raises(RuntimeError, match="mutated the paper portfolio balance"):
        asyncio.run(
            service(repository).run(proposal_id=None, portfolio_id=None, limit=10, offset=0)
        )
