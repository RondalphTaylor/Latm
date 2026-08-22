from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import Table
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ClauseElement, Executable

from app.domain.matching import MarketEventMatchDecision
from app.domain.sports import SportsLeague
from app.models.matching import MarketEventMatchRecord
from app.services.matching.repository import (
    MatchingRepository,
    match_record_id,
)
from tests.test_event_matcher import evaluate, event, market


class ScalarResult:
    def __init__(self, values: Sequence[object]) -> None:
        self._values = list(values)

    def all(self) -> list[object]:
        return self._values

    def unique(self) -> ScalarResult:
        return self

    def one_or_none(self) -> object | None:
        if not self._values:
            return None
        return self._values[0]


class RecordingSession:
    """Minimal scalar-session double for matching repository assertions."""

    def __init__(self, results: Sequence[Sequence[object]] = ()) -> None:
        self.statements: list[ClauseElement] = []
        self.results = [list(result) for result in results]
        self.commits = 0
        self.rollbacks = 0
        self.failure: Exception | None = None

    async def scalars(self, statement: Executable) -> ScalarResult:
        self.statements.append(cast(ClauseElement, statement))
        if self.failure is not None:
            raise self.failure
        values = self.results.pop(0) if self.results else []
        return ScalarResult(values)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def decision() -> MarketEventMatchDecision:
    return evaluate(market(), event())


def test_database_model_declares_policy_and_safety_constraints() -> None:
    table = cast(Table, MarketEventMatchRecord.__table__)
    constraint_names = {constraint.name for constraint in table.constraints}

    assert {
        "ck_market_event_matches_confidence",
        "ck_market_event_matches_policy_confidence",
        "ck_market_event_matches_time_window",
        "ck_market_event_matches_fingerprint_length",
        "ck_market_event_matches_status",
        "ck_market_event_matches_league",
        "ck_market_event_matches_safety_state",
        "uq_market_event_matches_semantic_input",
    } <= constraint_names


def test_insert_is_stable_append_oriented_and_semantically_idempotent() -> None:
    match = decision()
    expected_id = match_record_id(match)
    session = RecordingSession(results=[[expected_id]])
    repository = MatchingRepository(cast(AsyncSession, session))

    inserted = asyncio.run(repository.insert_decisions([match]))

    assert inserted == 1
    assert session.commits == 1
    assert session.rollbacks == 0
    assert match_record_id(match) == expected_id
    sql = str(session.statements[0])
    assert "ON CONFLICT ON CONSTRAINT uq_market_event_matches_semantic_input DO NOTHING" in sql
    assert "RETURNING market_event_matches.id" in sql


def test_insert_rolls_back_complete_batch_on_failure() -> None:
    session = RecordingSession()
    session.failure = RuntimeError("database unavailable")
    repository = MatchingRepository(cast(AsyncSession, session))

    try:
        asyncio.run(repository.insert_decisions([decision()]))
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected repository failure")

    assert session.commits == 0
    assert session.rollbacks == 1


def test_latest_query_ranks_before_applying_safety_filters() -> None:
    session = RecordingSession(results=[[]])
    repository = MatchingRepository(cast(AsyncSession, session))

    records = asyncio.run(
        repository.list_matches(
            latest_only=True,
            match_status="matched",
            market_id=UUID("3da220e1-b6d0-45e9-b507-7e75dc95a353"),
            sports_event_id=None,
            automatic_trading_eligible=True,
            league=SportsLeague.NBA,
            limit=25,
            offset=2,
        )
    )

    assert records == []
    sql = str(session.statements[0])
    assert "row_number() OVER (PARTITION BY market_event_matches.market_id" in sql
    assert "market_event_matches.status" in sql
    assert "market_event_matches.automatic_trading_eligible" in sql


def test_query_input_statements_are_bounded_and_provider_scoped() -> None:
    session = RecordingSession(results=[[], [], []])
    repository = MatchingRepository(cast(AsyncSession, session))
    start = datetime(2026, 8, 1, tzinfo=UTC)

    asyncio.run(
        repository.list_markets_for_matching(
            reference_start=start,
            reference_end=start,
            market_id=None,
            limit=100,
            offset=0,
            league=SportsLeague.MLB,
        )
    )
    asyncio.run(
        repository.list_teams_for_matching(
            provider_name="mlb",
            league=SportsLeague.MLB,
        )
    )
    asyncio.run(
        repository.list_events_for_matching(
            provider_name="balldontlie",
            start_date=start.date(),
            end_date=start.date(),
            league=SportsLeague.MLB,
        )
    )

    market_sql, team_sql, event_sql = (str(statement) for statement in session.statements)
    assert "markets.sports_league" in market_sql
    assert "markets.sports_market_type" in market_sql
    assert "coalesce(markets.occurrence_time, markets.close_time)" in market_sql
    assert "teams.provider_name" in team_sql
    assert "sports_events.provider_name" in event_sql
    assert "sports_events.league" in event_sql
