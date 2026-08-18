from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.domain.execution import PaperExecutionPolicy
from app.domain.portfolio import PositionSizingPolicy
from app.domain.risk import RiskDecisionType, RiskPolicy
from app.models.execution import PaperPositionRecord, PaperTradeRecord
from app.models.portfolio import PortfolioSnapshotRecord
from app.services.execution.repository import PaperExecutionRepository
from app.services.execution.service import PaperExecutionService
from app.services.opportunities.repository import OpportunityRepository
from app.services.opportunities.service import OpportunityDetectionService
from app.services.position_sizing.engine import RulesPositionSizer
from app.services.position_sizing.repository import PositionSizingRepository
from app.services.position_sizing.service import PaperPortfolioService, PositionSizingService
from app.services.risk.repository import RiskRepository
from app.services.risk.service import RiskService
from tests.test_position_sizing_postgres_integration import MARKET_ID, NOW, _seed_sources

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION_TESTS") != "1",
    reason="set RUN_DATABASE_INTEGRATION_TESTS=1 against a migrated test database",
)


async def _run_integration() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.connect() as connection:
        outer_transaction = await connection.begin()
        try:
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as session:
                await _seed_sources(session)
                opportunity_repository = OpportunityRepository(session)
                await OpportunityDetectionService(
                    repository=opportunity_repository,
                    clock=lambda: NOW,
                ).run(
                    start_date=NOW.date(),
                    end_date=NOW.date(),
                    market_id=MARKET_ID,
                    limit=10,
                    offset=0,
                )
                opportunities = await opportunity_repository.list_opportunities(
                    latest_only=True,
                    current_only=True,
                    current_at=NOW,
                    status=None,
                    direction=None,
                    market_id=MARKET_ID,
                    sports_event_id=None,
                    model_name=None,
                    model_version=None,
                    opportunity_id=None,
                    limit=10,
                    offset=0,
                )
                opportunity = next(
                    item for item in opportunities if item.status == "trade_candidate"
                )

                portfolio_repository = PositionSizingRepository(session)
                bundle, _ = await PaperPortfolioService(
                    repository=portfolio_repository,
                    default_starting_bankroll=Decimal("1000.00"),
                    clock=lambda: NOW,
                ).create(
                    idempotency_key="phase8-integration-portfolio",
                    name="Phase 8 Integration Portfolio",
                    starting_bankroll=None,
                )
                sizing_version = RulesPositionSizer(PositionSizingPolicy()).strategy_version
                sizing = await PositionSizingService(
                    repository=portfolio_repository,
                    clock=lambda: NOW,
                ).run(
                    portfolio_id=bundle.portfolio.id,
                    opportunity_id=opportunity.id,
                    limit=10,
                    offset=0,
                )
                assert sizing.persisted == 1
                proposal = (
                    await portfolio_repository.list_proposals(
                        portfolio_id=bundle.portfolio.id,
                        opportunity_id=opportunity.id,
                        market_id=None,
                        direction=None,
                        strategy_version=None,
                        limit=1,
                        offset=0,
                    )
                )[0]
                risk_repository = RiskRepository(session)
                risk_run = await RiskService(
                    repository=risk_repository,
                    policy=RiskPolicy(),
                    runtime_trading_mode="paper",
                    active_sizing_strategy_version=sizing_version,
                    clock=lambda: NOW,
                ).run(
                    proposal_id=proposal.id,
                    portfolio_id=None,
                    limit=1,
                    offset=0,
                )
                assert risk_run.decision_counts == {"auto_approve": 1}
                approved = (
                    await risk_repository.list_decisions(
                        latest_only=True,
                        unexpired_only=True,
                        current_at=NOW,
                        proposal_id=proposal.id,
                        portfolio_id=None,
                        market_id=None,
                        decision=RiskDecisionType.AUTO_APPROVE,
                        risk_policy_version=None,
                        limit=1,
                        offset=0,
                    )
                )[0]

                execution_service = PaperExecutionService(
                    repository=PaperExecutionRepository(session),
                    risk_policy=RiskPolicy(),
                    execution_policy=PaperExecutionPolicy(),
                    runtime_trading_mode="paper",
                    active_sizing_strategy_version=sizing_version,
                    clock=lambda: NOW + timedelta(seconds=30),
                )
                first = await execution_service.execute(approved.id)
                replay = await execution_service.execute(approved.id)

                assert first.created is True
                assert replay.created is False
                assert first.trade.id == replay.trade.id
                assert first.trade.status == "filled"
                assert first.trade.execution_mode == "paper"
                assert first.trade.total_cost == Decimal("19.91")
                assert first.position is not None
                assert first.position.quantity == 36
                assert first.position.unrealized_pnl == Decimal("-0.83")
                assert first.snapshot is not None
                assert first.snapshot.sequence == 1
                assert first.snapshot.cash_balance == Decimal("980.09")
                assert first.snapshot.committed_capital == Decimal("19.91")
                assert first.snapshot.available_bankroll == Decimal("980.09")
                assert first.snapshot.current_bankroll == Decimal("1000.00")
                assert first.snapshot.open_position_value == Decimal("19.08")
                assert first.snapshot.unrealized_pnl == Decimal("-0.83")
                assert first.snapshot.total_portfolio_value == Decimal("999.17")

                assert await session.scalar(select(func.count()).select_from(PaperTradeRecord)) == 1
                assert (
                    await session.scalar(select(func.count()).select_from(PaperPositionRecord)) == 1
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(PortfolioSnapshotRecord)
                        .where(PortfolioSnapshotRecord.portfolio_id == bundle.portfolio.id)
                    )
                    == 2
                )

                # The open-position gate is shared with Phase 7, not only execution.
                second_sizing = await PositionSizingService(
                    repository=portfolio_repository,
                    clock=lambda: NOW + timedelta(seconds=40),
                ).run(
                    portfolio_id=bundle.portfolio.id,
                    opportunity_id=opportunity.id,
                    limit=1,
                    offset=0,
                )
                assert second_sizing.persisted == 1
                new_proposal = (
                    await portfolio_repository.list_proposals(
                        portfolio_id=bundle.portfolio.id,
                        opportunity_id=opportunity.id,
                        market_id=None,
                        direction=None,
                        strategy_version=None,
                        limit=2,
                        offset=0,
                    )
                )[0]
                second_risk = await RiskService(
                    repository=risk_repository,
                    policy=RiskPolicy(),
                    runtime_trading_mode="paper",
                    active_sizing_strategy_version=sizing_version,
                    clock=lambda: NOW + timedelta(seconds=40),
                ).run(
                    proposal_id=new_proposal.id,
                    portfolio_id=None,
                    limit=1,
                    offset=0,
                )
                assert second_risk.decision_counts == {"reject": 1}
                rejected = (
                    await risk_repository.list_decisions(
                        latest_only=True,
                        unexpired_only=False,
                        current_at=NOW + timedelta(seconds=40),
                        proposal_id=new_proposal.id,
                        portfolio_id=None,
                        market_id=None,
                        decision=RiskDecisionType.REJECT,
                        risk_policy_version=None,
                        limit=1,
                        offset=0,
                    )
                )[0]
                assert "duplicate_active_intent_absent" in rejected.failed_rules
        finally:
            await outer_transaction.rollback()
    await engine.dispose()


def test_postgres_phase5_through_phase8_atomic_paper_entry() -> None:
    asyncio.run(_run_integration())
