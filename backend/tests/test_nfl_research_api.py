from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.sql import Select

from app.api.nfl_research import get_nfl_research_repository, router
from app.domain.sports import SportsLeague
from app.models.sports import SportsEventRecord, TeamRecord
from app.providers.sports.nfl import NflGamePayload, normalize_nfl_game
from app.services.nfl_research.baseline import evaluate_games
from app.services.nfl_research.repository import (
    MAX_SOURCE_ROWS,
    NflResearchRepository,
    NflResearchSelection,
    _select_records,
)
from app.services.sports.repository import SportsRepository
from tests.test_nfl_provider import game_payload


def _record() -> SportsEventRecord:
    event = normalize_nfl_game(
        NflGamePayload.model_validate(game_payload(date="2025-09-10T00:20:00Z", season=2025)),
        retrieved_at=datetime(2025, 9, 11, tzinfo=UTC),
    )
    record = SportsEventRecord(**SportsRepository._event_values([event])[0])
    record.home_team = TeamRecord(**SportsRepository._team_values([event.home_team])[0])
    record.away_team = TeamRecord(**SportsRepository._team_values([event.away_team])[0])
    return record


class StubRepository:
    def __init__(self, selection: NflResearchSelection) -> None:
        self.selection = selection

    async def select_games(self) -> NflResearchSelection:
        return self.selection


def _get(selection: NflResearchSelection) -> dict[str, object]:
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_nfl_research_repository] = lambda: StubRepository(
        selection
    )
    with TestClient(application) as client:
        response = client.get("/nfl-research-baseline")
    assert response.status_code == 200
    return cast(dict[str, object], response.json())


def test_empty_nfl_baseline_is_explicitly_blocked() -> None:
    body = _get(_select_records([], truncated=False))
    assert body["status"] == "blocked"
    assert body["blockers"] == ["no_eligible_historical_games"]
    assert body["report"] is None
    assert body["operational_forecast_published"] is False
    assert body["trading_eligible"] is False


def test_nfl_research_preview_has_exact_sources_and_replay_fingerprint() -> None:
    selection = _select_records([_record()], truncated=False)
    first = _get(selection)
    second = _get(selection)
    assert first == second
    assert first["status"] == "research_preview"
    assert first["research_only"] is True
    assert first["observation_basis"] == "retrospective_latest_results"
    assert first["selected_count"] == 1
    assert first["report"] is not None
    sources = cast(list[dict[str, object]], first["source_snapshots"])
    assert cast(dict[str, object], sources[0]["raw_data"])["week"] == 1


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("season", 2026, "out_of_scope_season"),
        ("postseason", True, "postseason"),
        ("status", "scheduled", "nonfinal"),
        ("home_score", None, "invalid_metadata"),
    ],
)
def test_ignored_rows_have_explicit_reasons(field: str, value: object, reason: str) -> None:
    record = _record()
    setattr(record, field, value)
    selection = _select_records([record], truncated=False)
    assert selection.ignored_reason_counts == {reason: 1}
    assert not selection.games
    assert selection.sources[0].event_id == record.id


@pytest.mark.parametrize("week", [None, 0, "1", True])
def test_invalid_or_missing_week_blocks_evaluation(week: object) -> None:
    record = _record()
    if week is None:
        del record.raw_data["week"]
        expected = "missing_source_week"
    else:
        record.raw_data["week"] = week
        expected = "invalid_metadata"
    selection = _select_records([record], truncated=False)
    body = _get(selection)
    assert body["status"] == "blocked"
    assert body["ignored_reason_counts"] == {expected: 1}
    assert "invalid_final_source_records" in cast(list[str], body["blockers"])


def test_source_row_cap_never_presents_partial_data_as_evaluated() -> None:
    body = _get(_select_records([_record()], truncated=True))
    assert body["status"] == "blocked"
    assert body["report"] is None
    assert body["blockers"] == ["source_row_limit_exceeded"]


def test_source_correction_changes_snapshot_fingerprint() -> None:
    record = _record()
    first = _select_records([record], truncated=False)
    record.home_score = 23
    record.raw_data["home_team_score"] = 23
    second = _select_records([record], truncated=False)
    assert first.source_fingerprint != second.source_fingerprint
    assert second.games[0].home_score == 23


