from __future__ import annotations

import asyncio
import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.domain.matching import MatchingPolicy
from app.models.markets import (
    MarketOutcomeRecord,
    PredictionMarketRecord,
    Provider,
)
from app.models.sports import SportsEventRecord, TeamRecord
from app.services.matching.matcher import MATCHER_VERSION, MarketEventMatcher
from app.services.matching.repository import MatchingRepository
from app.services.matching.service import MarketEventMatchingService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION_TESTS") != "1",
    reason="set RUN_DATABASE_INTEGRATION_TESTS=1 against a migrated test database",
)

MARKET_ID = UUID("f2494f3b-60c2-47ad-b20a-193b5492408d")
OUTCOME_ID = UUID("61356f91-9bda-4631-8713-9790f65ced77")
BOS_ID = UUID("44575499-5a70-4f8d-8c6f-e7066f77f29e")
NYK_ID = UUID("67e6cc5f-e2bd-480a-8ed6-ceec8224c497")
EVENT_ID = UUID("43171925-8705-4d2b-b2f5-4d2519d652fb")
TIP_TIME = datetime(2026, 8, 1, 23, tzinfo=UTC)


async def _run_integration() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url)
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
                session.add_all(
                    [
                        TeamRecord(
                            id=BOS_ID,
                            provider_name="balldontlie",
                            provider_team_id="phase3-bos",
                            league="nba",
                            abbreviation="BOS",
                            city="Boston",
                            name="Celtics",
                            full_name="Boston Celtics",
                            conference="East",
                            division="Atlantic",
                            raw_data={},
                            first_seen_at=TIP_TIME,
                            last_seen_at=TIP_TIME,
                        ),
                        TeamRecord(
                            id=NYK_ID,
                            provider_name="balldontlie",
                            provider_team_id="phase3-nyk",
                            league="nba",
                            abbreviation="NYK",
                            city="New York",
                            name="Knicks",
                            full_name="New York Knicks",
                            conference="East",
                            division="Atlantic",
                            raw_data={},
                            first_seen_at=TIP_TIME,
                            last_seen_at=TIP_TIME,
                        ),
                        SportsEventRecord(
                            id=EVENT_ID,
                            provider_name="balldontlie",
                            provider_event_id="phase3-event",
                            league="nba",
                            season=2025,
                            event_date=date(2026, 8, 1),
                            scheduled_start_time=TIP_TIME,
                            status="scheduled",
                            status_detail="7:00 pm ET",
                            period=0,
                            clock=None,
                            postseason=False,
                            postponed=False,
                            tournament_stage=None,
                            home_team_id=BOS_ID,
                            away_team_id=NYK_ID,
                            home_score=None,
                            away_score=None,
                            venue=None,
                            raw_data={},
                            first_seen_at=TIP_TIME,
                            last_seen_at=TIP_TIME,
                        ),
                    ]
                )
                market = PredictionMarketRecord(
                    id=MARKET_ID,
                    provider_name="kalshi",
                    provider_market_id="phase3-market",
                    provider_event_id="phase3-provider-event",
                    series_ticker="NBA-GAME",
                    category="Sports",
                    market_type="binary",
                    title="Will Boston win the Pro Basketball game?",
                    subtitle="BOS vs NYK",
                    rules_primary=None,
                    rules_secondary=None,
                    status="open",
                    is_nba=True,
                    open_time=None,
                    close_time=TIP_TIME + timedelta(hours=2),
                    occurrence_time=TIP_TIME,
                    provider_created_at=None,
                    provider_updated_at=None,
                    raw_data={},
                    first_seen_at=TIP_TIME,
                    last_seen_at=TIP_TIME,
                )
                market.outcomes = [
                    MarketOutcomeRecord(
                        id=OUTCOME_ID,
                        market_id=MARKET_ID,
                        provider_outcome_id="yes",
                        side="yes",
                        label="Boston",
                    )
                ]
                session.add(market)
                await session.commit()

                repository = MatchingRepository(session)
                policy = MatchingPolicy(
                    matcher_version=MATCHER_VERSION,
                    min_confidence=Decimal("0.90"),
                    ambiguity_margin=Decimal("0.10"),
                    time_window_hours=36,
                )
                service = MarketEventMatchingService(
                    repository=repository,
                    matcher=MarketEventMatcher(policy),
                    policy=policy,
                    sports_provider_name="balldontlie",
                )
                first = await service.run(
                    start_date=date(2026, 8, 1),
                    end_date=date(2026, 8, 1),
                    market_id=MARKET_ID,
                    limit=10,
                    offset=0,
                )
                identical = await service.run(
                    start_date=date(2026, 8, 1),
                    end_date=date(2026, 8, 1),
                    market_id=MARKET_ID,
                    limit=10,
                    offset=0,
                )
                event_record = await session.get(SportsEventRecord, EVENT_ID)
                assert event_record is not None
                event_record.scheduled_start_time = TIP_TIME + timedelta(hours=1)
                await session.commit()
                changed = await service.run(
                    start_date=date(2026, 8, 1),
                    end_date=date(2026, 8, 1),
                    market_id=MARKET_ID,
                    limit=10,
                    offset=0,
                )
                history = await repository.list_matches(
                    latest_only=False,
                    match_status=None,
                    market_id=MARKET_ID,
                    sports_event_id=None,
                    automatic_trading_eligible=None,
                    limit=10,
                    offset=0,
                )
                latest = await repository.get_latest_market_match(MARKET_ID)

                assert first.matched == 1
                assert first.persisted == 1
                assert identical.persisted == 0
                assert changed.persisted == 1
                assert len(history) == 2
                assert latest is not None
                assert latest.status == "matched"
                assert latest.automatic_trading_eligible is True
        finally:
            await outer_transaction.rollback()
    await engine.dispose()


def test_postgres_history_idempotence_and_latest_result() -> None:
    asyncio.run(_run_integration())
