from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

NonNegativeScore = Annotated[int, Field(ge=0)]


class SportsLeague(StrEnum):
    """Leagues supported by the normalized sports-data layer."""

    NBA = "nba"
    MLB = "mlb"


class SportsEventStatus(StrEnum):
    """Provider-neutral lifecycle states for a sports event."""

    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    FINAL = "final"
    POSTPONED = "postponed"
    CANCELED = "canceled"
    UNKNOWN = "unknown"


class Team(BaseModel):
    """Provider-independent sports team."""

    model_config = ConfigDict(frozen=True)

    provider_name: str = Field(min_length=1, max_length=50)
    provider_team_id: str = Field(min_length=1, max_length=100)
    league: SportsLeague = SportsLeague.NBA
    abbreviation: str = Field(min_length=2, max_length=10)
    city: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    full_name: str = Field(min_length=1, max_length=200)
    conference: str | None = Field(default=None, max_length=50)
    division: str | None = Field(default=None, max_length=100)
    raw_data: dict[str, JsonValue]
    retrieved_at: datetime


class SportsEvent(BaseModel):
    """Provider-independent game with reproducible source metadata."""

    model_config = ConfigDict(frozen=True)

    provider_name: str = Field(min_length=1, max_length=50)
    provider_event_id: str = Field(min_length=1, max_length=100)
    league: SportsLeague = SportsLeague.NBA
    season: int = Field(ge=1946, le=2200)
    event_date: date
    scheduled_start_time: datetime
    status: SportsEventStatus
    status_detail: str = Field(min_length=1, max_length=100)
    period: int = Field(ge=0)
    clock: str | None = Field(default=None, max_length=50)
    postseason: bool
    postponed: bool
    tournament_stage: str | None = Field(default=None, max_length=100)
    home_team: Team
    away_team: Team
    home_score: NonNegativeScore | None = None
    away_score: NonNegativeScore | None = None
    venue: str | None = Field(default=None, max_length=300)
    raw_data: dict[str, JsonValue]
    retrieved_at: datetime

    @field_validator("scheduled_start_time")
    @classmethod
    def scheduled_start_must_be_timezone_aware(cls, value: datetime) -> datetime:
        """Reject ambiguous provider datetimes that cannot support matching."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("scheduled_start_time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_teams_and_scores(self) -> Self:
        """Require distinct teams and complete final-score pairs."""
        home_identity = (self.home_team.provider_name, self.home_team.provider_team_id)
        away_identity = (self.away_team.provider_name, self.away_team.provider_team_id)
        if home_identity == away_identity:
            raise ValueError("home and away teams must be distinct")
        if (self.home_score is None) != (self.away_score is None):
            raise ValueError("home and away scores must both be present or absent")
        if self.status is SportsEventStatus.FINAL and self.home_score is None:
            raise ValueError("final events require scores")
        return self
