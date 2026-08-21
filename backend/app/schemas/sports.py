from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.sports import SportsEventRecord, TeamRecord


class TeamResponse(BaseModel):
    """Normalized sports team returned by the API."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    provider_name: str
    provider_team_id: str
    league: str
    abbreviation: str
    city: str
    name: str
    full_name: str
    conference: str | None
    division: str | None
    first_seen_at: datetime
    last_seen_at: datetime

    @classmethod
    def from_record(cls, record: TeamRecord) -> TeamResponse:
        """Build a stable team response without exposing raw provider fields."""
        return cls(
            id=record.id,
            provider_name=record.provider_name,
            provider_team_id=record.provider_team_id,
            league=record.league,
            abbreviation=record.abbreviation,
            city=record.city,
            name=record.name,
            full_name=record.full_name,
            conference=record.conference,
            division=record.division,
            first_seen_at=record.first_seen_at,
            last_seen_at=record.last_seen_at,
        )


class SportsEventResponse(BaseModel):
    """Normalized sports event returned by the API."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    provider_name: str
    provider_event_id: str
    league: str
    season: int
    event_date: date
    scheduled_start_time: datetime
    status: str
    status_detail: str
    period: int
    clock: str | None
    postseason: bool
    postponed: bool
    tournament_stage: str | None
    home_team: TeamResponse
    away_team: TeamResponse
    home_score: int | None
    away_score: int | None
    venue: str | None
    first_seen_at: datetime
    last_seen_at: datetime

    @classmethod
    def from_record(cls, record: SportsEventRecord) -> SportsEventResponse:
        """Build a stable event response with provider-neutral team naming."""
        return cls(
            id=record.id,
            provider_name=record.provider_name,
            provider_event_id=record.provider_event_id,
            league=record.league,
            season=record.season,
            event_date=record.event_date,
            scheduled_start_time=record.scheduled_start_time,
            status=record.status,
            status_detail=record.status_detail,
            period=record.period,
            clock=record.clock,
            postseason=record.postseason,
            postponed=record.postponed,
            tournament_stage=record.tournament_stage,
            home_team=TeamResponse.from_record(record.home_team),
            away_team=TeamResponse.from_record(record.away_team),
            home_score=record.home_score,
            away_score=record.away_score,
            venue=record.venue,
            first_seen_at=record.first_seen_at,
            last_seen_at=record.last_seen_at,
        )


class TeamIngestionResponse(BaseModel):
    """Summary returned after sports-team ingestion."""

    model_config = ConfigDict(frozen=True)

    provider: str
    fetched: int
    persisted: int


class EventIngestionResponse(BaseModel):
    """Summary returned after bounded sports-event ingestion."""

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
