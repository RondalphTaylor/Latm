from __future__ import annotations

import asyncio
import os
from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.domain.sports import SportsEvent, SportsEventStatus, SportsLeague, Team
from app.models.markets import Provider
from app.schemas.sports import SportsEventResponse
from app.services.sports.repository import (
    SportsRepository,
    sports_event_record_id,
    team_record_id,
)

OBSERVED_AT = datetime(2026, 9, 10, 12, tzinfo=UTC)


def _team(provider: str, league: SportsLeague, identity: str) -> Team:
    return Team(
        provider_name=provider,
        provider_team_id=identity,
        league=league,
        abbreviation="NE" if identity == "1" else "SEA",
        city="New England" if identity == "1" else "Seattle",
        name="Patriots" if identity == "1" else "Seahawks",
        full_name="New England Patriots" if identity == "1" else "Seattle Seahawks",
        conference="AFC" if identity == "1" else "NFC",
        division="East" if identity == "1" else "West",
        raw_data={"id": int(identity)},
        retrieved_at=OBSERVED_AT,
    )


def _event(
    provider: str = "balldontlie_nfl", league: SportsLeague = SportsLeague.NFL
) -> SportsEvent:
    return SportsEvent(
        provider_name=provider,
        provider_event_id="1001",
        league=league,
        season=2026,
        event_date=date(2026, 9, 10),
        scheduled_start_time=datetime(2026, 9, 11, 0, 20, tzinfo=UTC),
        status=SportsEventStatus.SCHEDULED,
        status_detail="Scheduled",
        period=0,
        postseason=False,
        postponed=False,
        home_team=_team(provider, league, "1"),
        away_team=_team(provider, league, "2"),
        venue="Test venue",
        raw_data={"id": 1001, "week": 1},
        retrieved_at=OBSERVED_AT,
    )


def test_nfl_identity_is_separate_from_nba_with_equal_source_ids() -> None:
    assert SportsLeague("nfl") is SportsLeague.NFL
    assert team_record_id("balldontlie_nfl", "1") != team_record_id("balldontlie", "1")
    assert sports_event_record_id("balldontlie_nfl", "1001") != sports_event_record_id(
        "balldontlie", "1001"
    )
    assert SportsRepository._provider_values({"balldontlie_nfl"}) == [
        {"name": "balldontlie_nfl", "display_name": "BALLDONTLIE NFL", "is_read_only": True}
    ]


def test_event_rejects_team_from_another_league() -> None:
    values = _event().model_dump()
    values["home_team"] = _team("balldontlie", SportsLeague.NBA, "1")
    with pytest.raises(ValidationError, match="event league"):
        SportsEvent.model_validate(values)


async def _run_persistence_checks() -> None:
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
                    repository = SportsRepository(session)
                    nfl = _event()
                    nba = _event("balldontlie", SportsLeague.NBA)
                    initial = await repository.upsert_events([nfl, nba, nfl])
                    assert initial.events == 2
                    assert initial.teams == 4
                    await repository.upsert_events([nfl, nba])
                    nfl_id = sports_event_record_id("balldontlie_nfl", "1001")
                    nba_id = sports_event_record_id("balldontlie", "1001")
                    stored = await repository.get_event(nfl_id)
                    assert stored is not None
                    assert stored.home_score is None and stored.away_score is None
                    assert stored.raw_data["week"] == 1
                    assert stored.home_team.provider_name == "balldontlie_nfl"
                    assert SportsEventResponse.from_record(stored).league == "nfl"
                    provider = await session.scalar(
                        select(Provider).where(Provider.name == "balldontlie_nfl")
                    )
                    assert provider is not None and provider.is_read_only

                    # Schedule revisions and final corrections update the same identity.
                    revised = nfl.model_copy(
                        update={
                            "event_date": date(2026, 9, 11),
                            "scheduled_start_time": nfl.scheduled_start_time + timedelta(days=1),
                            "status": SportsEventStatus.POSTPONED,
                            "status_detail": "Postponed",
                            "postponed": True,
                            "retrieved_at": OBSERVED_AT + timedelta(hours=1),
                        }
                    )
                    await repository.upsert_events([revised])
                    session.expire_all()
                    stored = await repository.get_event(nfl_id)
                    assert stored is not None and stored.postponed
                    assert stored.event_date == date(2026, 9, 11)
                    assert stored.scheduled_start_time == revised.scheduled_start_time

                    for score in (20, 23, 20):
                        final = revised.model_copy(
                            update={
                                "status": SportsEventStatus.FINAL,
                                "status_detail": "Final/OT",
                                "postponed": False,
                                "period": 5,
                                "home_score": score,
                                "away_score": 20,
                                "retrieved_at": OBSERVED_AT + timedelta(days=2),
                            }
                        )
                        await repository.upsert_events([final])
                        session.expire_all()
                        stored = await repository.get_event(nfl_id)
                        assert stored is not None
                        assert stored.id == nfl_id and stored.home_score == score
                        assert stored.away_score == 20
                        assert stored.first_seen_at == OBSERVED_AT
                        assert stored.last_seen_at == OBSERVED_AT + timedelta(days=2)
                        assert stored.home_team.league == "nfl"

                    nfl_events = await repository.list_events(
                        start_date=date(2026, 9, 11),
                        end_date=date(2026, 9, 11),
                        league="nfl",
                        event_status="final",
                        team_id=team_record_id("balldontlie_nfl", "1"),
                        provider_name="balldontlie_nfl",
                        limit=100,
                        offset=0,
                    )
                    assert [event.id for event in nfl_events] == [nfl_id]
                    nfl_teams = await repository.list_teams(
                        league="nfl", provider_name="balldontlie_nfl", limit=100, offset=0
                    )
                    assert {team.provider_team_id for team in nfl_teams} == {"1", "2"}
                    nba_stored = await repository.get_event(nba_id)
                    assert nba_stored is not None and nba_stored.league == "nba"
                    assert nba_stored.status == "scheduled"
                    assert nba_stored.home_score is None
                    assert nba_stored.home_team_id != nfl_events[0].home_team_id
            finally:
                await outer.rollback()
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_INTEGRATION_TESTS") != "1",
    reason="requires an explicitly enabled migrated PostgreSQL test database",
)
def test_nfl_persistence_replay_corrections_and_league_isolation() -> None:
    asyncio.run(_run_persistence_checks())
