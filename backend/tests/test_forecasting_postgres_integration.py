from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.domain.forecasts import ForecastPurpose
from app.models.markets import PredictionMarketRecord, Provider
from app.models.matching import MarketEventMatchRecord
from app.models.sports import SportsEventRecord, TeamRecord
from app.services.forecasting.repository import ForecastRepository
from app.services.forecasting.service import BaseForecastService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION_TESTS") != "1",
    reason="set RUN_DATABASE_INTEGRATION_TESTS=1 against a migrated test database",
)

BOS_ID = UUID("0cab7d41-8b4e-4f3a-83f1-5dded2d9f431")
NYK_ID = UUID("ae4f566b-95f5-4b0e-938c-a966873d6ebd")
HISTORY_ID = UUID("ef6e508e-66b4-4b00-a43f-e231dcf3911d")
SECOND_HISTORY_ID = UUID("a1044ca7-7b87-4be3-bd89-c9601569444c")
TARGET_ID = UUID("6a6bf679-acaf-45fc-890a-8b86adad009c")
MARKET_ID = UUID("29728bb4-5b1c-47a6-b021-72d555a1b7fd")
MATCH_ID = UUID("481936a1-7390-4e4f-9d07-836854057530")
RUN_AT = datetime(2026, 8, 1, 12, tzinfo=UTC)
TARGET_TIP = datetime(2026, 8, 2, 23, tzinfo=UTC)


def team_record(team_id: UUID, provider_id: str, abbreviation: str) -> TeamRecord:
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
        first_seen_at=RUN_AT,
        last_seen_at=RUN_AT,
    )


