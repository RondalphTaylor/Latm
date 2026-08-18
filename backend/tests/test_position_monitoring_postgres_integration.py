from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.domain.execution import PaperExecutionPolicy
from app.domain.portfolio import PositionSizingPolicy
from app.domain.position_monitoring import PositionMonitoringPolicy
from app.domain.risk import RiskDecisionType, RiskPolicy
from app.models.execution import PaperPositionRecord, PositionEventRecord
from app.models.forecasts import BaseForecastRecord
from app.models.markets import MarketResolutionRecord, PredictionMarketRecord
from app.models.portfolio import PortfolioSnapshotRecord
from app.models.sports import SportsEventRecord
from app.services.execution.repository import PaperExecutionRepository
from app.services.execution.service import PaperExecutionService
from app.services.opportunities.repository import OpportunityRepository
from app.services.opportunities.service import OpportunityDetectionService
from app.services.position_monitoring.repository import PositionMonitoringRepository
from app.services.position_monitoring.service import PositionMonitoringService
from app.services.position_sizing.engine import RulesPositionSizer
from app.services.position_sizing.repository import PositionSizingRepository
from app.services.position_sizing.service import PaperPortfolioService, PositionSizingService
from app.services.risk.repository import RiskRepository
from app.services.risk.service import RiskService
from tests.test_position_sizing_postgres_integration import (
    EVENT_ID,
    FORECAST_ID,
    MARKET_ID,
    NOW,
    _price,
    _seed_sources,
)

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION_TESTS") != "1",
    reason="set RUN_DATABASE_INTEGRATION_TESTS=1 against a migrated test database",
)

MONITOR_PRICE_ID = UUID("aa000000-0000-0000-0000-000000000001")
MONITOR_FORECAST_ID = UUID("aa000000-0000-0000-0000-000000000002")
RESOLUTION_ID = UUID("aa000000-0000-0000-0000-000000000003")


async def _open_phase8_position(session: AsyncSession) -> PaperPositionRecord:
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
    opportunity = next(item for item in opportunities if item.status == "trade_candidate")

    portfolio_repository = PositionSizingRepository(session)
    bundle, _ = await PaperPortfolioService(
        repository=portfolio_repository,
        default_starting_bankroll=Decimal("1000.00"),
        clock=lambda: NOW,
    ).create(
        idempotency_key="phase9-integration-portfolio",
        name="Phase 9 Integration Portfolio",
        starting_bankroll=None,
    )
    sizing_version = RulesPositionSizer(PositionSizingPolicy()).strategy_version
    await PositionSizingService(
        repository=portfolio_repository,
        clock=lambda: NOW,
    ).run(
        portfolio_id=bundle.portfolio.id,
        opportunity_id=opportunity.id,
        limit=1,
        offset=0,
    )
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
    await RiskService(
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
    approval = (
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
    execution = await PaperExecutionService(
        repository=PaperExecutionRepository(session),
        risk_policy=RiskPolicy(),
        execution_policy=PaperExecutionPolicy(),
        runtime_trading_mode="paper",
        active_sizing_strategy_version=sizing_version,
        clock=lambda: NOW + timedelta(seconds=30),
    ).execute(approval.id)
    assert execution.position is not None
    return execution.position


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
                position = await _open_phase8_position(session)
                repository = PositionMonitoringRepository(session)
                monitor_now = await repository.database_time()

                event = await session.get(SportsEventRecord, EVENT_ID)
                market = await session.get(PredictionMarketRecord, MARKET_ID)
                opening_forecast = await session.get(BaseForecastRecord, FORECAST_ID)
                assert event is not None and market is not None and opening_forecast is not None
                event.scheduled_start_time = monitor_now + timedelta(hours=2)
                event.status = "scheduled"
                event.postponed = False
                market.status = "active"
                session.add(_price(MONITOR_PRICE_ID, monitor_now, "0.62"))
                values = {
                    column.name: getattr(opening_forecast, column.name)
                    for column in BaseForecastRecord.__table__.columns
                }
                values.update(
                    {
                        "id": MONITOR_FORECAST_ID,
                        "home_win_probability": Decimal("0.620000"),
                        "away_win_probability": Decimal("0.380000"),
                        "input_fingerprint": "9" * 64,
                        "forecast_as_of": monitor_now,
                        "generated_at": monitor_now,
                    }
                )
                session.add(BaseForecastRecord(**values))
                await session.commit()

                monitoring = PositionMonitoringService(
                    repository=repository,
                    policy=PositionMonitoringPolicy(),
                    runtime_trading_mode="paper",
                )
                reduced = await monitoring.evaluate(position.id)
                replay = await monitoring.evaluate(position.id)
                assert reduced.created is True
                assert replay.created is False
                assert reduced.event.decision == "reduce"
                assert reduced.position.quantity == 18
                assert reduced.position.realized_pnl == Decimal("0.78")
                assert reduced.snapshot is not None
                assert reduced.snapshot.sequence == 2
                assert reduced.snapshot.cash_balance == Decimal("990.82")

                resolution_time = await repository.database_time()
                market = await session.get(PredictionMarketRecord, MARKET_ID)
                assert market is not None
                market.status = "finalized"
                session.add(
                    MarketResolutionRecord(
                        id=RESOLUTION_ID,
                        market_id=MARKET_ID,
                        result="yes",
                        yes_payout=Decimal("1.000000"),
                        no_payout=Decimal("0.000000"),
                        resolution_type="standard_binary",
                        source="official_provider",
                        settled_at=resolution_time,
                        retrieved_at=resolution_time,
                        input_fingerprint="8" * 64,
                        source_snapshot={"provider_result": "yes"},
                    )
                )
                await session.commit()

                settled = await monitoring.evaluate(position.id)
                settled_replay = await monitoring.evaluate(position.id)
                assert settled.event.decision == "settle"
                assert settled.position.status == "settled"
                assert settled.position.realized_pnl == Decimal("8.82")
                assert settled.snapshot is not None
                assert settled.snapshot.sequence == 3
                assert settled.snapshot.current_bankroll == Decimal("1008.82")
                assert settled.snapshot.cash_balance == Decimal("1008.82")
                assert settled.snapshot.committed_capital == Decimal("0.00")
                assert settled_replay.created is False
                assert settled_replay.event.id == settled.event.id

                assert (
                    await session.scalar(select(func.count()).select_from(PositionEventRecord)) == 2
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(PortfolioSnapshotRecord)
                        .where(PortfolioSnapshotRecord.portfolio_id == position.portfolio_id)
                    )
                    == 4
                )
        finally:
            await outer_transaction.rollback()
    await engine.dispose()


def test_postgres_phase8_entry_then_reduce_and_official_settlement() -> None:
    asyncio.run(_run_integration())
