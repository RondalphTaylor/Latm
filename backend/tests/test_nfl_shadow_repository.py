from __future__ import annotations

import asyncio
import importlib.util
import os
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import get_settings
from app.domain.matching import MatchingPolicy
from app.domain.nfl_shadow import NflShadowConfiguration, NflShadowPrediction, NflShadowTarget
from app.models.markets import PredictionMarketRecord, Provider
from app.models.matching import MarketEventMatchRecord
from app.models.nfl_shadow import NflShadowForecastRecord
from app.models.sports import SportsEventRecord
from app.providers.sports.nfl import NflGamePayload, normalize_nfl_game
from app.services.matching.matcher import MATCHER_VERSION, MarketEventMatcher
from app.services.matching.repository import MatchingRepository, match_record_id
from app.services.matching.service import MarketEventMatchingService
from app.services.nfl_research.baseline import NflResearchGame
from app.services.nfl_research.repository import (
    NflResearchRepository,
    NflResearchSelection,
    _select_records,
)
from app.services.nfl_research.shadow import NFL_SHADOW_SEED_FINGERPRINT, NFL_SHADOW_VERSION
from app.services.nfl_research.shadow_repository import NflShadowForecastRepository
from app.services.sports.repository import SportsRepository, sports_event_record_id
from tests.test_nfl_matching import PRIMARY, SECONDARY
from tests.test_nfl_provider import game_payload
from tests.test_nfl_research_api import _record


def _test_prediction(
    history: list[NflResearchGame], target: NflShadowTarget, as_of: datetime
) -> NflShadowPrediction:
    """Storage tests stub only pure math; pinned-seed algorithm has separate tests."""
    assert history
    return NflShadowPrediction(
        target_snapshot=target,
        as_of=as_of,
        expected_home_payout=Decimal("0.600000"),
        expected_away_payout=Decimal("0.400000"),
        home_rating=1550,
        away_rating=1450,
        seed_fingerprint=NFL_SHADOW_SEED_FINGERPRINT,
        baseline_version="test-storage-only",
        config_version=NFL_SHADOW_VERSION,
        configuration=NflShadowConfiguration(
            initial_rating=1500,
            k_factor=20,
            rating_scale=400,
            home_advantage=0,
            offseason_regression_fraction=1 / 3,
        ),
        target_fingerprint="f" * 64,
    )


async def _test_seed(self: NflResearchRepository) -> NflResearchSelection:
    return _select_records([_record()], truncated=False)


