from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Probability = Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"))]
NonNegativeCount = Annotated[int, Field(ge=0)]
NonNegativeScore = Annotated[int, Field(ge=0)]


class ForecastPurpose(StrEnum):
    """Contexts that must remain distinguishable in forecast history."""

    OPERATIONAL = "operational"
    HISTORICAL_REPLAY = "historical_replay"


class EloConfiguration(BaseModel):
    """Immutable parameters for one effective Elo model version."""

    model_config = ConfigDict(frozen=True)

    model_name: str = "nba_elo"
    code_version: str = "1.0.0"
    formula_version: str = "standard_elo_logistic_v1"
    initialization_strategy: str = "equal_rating"
    initial_rating: Decimal = Field(default=Decimal("1500"), ge=Decimal("0"), le=Decimal("5000"))
    k_factor: Decimal = Field(default=Decimal("20"), gt=Decimal("0"), le=Decimal("100"))
    logistic_scale: Decimal = Field(default=Decimal("400"), gt=Decimal("0"), le=Decimal("1000"))
    home_court_advantage: Decimal = Field(
        default=Decimal("100"), ge=Decimal("0"), le=Decimal("500")
    )


class HistoricalGameInput(BaseModel):
    """Locally persisted final game supplied to chronological replay."""

    model_config = ConfigDict(frozen=True)

    event_id: UUID
    scheduled_start_time: datetime
    home_team_id: UUID
    away_team_id: UUID
    home_score: NonNegativeScore | None
    away_score: NonNegativeScore | None
    source_last_seen_at: datetime

    @field_validator("scheduled_start_time", "source_last_seen_at")
    @classmethod
    def datetimes_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("forecast input datetimes must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_game(self) -> Self:
        if self.home_team_id == self.away_team_id:
            raise ValueError("historical game teams must be distinct")
        if (self.home_score is None) != (self.away_score is None):
            raise ValueError("historical scores must both be present or absent")
        return self


class ForecastTargetInput(BaseModel):
    """Normalized event and cutoff used to create a pregame forecast."""

    model_config = ConfigDict(frozen=True)

    event_id: UUID
    scheduled_start_time: datetime
    home_team_id: UUID
    away_team_id: UUID
    event_status: str = Field(min_length=1, max_length=30)
    purpose: ForecastPurpose
    history_cutoff: datetime
    source_last_seen_at: datetime

    @field_validator("scheduled_start_time", "history_cutoff", "source_last_seen_at")
    @classmethod
    def datetimes_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("forecast input datetimes must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_teams(self) -> Self:
        if self.home_team_id == self.away_team_id:
            raise ValueError("forecast target teams must be distinct")
        return self


class BaseForecast(BaseModel):
    """Deterministic event-level pregame probability with replay audit state."""

    model_config = ConfigDict(frozen=True)

    sports_event_id: UUID
    home_team_id: UUID
    away_team_id: UUID
    home_win_probability: Probability
    away_win_probability: Probability
    home_team_rating: Decimal
    away_team_rating: Decimal
    adjusted_rating_difference: Decimal
    model_name: str = Field(min_length=1, max_length=50)
    model_version: str = Field(min_length=1, max_length=100)
    configuration_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_event_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_data_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    purpose: ForecastPurpose
    training_games_seen: NonNegativeCount
    training_games_processed: NonNegativeCount
    skipped_tied_games: NonNegativeCount
    skipped_incomplete_games: NonNegativeCount
    home_prior_games: NonNegativeCount
    away_prior_games: NonNegativeCount
    latest_training_event_time: datetime | None
    forecast_as_of: datetime
    source_event_last_seen_at: datetime
    generated_at: datetime

    @field_validator(
        "latest_training_event_time",
        "forecast_as_of",
        "source_event_last_seen_at",
        "generated_at",
    )
    @classmethod
    def datetimes_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("forecast datetimes must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_probability_and_teams(self) -> Self:
        if self.home_team_id == self.away_team_id:
            raise ValueError("forecast teams must be distinct")
        if self.home_win_probability + self.away_win_probability != Decimal("1"):
            raise ValueError("home and away probabilities must sum to one")
        if self.training_games_processed > self.training_games_seen:
            raise ValueError("processed games cannot exceed seen games")
        return self
