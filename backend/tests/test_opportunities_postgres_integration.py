from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.domain.forecasts import EloConfiguration
from app.models.forecasts import BaseForecastRecord, ModelVersionRecord
from app.models.markets import (
    MarketOutcomeRecord,
    MarketPriceRecord,
    PredictionMarketRecord,
    Provider,
)
from app.models.matching import MarketEventMatchRecord
from app.models.sports import SportsEventRecord, TeamRecord
from app.services.forecasting.elo import (
    ELO_FORMULA,
    configuration_fingerprint,
    effective_model_version,
    source_event_fingerprint,
)
from app.services.forecasting.repository import model_version_record_id
from app.services.opportunities.repository import OpportunityRepository
from app.services.opportunities.service import OpportunityDetectionService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION_TESTS") != "1",
    reason="set RUN_DATABASE_INTEGRATION_TESTS=1 against a migrated test database",
)

RUN_AT = datetime(2026, 8, 8, 16, tzinfo=UTC)
MARKET_ID = UUID("50000000-0000-0000-0000-000000000001")
FIRST_PRICE_ID = UUID("50000000-0000-0000-0000-000000000002")
SECOND_PRICE_ID = UUID("50000000-0000-0000-0000-000000000003")
MATCH_ID = UUID("50000000-0000-0000-0000-000000000004")
UNMATCHED_ID = UUID("50000000-0000-0000-0000-000000000005")
EVENT_ID = UUID("50000000-0000-0000-0000-000000000006")
FORECAST_ID = UUID("50000000-0000-0000-0000-000000000007")
HOME_ID = UUID("50000000-0000-0000-0000-000000000008")
AWAY_ID = UUID("50000000-0000-0000-0000-000000000009")


def _team(team_id: UUID, provider_id: str, abbreviation: str, city: str, name: str) -> TeamRecord:
    return TeamRecord(
        id=team_id,
        provider_name="balldontlie",
        provider_team_id=provider_id,
        league="nba",
        abbreviation=abbreviation,
        city=city,
        name=name,
        full_name=f"{city} {name}",
        conference="East",
        division="Atlantic",
        raw_data={},
        first_seen_at=RUN_AT - timedelta(days=1),
        last_seen_at=RUN_AT - timedelta(minutes=20),
    )


def _price(price_id: UUID, retrieved_at: datetime, yes_ask: str) -> MarketPriceRecord:
    ask = Decimal(yes_ask)
    return MarketPriceRecord(
        id=price_id,
        market_id=MARKET_ID,
        yes_bid=ask - Decimal("0.02"),
        yes_ask=ask,
        no_bid=Decimal("1") - ask,
        no_ask=Decimal("1.02") - ask,
        last_price=ask - Decimal("0.01"),
        volume=Decimal("100"),
        volume_24h=Decimal("25"),
        open_interest=Decimal("50"),
        liquidity=None,
        retrieved_at=retrieved_at,
    )


