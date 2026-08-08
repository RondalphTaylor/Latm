from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ClauseElement, Executable

from app.domain.sports import SportsEvent, SportsEventStatus, Team
from app.services.sports.repository import (
    SportsRepository,
    sports_event_record_id,
    team_record_id,
)


class RecordingSession:
    """Minimal async-session double for upsert and transaction assertions."""

    def __init__(self) -> None:
        self.statements: list[ClauseElement] = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement: Executable) -> None:
        self.statements.append(cast(ClauseElement, statement))

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def team(*, provider_id: str, abbreviation: str, city: str, name: str) -> Team:
    return Team(
        provider_name="balldontlie",
        provider_team_id=provider_id,
        abbreviation=abbreviation,
        city=city,
        name=name,
        full_name=f"{city} {name}",
        conference="East",
        division="Atlantic",
        raw_data={"id": provider_id},
        retrieved_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def event(*, event_status: SportsEventStatus = SportsEventStatus.FINAL) -> SportsEvent:
    return SportsEvent(
        provider_name="balldontlie",
        provider_event_id="15907925",
        season=2025,
        event_date=date(2026, 8, 1),
        scheduled_start_time=datetime(2026, 8, 1, 23, tzinfo=UTC),
        status=event_status,
        status_detail="Final" if event_status is SportsEventStatus.FINAL else "7:00 pm ET",
        period=4 if event_status is SportsEventStatus.FINAL else 0,
        postseason=False,
        postponed=False,
        home_team=team(provider_id="2", abbreviation="BOS", city="Boston", name="Celtics"),
        away_team=team(provider_id="20", abbreviation="NYK", city="New York", name="Knicks"),
        home_score=115 if event_status is SportsEventStatus.FINAL else None,
        away_score=105 if event_status is SportsEventStatus.FINAL else None,
        raw_data={"id": 15907925},
        retrieved_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def test_event_upsert_is_identity_stable_and_deduplicates_input() -> None:
    session = RecordingSession()
    repository = SportsRepository(cast(AsyncSession, session))
    scheduled = event(event_status=SportsEventStatus.SCHEDULED)
    completed = event()

    result = asyncio.run(repository.upsert_events([scheduled, completed]))

    assert result.events == 1
    assert result.teams == 2
    assert session.commits == 1
    assert session.rollbacks == 0
    assert len(session.statements) == 3
    assert sports_event_record_id("balldontlie", "15907925") == sports_event_record_id(
        "balldontlie", "15907925"
    )
    assert team_record_id("balldontlie", "2") == team_record_id("balldontlie", "2")
    event_sql = str(session.statements[2])
    assert "ON CONFLICT ON CONSTRAINT uq_sports_events_provider_event_id DO UPDATE" in event_sql


def test_team_upsert_batches_large_sets() -> None:
    session = RecordingSession()
    repository = SportsRepository(cast(AsyncSession, session))
    teams = [
        team(
            provider_id=str(index),
            abbreviation=f"T{index}",
            city="Test",
            name=f"Team {index}",
        )
        for index in range(501)
    ]

    persisted = asyncio.run(repository.upsert_teams(teams))

    assert persisted == 501
    assert session.commits == 1
    assert len(session.statements) == 3
