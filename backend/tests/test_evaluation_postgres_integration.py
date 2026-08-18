from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.domain.forecasts import ForecastPurpose
from app.domain.portfolio import PortfolioMode, PortfolioSnapshot, PortfolioSnapshotReason
from app.models.evaluation import ForecastEvaluationRecord
from app.models.forecasts import BaseForecastRecord, ModelVersionRecord
from app.models.markets import Provider
from app.models.portfolio import PortfolioRecord, PortfolioSnapshotRecord
from app.models.sports import SportsEventRecord, TeamRecord
from app.services.evaluation.repository import EvaluationRepository
from app.services.evaluation.service import (
    ForecastEvaluationService,
    TradingPerformanceService,
)
from app.services.position_sizing.repository import portfolio_state_fingerprint

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION_TESTS") != "1",
    reason="set RUN_DATABASE_INTEGRATION_TESTS=1 against a migrated test database",
)

HOME_ID = UUID("b1000000-0000-0000-0000-000000000001")
AWAY_ID = UUID("b1000000-0000-0000-0000-000000000002")
EVENT_ID = UUID("b1000000-0000-0000-0000-000000000003")
MODEL_ID = UUID("b1000000-0000-0000-0000-000000000004")
FORECAST_ID = UUID("b1000000-0000-0000-0000-000000000005")
PORTFOLIO_ID = UUID("b1000000-0000-0000-0000-000000000006")
SNAPSHOT_ID = UUID("b1000000-0000-0000-0000-000000000007")
TIP = datetime(2026, 8, 10, 23, tzinfo=UTC)


