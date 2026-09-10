from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from app.domain.sports import SportsLeague

Confidence = Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"))]


class MarketEventMatchStatus(StrEnum):
    """Provider-neutral states for one market-to-event decision."""

    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    UNMATCHED = "unmatched"


class TeamAliasSource(StrEnum):
    """Auditable sources of deterministic team evidence."""

    FULL_NAME = "full_name"
    NICKNAME = "nickname"
    ABBREVIATION = "abbreviation"
    CURATED = "curated"
    CITY = "city"


class MatchingPolicy(BaseModel):
    """Versioned deterministic matching thresholds."""

    model_config = ConfigDict(frozen=True)

    matcher_version: str = Field(min_length=1, max_length=50)
    min_confidence: Confidence
    ambiguity_margin: Confidence
    time_window_hours: int = Field(ge=1, le=168)


class TeamMatchInput(BaseModel):
    """Normalized team fields used by the matcher."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    abbreviation: str = Field(min_length=2, max_length=10)
    city: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    full_name: str = Field(min_length=1, max_length=200)


class SportsEventMatchInput(BaseModel):
    """Normalized event fields used by the matcher."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    event_date: date
    scheduled_start_time: datetime
    home_team_id: UUID
    away_team_id: UUID
    last_seen_at: datetime

    @field_validator("scheduled_start_time", "last_seen_at")
    @classmethod
    def datetimes_must_be_timezone_aware(cls, value: datetime) -> datetime:
        """Reject ambiguous timestamps from matching inputs."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("matching datetimes must be timezone-aware")
        return value


class MarketMatchInput(BaseModel):
    """Normalized prediction-market fields used by the matcher."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    provider_name: str | None = None
    provider_market_id: str | None = None
    provider_event_id: str | None = None
    series_ticker: str | None = None
    league: SportsLeague = SportsLeague.NBA
    title: str = Field(min_length=1)
    subtitle: str | None = None
    rules_primary: str | None = None
    rules_secondary: str | None = None
    category: str | None = None
    market_type: str = Field(min_length=1, max_length=50)
    outcome_labels: tuple[str, ...] = ()
    occurrence_time: datetime | None = None
    close_time: datetime | None = None
    last_seen_at: datetime

    @field_validator("occurrence_time", "close_time", "last_seen_at")
    @classmethod
    def optional_datetimes_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        """Reject ambiguous market timestamps when present."""
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("matching datetimes must be timezone-aware")
        return value


class TeamSignal(BaseModel):
    """Strongest detected alias for one NBA team."""

    model_config = ConfigDict(frozen=True)

    team_id: UUID
    alias: str = Field(min_length=1, max_length=200)
    source: TeamAliasSource
    quality: Confidence


class CandidateScore(BaseModel):
    """Inspectible score for one plausible sports event."""

    model_config = ConfigDict(frozen=True)

    event_id: UUID
    scheduled_start_time: datetime
    home_team_id: UUID
    away_team_id: UUID
    team_score: Confidence
    temporal_score: Confidence
    confidence: Confidence
    time_delta_seconds: int | None = Field(default=None, ge=0)
    within_time_window: bool
    method: str = Field(min_length=1, max_length=50)


class MarketEventMatchDecision(BaseModel):
    """Reproducible, auditable result for one market snapshot."""

    model_config = ConfigDict(frozen=True)

    market_id: UUID
    league: SportsLeague = SportsLeague.NBA
    sports_event_id: UUID | None
    status: MarketEventMatchStatus
    confidence: Confidence
    method: str = Field(min_length=1, max_length=50)
    reason: str = Field(min_length=1, max_length=500)
    matcher_version: str = Field(min_length=1, max_length=50)
    min_confidence: Confidence
    ambiguity_margin: Confidence
    time_window_hours: int = Field(ge=1, le=168)
    automatic_trading_eligible: bool
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    team_signals: tuple[TeamSignal, ...]
    candidate_scores: tuple[CandidateScore, ...]
    evidence: dict[str, JsonValue]
    evaluated_at: datetime

    @field_validator("evaluated_at")
    @classmethod
    def evaluated_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        """Ensure audit timestamps are unambiguous."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluated_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_safety_invariants(self) -> Self:
        """Keep ambiguous and unmatched decisions ineligible by construction."""
        if self.status is MarketEventMatchStatus.MATCHED:
            if self.sports_event_id is None:
                raise ValueError("matched decisions require a sports_event_id")
            if self.confidence < self.min_confidence:
                raise ValueError("matched decisions must meet min_confidence")
            expected_eligibility = self.league is SportsLeague.NBA
            if self.automatic_trading_eligible is not expected_eligibility:
                raise ValueError("matched decision eligibility must follow the league safety gate")
        else:
            if self.sports_event_id is not None:
                raise ValueError("ambiguous and unmatched decisions cannot select an event")
            if self.automatic_trading_eligible:
                raise ValueError("ambiguous and unmatched decisions cannot be eligible")
        return self