@pytest.mark.parametrize(
    ("field", "value"), [("preseason", True), ("season_type", 1), ("season_type", 3)]
)
def test_explicit_nonregular_source_metadata_is_rejected(field: str, value: object) -> None:
    record = _record()
    record.raw_data[field] = value
    selection = _select_records([record], truncated=False)
    assert selection.ignored_reason_counts == {"invalid_metadata": 1}
    assert "invalid_final_source_records" in selection.blockers


def test_explicit_regular_season_type_is_accepted() -> None:
    record = _record()
    record.raw_data["season_type"] = 2
    assert len(_select_records([record], truncated=False).games) == 1


def test_preseason_calendar_does_not_enter_regular_research() -> None:
    record = _record()
    record.scheduled_start_time = datetime(2025, 8, 10, tzinfo=UTC)
    record.raw_data["date"] = record.scheduled_start_time.isoformat()
    selection = _select_records([record], truncated=False)
    assert selection.ignored_reason_counts == {"invalid_metadata": 1}


def test_evaluator_failure_is_blocked_with_diagnostic(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_: object) -> None:
        raise ValueError("duplicate provider game identity")

    monkeypatch.setattr("app.api.nfl_research.evaluate_games", fail)
    body = _get(_select_records([_record()], truncated=False))
    assert body["status"] == "blocked"
    assert body["evaluation_error"] == "duplicate provider game identity"
    assert body["report"] is None


class ScalarResult:
    def unique(self) -> ScalarResult:
        return self

    def all(self) -> list[SportsEventRecord]:
        return [_record()]


class SelectOnlySession:
    def __init__(self) -> None:
        self.statement: Select[tuple[SportsEventRecord]] | None = None

    async def scalars(self, statement: Select[tuple[SportsEventRecord]]) -> ScalarResult:
        self.statement = statement
        return ScalarResult()


def test_repository_only_selects_scoped_provider_and_league_with_hard_cap() -> None:
    session = SelectOnlySession()
    result = asyncio.run(NflResearchRepository(cast(AsyncSession, session)).select_games())
    assert len(result.games) == 1
    assert session.statement is not None
    compiled = session.statement.compile()
    values = set(compiled.params.values())
    assert "balldontlie_nfl" in values and "nfl" in values
    assert MAX_SOURCE_ROWS + 1 in values
    assert str(compiled).startswith("SELECT")


async def _run_postgres_selection() -> None:
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
                    nfl = normalize_nfl_game(
                        NflGamePayload.model_validate(
                            game_payload(date="2025-09-10T00:20:00Z", season=2025)
                        ),
                        retrieved_at=datetime(2025, 9, 11, tzinfo=UTC),
                    )
                    nba = nfl.model_copy(
                        update={
                            "provider_name": "balldontlie",
                            "league": SportsLeague.NBA,
                            "home_team": nfl.home_team.model_copy(
                                update={"provider_name": "balldontlie", "league": SportsLeague.NBA}
                            ),
                            "away_team": nfl.away_team.model_copy(
                                update={"provider_name": "balldontlie", "league": SportsLeague.NBA}
                            ),
                        }
                    )
                    await SportsRepository(session).upsert_events([nfl, nba])
                    session.expunge_all()
                    repository = NflResearchRepository(session)
                    first = await repository.select_games()
                    second = await repository.select_games()
                    assert first == second
                    assert len(first.games) == 1
                    assert len(first.sources) == 1
                    assert first.ignored == () and first.blockers == ()
                    assert first.sources[0].raw_data == nfl.raw_data
                    report = evaluate_games(list(first.games))
                    assert report == evaluate_games(list(second.games))
                    assert report.research_only is True
                    assert len(report.games) == 1
                    assert report.games[0].actual_home_payout == 0.5
                    assert not session.new and not session.dirty and not session.deleted
            finally:
                await outer.rollback()
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_INTEGRATION_TESTS") != "1",
    reason="requires a migrated isolated PostgreSQL test database",
)
def test_postgres_read_only_nfl_selection_and_reproducible_evaluation() -> None:
    asyncio.run(_run_postgres_selection())
