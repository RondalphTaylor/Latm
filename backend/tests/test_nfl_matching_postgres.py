from __future__ import annotations

import asyncio
import importlib.util
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import partial
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.domain.matching import MarketEventMatchDecision, MarketEventMatchStatus, MatchingPolicy
from app.domain.sports import SportsLeague
from app.models.markets import PredictionMarketRecord, Provider
from app.models.matching import MarketEventMatchRecord
from app.services.matching.matcher import MATCHER_VERSION, MarketEventMatcher
from app.services.matching.repository import MatchingRepository
from app.services.matching.service import MarketEventMatchingService
from app.services.sports.repository import SportsRepository, sports_event_record_id
from tests.test_nfl_matching import PRIMARY, SECONDARY
from tests.test_nfl_repository import _event

MARKET_ID = UUID("d80ff5fc-f6cd-47e1-b544-739a8c912ca0")
OBSERVED_AT = datetime(2026, 9, 10, 12, tzinfo=UTC)


def _migration() -> ModuleType:
    path = Path(__file__).parents[1] / "alembic/versions/0021_nfl_market_matching.py"
    spec = importlib.util.spec_from_file_location("nfl_market_matching_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_nfl_migration_downgrade_checks_before_changing_constraints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _migration()
    operations = MagicMock()
    monkeypatch.setattr(migration, "op", operations)
    migration.downgrade()
    calls = operations.mock_calls
    assert calls[0].args == ("LOCK TABLE markets, market_event_matches IN ACCESS EXCLUSIVE MODE",)
    assert "downgrade refused" in calls[1].args[0]
    assert "DELETE" not in calls[1].args[0]
    assert calls[2][0] == "drop_constraint"


def _apply_migration(connection: Connection, *, downgrade: bool) -> None:
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        migration = _migration()
        if downgrade:
            migration.downgrade()
        else:
            migration.upgrade()


async def _run_matching_checks() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            outer = await connection.begin()
            try:
                # Empty roundtrip must restore NBA/MLB checks and upgrade without data loss.
                await connection.run_sync(lambda conn: _apply_migration(conn, downgrade=True))
                await connection.run_sync(lambda conn: _apply_migration(conn, downgrade=False))
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    await SportsRepository(session).upsert_events([_event()])
                    await session.execute(
                        insert(Provider)
                        .values(name="kalshi", display_name="Kalshi", is_read_only=True)
                        .on_conflict_do_nothing(index_elements=[Provider.name])
                    )
                    market = PredictionMarketRecord(
                        id=MARKET_ID,
                        provider_name="kalshi",
                        provider_market_id="nfl-matching-storage-test",
                        market_type="binary",
                        title="New England Patriots at Seattle Seahawks",
                        status="open",
                        is_nba=False,
                        sports_league="nfl",
                        sports_market_type="single_game_winner",
                        sports_classification_method="official_series_metadata",
                        sports_classification_version="nfl-test-v1",
                        sports_classification_fingerprint="1" * 64,
                        raw_data={},
                        first_seen_at=OBSERVED_AT,
                        last_seen_at=OBSERVED_AT,
                    )
                    session.add(market)
                    await session.commit()
                    decision = MarketEventMatchDecision(
                        market_id=MARKET_ID,
                        league=SportsLeague.NFL,
                        sports_event_id=sports_event_record_id("balldontlie_nfl", "1001"),
                        status=MarketEventMatchStatus.MATCHED,
                        confidence=Decimal("1"),
                        method="teams_and_time",
                        reason="NFL research-only match",
                        matcher_version="nfl-test-v1",
                        min_confidence=Decimal("0.9"),
                        ambiguity_margin=Decimal("0.1"),
                        time_window_hours=36,
                        automatic_trading_eligible=False,
                        input_fingerprint="2" * 64,
                        team_signals=(),
                        candidate_scores=(),
                        evidence={"research_only": True},
                        evaluated_at=datetime(2020, 1, 1, tzinfo=UTC),
                    )
                    repository = MatchingRepository(session)
                    assert await repository.insert_decisions([decision]) == 1
                    assert await repository.insert_decisions([decision]) == 0
                    stored = await session.scalar(
                        select(MarketEventMatchRecord).where(
                            MarketEventMatchRecord.market_id == MARKET_ID
                        )
                    )
                    assert stored is not None
                    assert stored.league == "nfl"
                    assert stored.automatic_trading_eligible is False
                    # Direct database writes cannot bypass the domain safety validator.
                    unsafe = decision.model_copy(
                        update={
                            "automatic_trading_eligible": True,
                            "input_fingerprint": "3" * 64,
                        }
                    )
                    with pytest.raises(IntegrityError, match="safety_state"):
                        async with session.begin_nested():
                            await session.execute(
                                insert(MarketEventMatchRecord).values(
                                    MatchingRepository._decision_values(unsafe)
                                )
                            )
                    with pytest.raises(IntegrityError, match="safety_state"):
                        async with session.begin_nested():
                            await session.execute(
                                update(MarketEventMatchRecord)
                                .where(MarketEventMatchRecord.market_id == MARKET_ID)
                                .values(automatic_trading_eligible=True)
                            )
                    await session.commit()
                    # Exercise the real service, provider isolation and contract-date
                    # query fallback; market close is deliberately outside the run window.
                    await session.execute(
                        update(PredictionMarketRecord)
                        .where(PredictionMarketRecord.id == MARKET_ID)
                        .values(
                            provider_market_id="KXNFLGAME-26SEP10NESEA-SEA",
                            provider_event_id="KXNFLGAME-26SEP10NESEA",
                            series_ticker="KXNFLGAME",
                            title="Seattle wins",
                            category="Sports",
                            rules_primary=PRIMARY.replace("Sep 9,", "Sep 10,"),
                            rules_secondary=SECONDARY.replace("Sep 9,", "Sep 10,"),
                            occurrence_time=None,
                            close_time=datetime(2026, 10, 1, tzinfo=UTC),
                        )
                    )
                    await session.commit()
                    session.expire_all()
                    policy = MatchingPolicy(
                        matcher_version=MATCHER_VERSION,
                        min_confidence=Decimal("0.9"),
                        ambiguity_margin=Decimal("0.1"),
                        time_window_hours=36,
                    )
                    service = MarketEventMatchingService(
                        repository=MatchingRepository(session),
                        matcher=MarketEventMatcher(policy),
                        policy=policy,
                    )
                    run_matching = partial(
                        service.run,
                        start_date=date(2026, 9, 10),
                        end_date=date(2026, 9, 10),
                        market_id=None,
                        limit=100,
                        offset=0,
                        league=SportsLeague.NFL,
                    )
                    first = await run_matching()
                    replay = await run_matching()
                    assert first.examined == first.matched == first.persisted == 1
                    assert replay.matched == 1 and replay.persisted == 0
                    await session.execute(
                        update(PredictionMarketRecord)
                        .where(PredictionMarketRecord.id == MARKET_ID)
                        .values(rules_secondary="Unreviewed revised rules.")
                    )
                    await session.commit()
                    session.expire_all()
                    changed = await run_matching()
                    assert changed.unmatched == changed.persisted == 1
                    latest = await MatchingRepository(session).get_latest_market_match(MARKET_ID)
                    assert latest is not None and not latest.automatic_trading_eligible
                    assert latest.evidence["contract_eligible_for_research"] is False
                    with pytest.raises(DBAPIError, match="downgrade refused"):
                        async with connection.begin_nested():
                            await connection.run_sync(
                                lambda conn: _apply_migration(conn, downgrade=True)
                            )
                    assert (
                        await session.scalar(
                            select(MarketEventMatchRecord.automatic_trading_eligible).where(
                                MarketEventMatchRecord.market_id == MARKET_ID
                            )
                        )
                        is False
                    )
                    assert (
                        await session.scalar(
                            select(PredictionMarketRecord.sports_league).where(
                                PredictionMarketRecord.id == MARKET_ID
                            )
                        )
                        == "nfl"
                    )
            finally:
                await outer.rollback()
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_INTEGRATION_TESTS") != "1",
    reason="requires a migrated isolated PostgreSQL test database",
)
def test_nfl_matching_replay_database_gate_and_safe_downgrade() -> None:
    asyncio.run(_run_matching_checks())
