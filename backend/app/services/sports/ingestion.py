from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel, ConfigDict

from app.domain.sports import SportsEventStatus
from app.providers.sports.base import SportsDataProvider
from app.services.sports.repository import SportsRepository

MAX_INGESTION_RANGE_DAYS = 31


def validate_ingestion_date_range(start_date: date, end_date: date) -> None:
    """Reject reversed or excessively broad provider requests."""
    if start_date > end_date:
        raise ValueError("start_date must not be after end_date")
    if end_date - start_date > timedelta(days=MAX_INGESTION_RANGE_DAYS - 1):
        raise ValueError(f"date range cannot exceed {MAX_INGESTION_RANGE_DAYS} inclusive days")


class TeamIngestionResult(BaseModel):
    """Auditable summary of one NBA-team ingestion run."""

    model_config = ConfigDict(frozen=True)

    provider: str
    fetched: int
    persisted: int


class EventIngestionResult(BaseModel):
    """Auditable summary of one bounded NBA-game ingestion run."""

    model_config = ConfigDict(frozen=True)

    provider: str
    start_date: date
    end_date: date
    fetched: int
    teams_persisted: int
    events_persisted: int
    scheduled: int
    in_progress: int
    final: int
    postponed: int
    canceled: int
    unknown: int


class SportsIngestionService:
    """Coordinate sports-provider retrieval and normalized persistence."""

    def __init__(
        self,
        *,
        provider: SportsDataProvider,
        repository: SportsRepository,
    ) -> None:
        self._provider = provider
        self._repository = repository

    async def ingest_teams(self) -> TeamIngestionResult:
        """Retrieve and persist all provider NBA teams."""
        teams = await self._provider.get_teams()
        persisted = await self._repository.upsert_teams(teams)
        return TeamIngestionResult(
            provider=self._provider.name,
            fetched=len(teams),
            persisted=persisted,
        )

    async def ingest_events(self, *, start_date: date, end_date: date) -> EventIngestionResult:
        """Retrieve and persist all games in an inclusive bounded range."""
        validate_ingestion_date_range(start_date, end_date)
        events = await self._provider.get_games(start_date=start_date, end_date=end_date)
        persisted = await self._repository.upsert_events(events)
        status_counts = {
            event_status: sum(event.status is event_status for event in events)
            for event_status in SportsEventStatus
        }
        return EventIngestionResult(
            provider=self._provider.name,
            start_date=start_date,
            end_date=end_date,
            fetched=len(events),
            teams_persisted=persisted.teams,
            events_persisted=persisted.events,
            scheduled=status_counts[SportsEventStatus.SCHEDULED],
            in_progress=status_counts[SportsEventStatus.IN_PROGRESS],
            final=status_counts[SportsEventStatus.FINAL],
            postponed=status_counts[SportsEventStatus.POSTPONED],
            canceled=status_counts[SportsEventStatus.CANCELED],
            unknown=status_counts[SportsEventStatus.UNKNOWN],
        )