def event_record(
    event_id: UUID,
    provider_id: str,
    start: datetime,
    *,
    status: str,
    home_score: int | None,
    away_score: int | None,
) -> SportsEventRecord:
    return SportsEventRecord(
        id=event_id,
        provider_name="balldontlie",
        provider_event_id=provider_id,
        league="nba",
        season=2025,
        event_date=start.date(),
        scheduled_start_time=start,
        status=status,
        status_detail=status,
        period=4 if status == "final" else 0,
        clock=None,
        postseason=False,
        postponed=False,
        tournament_stage=None,
        home_team_id=BOS_ID,
        away_team_id=NYK_ID,
        home_score=home_score,
        away_score=away_score,
        venue=None,
        raw_data={},
        first_seen_at=start,
        last_seen_at=start + timedelta(hours=3),
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
                        [
                            {
                                "name": "kalshi",
                                "display_name": "Kalshi",
                                "is_read_only": True,
                            },
                            {
                                "name": "balldontlie",
                                "display_name": "BALLDONTLIE",
                                "is_read_only": True,
                            },
                        ]
                    )
                    .on_conflict_do_nothing(index_elements=[Provider.name])
                )
                first_history = event_record(
                    HISTORY_ID,
                    "phase4-history-1",
                    TARGET_TIP - timedelta(days=3),
                    status="final",
                    home_score=110,
                    away_score=100,
                )
                session.add_all(
                    [
                        team_record(BOS_ID, "phase4-bos", "BOS"),
                        team_record(NYK_ID, "phase4-nyk", "NYK"),
                        first_history,
                        event_record(
                            SECOND_HISTORY_ID,
                            "phase4-history-2",
                            TARGET_TIP - timedelta(days=2),
                            status="final",
                            home_score=105,
                            away_score=108,
                        ),
                        event_record(
                            TARGET_ID,
                            "phase4-target",
                            TARGET_TIP,
                            status="scheduled",
                            home_score=None,
                            away_score=None,
                        ),
                        PredictionMarketRecord(
                            id=MARKET_ID,
                            provider_name="kalshi",
                            provider_market_id="phase4-market",
                            provider_event_id="phase4-market-event",
                            series_ticker="NBA-GAME",
                            category="Sports",
                            market_type="binary",
                            title="Will Boston win?",
                            subtitle="BOS vs NYK",
                            rules_primary=None,
                            rules_secondary=None,
                            status="open",
                            is_nba=True,
                            open_time=None,
                            close_time=TARGET_TIP + timedelta(hours=2),
                            occurrence_time=TARGET_TIP,
                            provider_created_at=None,
                            provider_updated_at=None,
                            raw_data={},
                            first_seen_at=RUN_AT,
                            last_seen_at=RUN_AT,
                        ),
                    ]
                )
                await session.flush()
                session.add(
                    MarketEventMatchRecord(
                        id=MATCH_ID,
                        market_id=MARKET_ID,
                        league="nba",
                        sports_event_id=TARGET_ID,
                        status="matched",
                        confidence=Decimal("1.0000"),
                        method="exact_team_pair_and_time",
                        reason="fixture match",
                        matcher_version="deterministic-team-time-v1",
                        min_confidence=Decimal("0.9000"),
                        ambiguity_margin=Decimal("0.1000"),
                        time_window_hours=36,
                        automatic_trading_eligible=True,
                        input_fingerprint="a" * 64,
                        team_signals=[],
                        candidate_scores=[],
                        evidence={},
                        evaluated_at=RUN_AT,
                    )
                )
                await session.commit()

                repository = ForecastRepository(session)
                service = BaseForecastService(
                    repository=repository,
                    sports_provider_name="balldontlie",
                    clock=lambda: RUN_AT,
                )
                first = await service.run(
                    purpose=ForecastPurpose.OPERATIONAL,
                    start_date=TARGET_TIP.date(),
                    end_date=TARGET_TIP.date(),
                    event_id=TARGET_ID,
                    limit=10,
                    offset=0,
                )
                identical = await service.run(
                    purpose=ForecastPurpose.OPERATIONAL,
                    start_date=TARGET_TIP.date(),
                    end_date=TARGET_TIP.date(),
                    event_id=TARGET_ID,
                    limit=10,
                    offset=0,
                )
                first_history.home_score = 90
                first_history.away_score = 120
                await session.commit()
                changed = await service.run(
                    purpose=ForecastPurpose.OPERATIONAL,
                    start_date=TARGET_TIP.date(),
                    end_date=TARGET_TIP.date(),
                    event_id=TARGET_ID,
                    limit=10,
                    offset=0,
                )
                replay = await service.run(
                    purpose=ForecastPurpose.HISTORICAL_REPLAY,
                    start_date=(TARGET_TIP - timedelta(days=2)).date(),
                    end_date=(TARGET_TIP - timedelta(days=2)).date(),
                    event_id=SECOND_HISTORY_ID,
                    limit=10,
                    offset=0,
                )
                operational_history = await repository.list_forecasts(
                    latest_only=False,
                    purpose=ForecastPurpose.OPERATIONAL,
                    sports_event_id=TARGET_ID,
                    model_name="nba_elo",
                    model_version=None,
                    limit=10,
                    offset=0,
                )
                latest = await repository.list_forecasts(
                    latest_only=True,
                    purpose=ForecastPurpose.OPERATIONAL,
                    sports_event_id=TARGET_ID,
                    model_name=None,
                    model_version=None,
                    limit=10,
                    offset=0,
                )
                models = await repository.list_model_versions()

                assert first.persisted == 1
                assert first.training_games_processed == 2
                assert identical.persisted == 0
                assert changed.persisted == 1
                assert replay.persisted == 1
                assert len(operational_history) == 2
                assert len(latest) == 1
                assert len(models) == 1
                assert (
                    operational_history[0].input_fingerprint
                    != operational_history[1].input_fingerprint
                )
                assert (
                    operational_history[0].home_win_probability
                    != operational_history[1].home_win_probability
                )
                assert latest[0].input_fingerprint == operational_history[0].input_fingerprint
                assert replay.training_games_processed == 1
        finally:
            await outer_transaction.rollback()
    await engine.dispose()


def test_postgres_forecast_idempotence_append_history_and_replay() -> None:
    asyncio.run(_run_integration())