def _team(team_id: UUID, provider_id: str, abbreviation: str) -> TeamRecord:
    return TeamRecord(
        id=team_id,
        provider_name="balldontlie",
        provider_team_id=provider_id,
        league="nba",
        abbreviation=abbreviation,
        city=abbreviation,
        name=abbreviation,
        full_name=abbreviation,
        conference="East",
        division="Atlantic",
        raw_data={},
        first_seen_at=TIP - timedelta(days=1),
        last_seen_at=TIP - timedelta(days=1),
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
                await session.execute(
                    insert(Provider)
                    .values(
                        name="balldontlie",
                        display_name="BALLDONTLIE",
                        is_read_only=True,
                    )
                    .on_conflict_do_nothing(index_elements=[Provider.name])
                )
                session.add_all(
                    [
                        _team(HOME_ID, "phase10-home", "HOM"),
                        _team(AWAY_ID, "phase10-away", "AWY"),
                    ]
                )
                await session.flush()
                event = SportsEventRecord(
                    id=EVENT_ID,
                    provider_name="balldontlie",
                    provider_event_id="phase10-event",
                    league="nba",
                    season=2026,
                    event_date=TIP.date(),
                    scheduled_start_time=TIP,
                    status="final",
                    status_detail="Final",
                    period=4,
                    clock=None,
                    postseason=False,
                    postponed=False,
                    tournament_stage=None,
                    home_team_id=HOME_ID,
                    away_team_id=AWAY_ID,
                    home_score=110,
                    away_score=100,
                    venue=None,
                    raw_data={},
                    first_seen_at=TIP - timedelta(days=1),
                    last_seen_at=TIP + timedelta(hours=3),
                )
                model = ModelVersionRecord(
                    id=MODEL_ID,
                    model_name="nba_elo",
                    model_version="phase10-test-v1",
                    algorithm="elo",
                    configuration={},
                    configuration_fingerprint="1" * 64,
                    formula="test",
                    description="Phase 10 integration fixture",
                    created_at=TIP - timedelta(days=1),
                )
                forecast = BaseForecastRecord(
                    id=FORECAST_ID,
                    sports_event_id=EVENT_ID,
                    model_version_id=MODEL_ID,
                    purpose="operational",
                    home_team_id=HOME_ID,
                    away_team_id=AWAY_ID,
                    home_win_probability=Decimal("0.600000"),
                    away_win_probability=Decimal("0.400000"),
                    home_team_rating=Decimal("1510.0000"),
                    away_team_rating=Decimal("1490.0000"),
                    adjusted_rating_difference=Decimal("120.0000"),
                    training_data_fingerprint="2" * 64,
                    input_fingerprint="3" * 64,
                    input_features={},
                    training_games_seen=10,
                    training_games_processed=10,
                    skipped_tied_games=0,
                    skipped_incomplete_games=0,
                    home_prior_games=5,
                    away_prior_games=5,
                    latest_training_event_time=TIP - timedelta(days=2),
                    forecast_as_of=TIP - timedelta(hours=1),
                    source_event_last_seen_at=TIP - timedelta(days=1),
                    generated_at=TIP - timedelta(hours=1),
                )
                portfolio = PortfolioRecord(
                    id=PORTFOLIO_ID,
                    idempotency_key="phase10-integration",
                    name="Phase 10 Integration",
                    execution_mode="paper",
                    currency="USD",
                    starting_bankroll=Decimal("1000.00"),
                    status="active",
                    is_active=True,
                    creation_fingerprint="4" * 64,
                    created_at=TIP,
                )
                snapshot = PortfolioSnapshotRecord(
                    id=SNAPSHOT_ID,
                    portfolio_id=PORTFOLIO_ID,
                    sequence=0,
                    execution_mode="paper",
                    currency="USD",
                    starting_bankroll=Decimal("1000.00"),
                    current_bankroll=Decimal("1000.00"),
                    cash_balance=Decimal("1000.00"),
                    reserved_capital=Decimal("0.00"),
                    committed_capital=Decimal("0.00"),
                    available_bankroll=Decimal("1000.00"),
                    realized_pnl=Decimal("0.00"),
                    open_position_value=Decimal("0.00"),
                    unrealized_pnl=Decimal("0.00"),
                    total_portfolio_value=Decimal("1000.00"),
                    previous_snapshot_id=None,
                    reason="created",
                    state_fingerprint="0" * 64,
                    captured_at=TIP,
                )
                snapshot.state_fingerprint = portfolio_state_fingerprint(
                    PortfolioSnapshot(
                        id=snapshot.id,
                        portfolio_id=snapshot.portfolio_id,
                        sequence=snapshot.sequence,
                        mode=PortfolioMode.PAPER,
                        currency=snapshot.currency,
                        starting_bankroll=snapshot.starting_bankroll,
                        current_bankroll=snapshot.current_bankroll,
                        cash_balance=snapshot.cash_balance,
                        reserved_capital=snapshot.reserved_capital,
                        committed_capital=snapshot.committed_capital,
                        available_bankroll=snapshot.available_bankroll,
                        realized_pnl=snapshot.realized_pnl,
                        open_position_value=snapshot.open_position_value,
                        unrealized_pnl=snapshot.unrealized_pnl,
                        total_portfolio_value=snapshot.total_portfolio_value,
                        previous_snapshot_id=None,
                        reason=PortfolioSnapshotReason.CREATED,
                        state_fingerprint=snapshot.state_fingerprint,
                        captured_at=snapshot.captured_at,
                    )
                )
                session.add_all([event, model, portfolio])
                await session.flush()
                session.add_all([forecast, snapshot])
                await session.flush()

                repository = EvaluationRepository(session)
                service = ForecastEvaluationService(repository=repository)
                first = await service.run(
                    purpose=ForecastPurpose.OPERATIONAL,
                    start_date=TIP.date(),
                    end_date=TIP.date(),
                    event_id=EVENT_ID,
                    model_version_id=MODEL_ID,
                    limit=10,
                    offset=0,
                )
                replay = await service.run(
                    purpose=ForecastPurpose.OPERATIONAL,
                    start_date=TIP.date(),
                    end_date=TIP.date(),
                    event_id=EVENT_ID,
                    model_version_id=MODEL_ID,
                    limit=10,
                    offset=0,
                )
                assert first.persisted == 1
                assert replay.persisted == 0
                assert replay.replayed == 1

                event.home_score = 95
                event.away_score = 105
                event.last_seen_at = TIP + timedelta(hours=4)
                corrected = await service.run(
                    purpose=ForecastPurpose.OPERATIONAL,
                    start_date=TIP.date(),
                    end_date=TIP.date(),
                    event_id=EVENT_ID,
                    model_version_id=MODEL_ID,
                    limit=10,
                    offset=0,
                )
                assert corrected.persisted == 1

                event.home_score = 110
                event.away_score = 100
                event.last_seen_at = TIP + timedelta(hours=5)
                reverted = await service.run(
                    purpose=ForecastPurpose.OPERATIONAL,
                    start_date=TIP.date(),
                    end_date=TIP.date(),
                    event_id=EVENT_ID,
                    model_version_id=MODEL_ID,
                    limit=10,
                    offset=0,
                )
                assert reverted.persisted == 0
                assert reverted.replayed == 1
                assert await session.scalar(select(func.count(ForecastEvaluationRecord.id))) == 2

                performance = await service.performance(
                    purpose=ForecastPurpose.OPERATIONAL,
                    start_date=TIP.date(),
                    end_date=TIP.date(),
                    model_version_ids=(MODEL_ID,),
                )
                assert performance.evaluation_count == 1
                assert performance.unique_event_count == 1
                assert performance.models[0].summary.mean_brier_score == Decimal("0.160000000000")

                trading = await TradingPerformanceService(repository=repository).evaluate(
                    PORTFOLIO_ID
                )
                assert trading.net_total_pnl == Decimal("0.00")
                assert trading.return_on_starting_bankroll == Decimal("0E-10")
                assert trading.win_rate is None
                assert trading.maximum_drawdown.amount == Decimal("0.00")
        finally:
            await outer_transaction.rollback()
    await engine.dispose()


def test_forecast_and_trading_evaluation_postgres_pipeline() -> None:
    asyncio.run(_run_integration())
