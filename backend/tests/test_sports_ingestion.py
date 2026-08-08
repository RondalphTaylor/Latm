from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, date, datetime

import pytest

from app.domain.sports import SportsEvent, SportsEventStatus, Team
from app.services.sports.ingestion import SportsIngestionService
from app.services.sports.repository import SportsRepository, SportsUpsertResult


def team(*, provider_id: str, abbreviation: str) -> Team:
    return Team(
        provider_name="balldontlie",
        provider_team_id=provider_id,
        abbreviation=abbreviation,
        city="Test",
        name=f"Team {abbreviation}",
        full_name=f"Test Team {abbreviation}",
        raw_data={},
        retrieved_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def event(*, provider_id: str, status: SportsEventStatus) -> SportsEvent:
    final = status is SportsEventStatus.FINAL
    return SportsEvent(
        provider_name="balldontlie",
        provider_event_id=provider_id,
        season=2025,
        event_date=date(2026, 8, 1),
        scheduled_start_time=datetime(2026, 8, 1, 23, tzinfo=UTC),
        status=status,
        status_detail="Final" if final else "7:00 pm ET",
        period=4 if final else 0,
        postseason=False,
        postponed=False,
        home_team=team(provider_id="2", abbreviation="BOS"),
        away_team=team(provider_id="20", abbreviation="NYK"),
        home_score=115 if final else None,
        away_score=105 if final else None,
        raw_data={},
        retrieved_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


class StaticSportsProvider:
    """Sports provider test double with date-range capture."""

    name = "balldontlie"

    def __init__(self) -> None:
        self.teams = [team(provider_id="2", abbreviation="BOS")]
        self.events = [
            event(provider_id="1", status=SportsEventStatus.SCHEDULED),
            event(provider_id="2", status=SportsEventStatus.FINAL),
        ]
        self.requested_range: tuple[date, date] | None = None

    async def get_teams(self) -> list[Team]:
        return self.teams

    async def get_team(self, provider_team_id: str) -> Team:
        return next(team for team in self.teams if team.provider_team_id == provider_team_id)

    async def get_games(self, *, start_date: date, end_date: date) -> list[SportsEvent]:
        self.requested_range = (start_date, end_date)
        return self.events

    async def get_game(self, provider_event_id: str) -> SportsEvent:
        return next(event for event in self.events if event.provider_event_id == provider_event_id)


class CapturingSportsRepository(SportsRepository):
    """Sports repository test double that captures normalized inputs."""

    def __init__(self) -> None:
        self.teams: list[Team] = []
        self.events: list[SportsEvent] = []

    async def upsert_teams(self, teams: Sequence[Team]) -> int:
        self.teams = list(teams)
        return len(self.teams)

    async def upsert_events(self, events: Sequence[SportsEvent]) -> SportsUpsertResult:
        self.events = list(events)
        return SportsUpsertResult(teams=2, events=len(self.events))


def test_ingests_teams_and_bounded_events_with_status_counts() -> None:
    provider = StaticSportsProvider()
    repository = CapturingSportsRepository()
    service = SportsIngestionService(provider=provider, repository=repository)

    team_result = asyncio.run(service.ingest_teams())
    event_result = asyncio.run(
        service.ingest_events(
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
        )
    )

    assert team_result.fetched == team_result.persisted == 1
    assert provider.requested_range == (date(2026, 8, 1), date(2026, 8, 2))
    assert event_result.fetched == event_result.events_persisted == 2
    assert event_result.scheduled == 1
    assert event_result.final == 1
    assert event_result.teams_persisted == 2


def test_rejects_reversed_or_overly_broad_ranges_before_provider_call() -> None:
    provider = StaticSportsProvider()
    service = SportsIngestionService(
        provider=provider,
        repository=CapturingSportsRepository(),
    )

    with pytest.raises(ValueError, match="must not be after"):
        asyncio.run(
            service.ingest_events(
                start_date=date(2026, 8, 2),
                end_date=date(2026, 8, 1),
            )
        )
    with pytest.raises(ValueError, match="cannot exceed 31"):
        asyncio.run(
            service.ingest_events(
                start_date=date(2026, 1, 1),
                end_date=date(2026, 2, 1),
            )
        )

    assert provider.requested_range is None