async def _run_integration() -> None:
    configuration = EloConfiguration()
    model_version = effective_model_version(configuration)
    model_id = model_version_record_id("nba_elo", model_version)
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
                            {"name": "kalshi", "display_name": "Kalshi", "is_read_only": True},
                            {
                                "name": "balldontlie",
                                "display_name": "BALLDONTLIE",
                                "is_read_only": True,
                            },
                        ]
                    )
                    .on_conflict_do_nothing(index_elements=[Provider.name])
                )
                event_last_seen = RUN_AT - timedelta(minutes=20)
                market = PredictionMarketRecord(
                    id=MARKET_ID,
                    provider_name="kalshi",
                    provider_market_id="phase5-market",
                    provider_event_id="phase5-event",
                    series_ticker="NBA-GAME",
                    category="Sports",
                    market_type="binary",
                    title="Will the Boston Celtics win?",
                    subtitle="BOS vs NYK",
                    rules_primary=None,
                    rules_secondary=None,
                    status="active",
                    is_nba=True,
                    open_time=RUN_AT - timedelta(days=1),
                    close_time=RUN_AT + timedelta(hours=1),
                    occurrence_time=RUN_AT + timedelta(hours=1),
                    provider_created_at=None,
                    provider_updated_at=None,
                    raw_data={},
                    first_seen_at=RUN_AT - timedelta(days=1),
                    last_seen_at=RUN_AT,
                )
                market.outcomes = [
                    MarketOutcomeRecord(
                        id=UUID("50000000-0000-0000-0000-000000000010"),
                        market_id=MARKET_ID,
                        provider_outcome_id="yes",
                        side="yes",
                        label="Boston Celtics",
                    ),
                    MarketOutcomeRecord(
                        id=UUID("50000000-0000-0000-0000-000000000011"),
                        market_id=MARKET_ID,
                        provider_outcome_id="no",
                        side="no",
                        label="New York Knicks",
                    ),
                ]
                session.add_all(
                    [
                        _team(HOME_ID, "phase5-bos", "BOS", "Boston", "Celtics"),
                        _team(AWAY_ID, "phase5-nyk", "NYK", "New York", "Knicks"),
                        SportsEventRecord(
                            id=EVENT_ID,
                            provider_name="balldontlie",
                            provider_event_id="phase5-game",
                            league="nba",
                            season=2026,
                            event_date=RUN_AT.date(),
                            scheduled_start_time=RUN_AT + timedelta(hours=1),
                            status="scheduled",
                            status_detail="Scheduled",
                            period=0,
                            clock=None,
                            postseason=False,
                            postponed=False,
                            tournament_stage=None,
                            home_team_id=HOME_ID,
                            away_team_id=AWAY_ID,
                            home_score=None,
                            away_score=None,
                            venue=None,
                            raw_data={},
                            first_seen_at=RUN_AT - timedelta(days=1),
                            last_seen_at=event_last_seen,
                        ),
                        market,
                        ModelVersionRecord(
                            id=model_id,
                            model_name="nba_elo",
                            model_version=model_version,
                            algorithm="elo",
                            configuration=configuration.model_dump(mode="json"),
                            configuration_fingerprint=configuration_fingerprint(configuration),
                            formula=ELO_FORMULA,
                            description="fixture",
                            created_at=RUN_AT - timedelta(minutes=10),
                        ),
                    ]
                )
                await session.flush()
                session.add_all(
                    [
                        MarketEventMatchRecord(
                            id=MATCH_ID,
                            market_id=MARKET_ID,
                            league="nba",
                            sports_event_id=EVENT_ID,
                            status="matched",
                            confidence=Decimal("0.9900"),
                            method="fixture",
                            reason="fixture",
                            matcher_version="deterministic-team-time-v1",
                            min_confidence=Decimal("0.9000"),
                            ambiguity_margin=Decimal("0.1000"),
                            time_window_hours=36,
                            automatic_trading_eligible=True,
                            input_fingerprint="a" * 64,
                            team_signals=[],
                            candidate_scores=[],
                            evidence={},
                            evaluated_at=RUN_AT - timedelta(minutes=20),
                        ),
                        _price(FIRST_PRICE_ID, RUN_AT - timedelta(minutes=2), "0.55"),
                        BaseForecastRecord(
                            id=FORECAST_ID,
                            sports_event_id=EVENT_ID,
                            model_version_id=model_id,
                            purpose="operational",
                            home_team_id=HOME_ID,
                            away_team_id=AWAY_ID,
                            home_win_probability=Decimal("0.640000"),
                            away_win_probability=Decimal("0.360000"),
                            home_team_rating=Decimal("1510"),
                            away_team_rating=Decimal("1490"),
                            adjusted_rating_difference=Decimal("120"),
                            training_data_fingerprint="b" * 64,
                            input_fingerprint="c" * 64,
                            input_features={
                                "source_event_fingerprint": source_event_fingerprint(
                                    event_id=EVENT_ID,
                                    scheduled_start_time=RUN_AT + timedelta(hours=1),
                                    home_team_id=HOME_ID,
                                    away_team_id=AWAY_ID,
                                    event_status="scheduled",
                                )
                            },
                            training_games_seen=10,
                            training_games_processed=10,
                            skipped_tied_games=0,
                            skipped_incomplete_games=0,
                            home_prior_games=5,
                            away_prior_games=5,
                            latest_training_event_time=RUN_AT - timedelta(days=1),
                            forecast_as_of=RUN_AT - timedelta(minutes=10),
                            source_event_last_seen_at=event_last_seen,
                            generated_at=RUN_AT - timedelta(minutes=10),
                        ),
                    ]
                )
                await session.commit()

                repository = OpportunityRepository(session)
                service = OpportunityDetectionService(repository=repository, clock=lambda: RUN_AT)
                first = await service.run(
                    start_date=RUN_AT.date(),
                    end_date=RUN_AT.date(),
                    market_id=MARKET_ID,
                    limit=10,
                    offset=0,
                )
                identical = await service.run(
                    start_date=RUN_AT.date(),
                    end_date=RUN_AT.date(),
                    market_id=MARKET_ID,
                    limit=10,
                    offset=0,
                )
                session.add(_price(SECOND_PRICE_ID, RUN_AT + timedelta(minutes=1), "0.53"))
                await session.commit()
                changed_service = OpportunityDetectionService(
                    repository=repository,
                    clock=lambda: RUN_AT + timedelta(minutes=2),
                )
                changed = await changed_service.run(
                    start_date=RUN_AT.date(),
                    end_date=RUN_AT.date(),
                    market_id=MARKET_ID,
                    limit=10,
                    offset=0,
                )
                session.add(
                    MarketEventMatchRecord(
                        id=UNMATCHED_ID,
                        market_id=MARKET_ID,
                        league="nba",
                        sports_event_id=None,
                        status="unmatched",
                        confidence=Decimal("0"),
                        method="no_candidate",
                        reason="newest decision is unsafe",
                        matcher_version="deterministic-team-time-v1",
                        min_confidence=Decimal("0.9000"),
                        ambiguity_margin=Decimal("0.1000"),
                        time_window_hours=36,
                        automatic_trading_eligible=False,
                        input_fingerprint="d" * 64,
                        team_signals=[],
                        candidate_scores=[],
                        evidence={},
                        evaluated_at=RUN_AT + timedelta(minutes=3),
                    )
                )
                await session.commit()
                masked_service = OpportunityDetectionService(
                    repository=repository,
                    clock=lambda: RUN_AT + timedelta(minutes=4),
                )
                masked = await masked_service.run(
                    start_date=RUN_AT.date(),
                    end_date=RUN_AT.date(),
                    market_id=MARKET_ID,
                    limit=10,
                    offset=0,
                )
                current = await repository.list_opportunities(
                    latest_only=True,
                    current_only=True,
                    current_at=None,
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
                history = await repository.list_opportunities(
                    latest_only=False,
                    current_only=False,
                    current_at=None,
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

                assert first.persisted == 2
                assert identical.persisted == 0
                assert changed.persisted == 2
                assert masked.generated == 0
                assert masked.skip_counts == {"latest_match_not_eligible": 1}
                assert current == []
                assert len(history) == 4
                assert {record.direction for record in history} == {"yes", "no"}
                assert {record.market_price_id for record in history} == {
                    FIRST_PRICE_ID,
                    SECOND_PRICE_ID,
                }
        finally:
            await outer_transaction.rollback()
    await engine.dispose()


def test_postgres_opportunity_idempotence_history_and_latest_match_masking() -> None:
    asyncio.run(_run_integration())
