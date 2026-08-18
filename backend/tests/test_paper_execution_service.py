from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest

from app.domain.execution import PaperExecutionPolicy
from app.domain.portfolio import PositionSizingPolicy
from app.domain.risk import RiskPolicy
from app.models.execution import PaperPositionRecord, PaperTradeRecord
from app.models.portfolio import PortfolioSnapshotRecord
from app.models.risk import RiskDecisionRecord
from app.services.execution.repository import PaperExecutionRepository
from app.services.execution.service import PaperExecutionConflictError, PaperExecutionService
from app.services.position_sizing.engine import RulesPositionSizer
from app.services.risk.repository import RiskEvaluationContext
from tests.test_risk_api import decision_record
from tests.test_risk_service import NOW, risk_context


class FakeExecutionRepository:
    def __init__(self) -> None:
        self.risk = decision_record()
        self.context = risk_context()
        self.context.latest_snapshot.open_position_value = Decimal("0.00")
        self.context.latest_snapshot.unrealized_pnl = Decimal("0.00")
        self.context.latest_snapshot.total_portfolio_value = Decimal("1000.00")
        self.context.latest_snapshot.previous_snapshot_id = None
        self.trade: PaperTradeRecord | None = None
        self.position: PaperPositionRecord | None = None
        self.snapshot: PortfolioSnapshotRecord | None = None
        self.fill_count = 0
        self.rejection_count = 0
        self.open_position = False

    async def get_trade_for_risk(self, _: UUID) -> PaperTradeRecord | None:
        return self.trade

    async def get_risk_decision(self, decision_id: UUID) -> RiskDecisionRecord | None:
        return self.risk if decision_id == self.risk.id else None

    async def lock_portfolio(self, _: UUID) -> object:
        return self.context.portfolio

    async def lock_execution_parents(self, **_: object) -> None:
        return None

    async def lock_risk_decision(self, _: UUID) -> RiskDecisionRecord:
        return self.risk

    async def get_risk_context(self, **_: object) -> RiskEvaluationContext:
        return self.context

    async def latest_risk_id(self, _: UUID) -> UUID:
        return self.risk.id

    async def has_open_market_position(self, **_: object) -> bool:
        return self.open_position

    async def persist_rejection(self, trade: PaperTradeRecord) -> None:
        self.trade = trade
        self.rejection_count += 1

    async def persist_fill(
        self,
        *,
        snapshot: PortfolioSnapshotRecord,
        trade: PaperTradeRecord,
        position: PaperPositionRecord,
    ) -> None:
        self.snapshot = snapshot
        self.trade = trade
        self.position = position
        self.fill_count += 1

    async def get_position_for_trade(self, _: UUID) -> PaperPositionRecord | None:
        return self.position

    async def get_snapshot(self, _: UUID) -> PortfolioSnapshotRecord | None:
        return self.snapshot


def service(repository: FakeExecutionRepository) -> PaperExecutionService:
    sizing_version = RulesPositionSizer(PositionSizingPolicy()).strategy_version
    return PaperExecutionService(
        repository=cast(PaperExecutionRepository, repository),
        risk_policy=RiskPolicy(),
        execution_policy=PaperExecutionPolicy(),
        runtime_trading_mode="paper",
        active_sizing_strategy_version=sizing_version,
        clock=lambda: NOW + timedelta(seconds=30),
    )


def test_happy_fill_updates_balances_and_replay_is_idempotent() -> None:
    repository = FakeExecutionRepository()
    execution = service(repository)

    created = asyncio.run(execution.execute(repository.risk.id))

    assert created.created is True
    assert created.trade.status == "filled"
    assert created.position is not None
    assert created.snapshot is not None
    assert created.trade.total_cost == created.position.total_cost_basis
    assert created.snapshot.sequence == 1
    assert created.snapshot.previous_snapshot_id == repository.context.latest_snapshot.id
    assert created.snapshot.cash_balance == (
        repository.context.latest_snapshot.cash_balance - created.trade.total_cost
    )
    assert created.snapshot.committed_capital == created.trade.total_cost
    assert created.snapshot.available_bankroll == created.snapshot.cash_balance
    assert created.snapshot.current_bankroll == Decimal("1000.00")
    assert created.snapshot.open_position_value == created.position.market_value
    assert created.snapshot.unrealized_pnl == created.position.unrealized_pnl
    assert created.snapshot.total_portfolio_value == (
        created.snapshot.current_bankroll + created.snapshot.unrealized_pnl
    )
    assert repository.fill_count == 1

    replay = asyncio.run(execution.execute(repository.risk.id))
    assert replay.created is False
    assert replay.trade.id == created.trade.id
    assert repository.fill_count == 1


def test_open_market_position_consumes_approval_as_audited_rejection() -> None:
    repository = FakeExecutionRepository()
    repository.open_position = True

    result = asyncio.run(service(repository).execute(repository.risk.id))

    assert result.trade.status == "rejected"
    assert "no_open_market_position" in result.trade.failed_rules
    assert result.position is None
    assert result.snapshot is None
    assert repository.rejection_count == 1
    assert repository.fill_count == 0


def test_reject_or_human_risk_decision_never_reaches_execution() -> None:
    repository = FakeExecutionRepository()
    repository.risk.decision = "require_human_approval"

    with pytest.raises(PaperExecutionConflictError):
        asyncio.run(service(repository).execute(repository.risk.id))

    assert repository.fill_count == repository.rejection_count == 0


def test_unknown_risk_decision_is_not_found() -> None:
    repository = FakeExecutionRepository()

    with pytest.raises(LookupError):
        asyncio.run(service(repository).execute(UUID(int=0)))