def _downgrade(connection: Connection) -> None:
    path = Path(__file__).parents[1] / "alembic/versions/0022_nfl_shadow_forecasts.py"
    spec = importlib.util.spec_from_file_location("shadow_test_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with Operations.context(MigrationContext.configure(connection)):
        migration.downgrade()


async def _prepare(session: AsyncSession) -> tuple[UUID, UUID, UUID, datetime]:
    now = await session.scalar(select(func.clock_timestamp()))
    assert isinstance(now, datetime)
    kickoff = now + timedelta(hours=2)
    local_date = kickoff.astimezone(ZoneInfo("America/New_York")).date()
    assert kickoff.year == 2026, "isolated integration fixture requires the 2026 target season"
    display_date = f"{local_date:%b} {local_date.day}, {local_date.year}"
    event_ticker = f"KXNFLGAME-{local_date:%y%b%d}NESEA".upper()
    source = normalize_nfl_game(
        NflGamePayload.model_validate(
            game_payload(
                date=kickoff.isoformat(),
                status="Scheduled",
                status_state="scheduled",
                home_team_score=None,
                visitor_team_score=None,
            )
        ),
        retrieved_at=now,
    )
    await SportsRepository(session).upsert_events([source])
    await session.execute(
        insert(Provider)
        .values(name="kalshi", display_name="Kalshi", is_read_only=True)
        .on_conflict_do_nothing(index_elements=[Provider.name])
    )
    market = PredictionMarketRecord(
        id=uuid4(),
        provider_name="kalshi",
        provider_market_id=event_ticker + "-SEA",
        provider_event_id=event_ticker,
        series_ticker="KXNFLGAME",
        category="Sports",
        market_type="binary",
        title="Seattle wins",
        subtitle="NE vs SEA",
        rules_primary=PRIMARY.replace("Sep 9, 2026", display_date),
        rules_secondary=SECONDARY.replace("Sep 9, 2026", display_date),
        status="open",
        is_nba=False,
        sports_league="nfl",
        sports_market_type="single_game_winner",
        sports_classification_method="official_series_metadata",
        sports_classification_version="kalshi-official-series-v1",
        sports_classification_fingerprint="b" * 64,
        occurrence_time=kickoff,
        close_time=kickoff + timedelta(hours=6),
        raw_data={},
        first_seen_at=now,
        last_seen_at=now,
    )
    market.outcomes = []
    session.add(market)
    await session.commit()
    event_id = sports_event_record_id("balldontlie_nfl", source.provider_event_id)
    event = await session.get(SportsEventRecord, event_id)
    assert event is not None
    settings = get_settings()
    decision = MarketEventMatcher(
        MatchingPolicy(
            matcher_version=MATCHER_VERSION,
            min_confidence=settings.matching_min_confidence,
            ambiguity_margin=settings.matching_ambiguity_margin,
            time_window_hours=settings.matching_time_window_hours,
        )
    ).match(
        MarketEventMatchingService._market_input(market),
        teams=tuple(
            MarketEventMatchingService._team_input(team)
            for team in (event.home_team, event.away_team)
        ),
        events=(MarketEventMatchingService._event_input(event),),
        evaluated_at=now,
    )
    assert decision.status == "matched"
    await MatchingRepository(session).insert_decisions([decision])
    return match_record_id(decision), market.id, event.id, kickoff


async def _run_checks(fault: str | None) -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            outer = await connection.begin()
            try:
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    match_id, market_id, event_id, kickoff = await _prepare(session)
                    repository = NflShadowForecastRepository(session)
                    if fault in {"crossed_kickoff", "crossed_market_close"}:
                        boundary = kickoff
                        if fault == "crossed_market_close":
                            boundary = kickoff - timedelta(hours=1)
                            await session.execute(
                                update(PredictionMarketRecord)
                                .where(PredictionMarketRecord.id == market_id)
                                .values(close_time=boundary)
                            )
                            # The source match includes close_time; keep it semantically current.
                            market = await session.get(PredictionMarketRecord, market_id)
                            event = await session.get(SportsEventRecord, event_id)
                            assert market is not None and event is not None
                            settings = get_settings()
                            decision = MarketEventMatcher(
                                MatchingPolicy(
                                    matcher_version=MATCHER_VERSION,
                                    min_confidence=settings.matching_min_confidence,
                                    ambiguity_margin=settings.matching_ambiguity_margin,
                                    time_window_hours=settings.matching_time_window_hours,
                                )
                            ).match(
                                MarketEventMatchingService._market_input(market),
                                teams=tuple(
                                    MarketEventMatchingService._team_input(team)
                                    for team in (event.home_team, event.away_team)
                                ),
                                events=(MarketEventMatchingService._event_input(event),),
                                evaluated_at=kickoff - timedelta(hours=2),
                            )
                            await session.execute(
                                update(MarketEventMatchRecord)
                                .where(MarketEventMatchRecord.id == match_id)
                                .values(input_fingerprint=decision.input_fingerprint)
                            )
                        times = iter((kickoff - timedelta(hours=2), boundary))

                        async def controlled_clock() -> datetime:
                            return next(times)

                        repository._now = controlled_clock  # type: ignore[method-assign]
                    if fault == "stale_event":
                        await session.execute(
                            update(SportsEventRecord)
                            .where(SportsEventRecord.id == event_id)
                            .values(last_seen_at=kickoff - timedelta(days=2))
                        )
                    elif fault == "closed_market":
                        await session.execute(
                            update(PredictionMarketRecord)
                            .where(PredictionMarketRecord.id == market_id)
                            .values(status="closed")
                        )
                    elif fault == "changed_rules":
                        await session.execute(
                            update(PredictionMarketRecord)
                            .where(PredictionMarketRecord.id == market_id)
                            .values(rules_secondary="unsupported revised rules")
                        )
                    elif fault == "future_source":
                        await session.execute(
                            update(SportsEventRecord)
                            .where(SportsEventRecord.id == event_id)
                            .values(last_seen_at=kickoff)
                        )
                    elif fault == "old_unchanged_match":
                        await session.execute(
                            update(MarketEventMatchRecord)
                            .where(MarketEventMatchRecord.id == match_id)
                            .values(evaluated_at=kickoff - timedelta(days=2))
                        )
                    elif fault == "duplicate_candidate":
                        event = await session.get(SportsEventRecord, event_id)
                        assert event is not None
                        raw = dict(event.raw_data)
                        raw["id"] = 7002
                        duplicate = normalize_nfl_game(
                            NflGamePayload.model_validate(raw), retrieved_at=event.last_seen_at
                        )
                        await SportsRepository(session).upsert_events([duplicate])
                    elif fault == "newer_unmatched":
                        current = await session.get(MarketEventMatchRecord, match_id)
                        assert current is not None
                        values = {
                            column.name: getattr(current, column.name)
                            for column in MarketEventMatchRecord.__table__.columns
                        }
                        values.update(
                            id=uuid4(),
                            status="unmatched",
                            sports_event_id=None,
                            input_fingerprint="e" * 64,
                            evaluated_at=kickoff - timedelta(hours=1),
                        )
                        await session.execute(insert(MarketEventMatchRecord).values(values))
                    await session.commit()
                    if fault is not None and fault != "old_unchanged_match":
                        expected_error = (
                            "boundary crossed while building"
                            if fault in {"crossed_kickoff", "crossed_market_close"}
                            else None
                        )
                        with pytest.raises(ValueError, match=expected_error):
                            await repository.run(match_id)
                        assert (
                            await session.scalar(
                                select(func.count()).select_from(NflShadowForecastRecord)
                            )
                            == 0
                        )
                        return
                    first, created = await repository.run(match_id)
                    assert created
                    second, created_again = await repository.run(match_id)
                    assert not created_again and second.id == first.id
                    assert first.expected_yes_payout == Decimal("0.400000")
                    assert first.expected_no_payout == Decimal("0.600000")
                    assert first.generated_at < kickoff
                    assert first.research_only and not first.trading_enabled
                    assert first.audit["seed"]
                    assert await repository.get_snapshot(first.id) is first
                    assert len(await repository.list_snapshots(limit=10, offset=0)) == 1
                    for statement in (
                        update(NflShadowForecastRecord).values(trading_enabled=True),
                        delete(NflShadowForecastRecord),
                    ):
                        with pytest.raises(DBAPIError, match="immutable"):
                            async with session.begin_nested():
                                await session.execute(statement)
                    invalid = {
                        column.name: getattr(first, column.name)
                        for column in NflShadowForecastRecord.__table__.columns
                    }
                    invalid.update(id=uuid4(), input_fingerprint="d" * 64, trading_enabled=True)
                    with pytest.raises(IntegrityError, match="safety"):
                        async with session.begin_nested():
                            await session.execute(insert(NflShadowForecastRecord).values(invalid))
                    invalid.update(trading_enabled=False, sports_event_id=uuid4())
                    with pytest.raises(DBAPIError, match="lineage"):
                        async with session.begin_nested():
                            await session.execute(insert(NflShadowForecastRecord).values(invalid))
                    await session.commit()
                    with pytest.raises(DBAPIError, match="downgrade refused"):
                        async with connection.begin_nested():
                            await connection.run_sync(_downgrade)
            finally:
                await outer.rollback()
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_INTEGRATION_TESTS") != "1",
    reason="requires isolated migrated PostgreSQL database",
)
@pytest.mark.parametrize(
    "fault",
    [
        None,
        "stale_event",
        "closed_market",
        "changed_rules",
        "future_source",
        "duplicate_candidate",
        "newer_unmatched",
        "old_unchanged_match",
        "crossed_kickoff",
        "crossed_market_close",
    ],
)
def test_shadow_storage_and_pregame_fail_closed(
    monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    monkeypatch.setattr(NflResearchRepository, "select_games", _test_seed)
    monkeypatch.setattr(
        "app.services.nfl_research.shadow_repository.build_shadow_prediction", _test_prediction
    )
    asyncio.run(_run_checks(fault))
