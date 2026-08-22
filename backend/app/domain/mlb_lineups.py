from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


class MlbLineupState(StrEnum):
    """Availability of one official batting order observation."""

    UNAVAILABLE = "unavailable"
    PARTIAL = "partial"
    POSTED = "posted"


class MlbObservationPhase(StrEnum):
    """Game phase at which official pregame information was observed."""

    PREGAME = "pregame"
    LIVE = "live"
    POSTGAME = "postgame"


class MlbProbablePitcher(BaseModel):
    """Typed official probable-pitcher identity."""

    model_config = ConfigDict(frozen=True)

    provider_player_id: str = Field(min_length=1, max_length=100)
    full_name: str = Field(min_length=1, max_length=200)
    pitch_hand: str | None = Field(default=None, pattern=r"^[LRS]$")


class MlbLineupEntry(BaseModel):
    """One player in an official batting-order observation."""

    model_config = ConfigDict(frozen=True)

    batting_order: int = Field(ge=1, le=9)
    provider_player_id: str = Field(min_length=1, max_length=100)
    full_name: str = Field(min_length=1, max_length=200)
    position: str = Field(min_length=1, max_length=10)
    bat_side: str | None = Field(default=None, pattern=r"^[LRS]$")


class MlbLineupSnapshot(BaseModel):
    """Immutable typed subset of one official MLB game-feed observation."""

    model_config = ConfigDict(frozen=True)

    provider_name: str = Field(pattern=r"^mlb$")
    provider_event_id: str = Field(min_length=1, max_length=100)
    home_provider_team_id: str = Field(min_length=1, max_length=100)
    away_provider_team_id: str = Field(min_length=1, max_length=100)
    scheduled_start_time: datetime
    source_updated_at: datetime
    retrieved_at: datetime
    source_abstract_state: str = Field(min_length=1, max_length=30)
    source_detailed_state: str = Field(min_length=1, max_length=100)
    observation_phase: MlbObservationPhase
    home_probable_pitcher: MlbProbablePitcher | None = None
    away_probable_pitcher: MlbProbablePitcher | None = None
    home_lineup_state: MlbLineupState
    away_lineup_state: MlbLineupState
    home_lineup: tuple[MlbLineupEntry, ...]
    away_lineup: tuple[MlbLineupEntry, ...]
    complete_for_pregame_model: bool
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_snapshot: dict[str, JsonValue]

    @field_validator("scheduled_start_time", "source_updated_at", "retrieved_at")
    @classmethod
    def datetimes_must_be_timezone_aware(cls, value: datetime) -> datetime:
        """Reject ambiguous source and observation timestamps."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("MLB lineup snapshot datetimes must be timezone-aware")
        return value

    @staticmethod
    def _validate_lineup(
        lineup: tuple[MlbLineupEntry, ...],
        state: MlbLineupState,
    ) -> None:
        expected_state = (
            MlbLineupState.UNAVAILABLE
            if not lineup
            else MlbLineupState.POSTED
            if len(lineup) == 9
            else MlbLineupState.PARTIAL
        )
        if state is not expected_state:
            raise ValueError("lineup state must match the observed player count")
        orders = [entry.batting_order for entry in lineup]
        players = [entry.provider_player_id for entry in lineup]
        if len(orders) != len(set(orders)) or len(players) != len(set(players)):
            raise ValueError("lineup orders and player identities must be unique")
        if state is MlbLineupState.POSTED and sorted(orders) != list(range(1, 10)):
            raise ValueError("posted lineups require batting-order slots 1 through 9")

    @model_validator(mode="after")
    def validate_availability_and_timing(self) -> Self:
        """Bind completeness to two posted lineups, pitchers, and pregame timing."""
        self._validate_lineup(self.home_lineup, self.home_lineup_state)
        self._validate_lineup(self.away_lineup, self.away_lineup_state)
        expected_complete = (
            self.observation_phase is MlbObservationPhase.PREGAME
            and self.source_updated_at <= self.retrieved_at
            and self.source_updated_at < self.scheduled_start_time
            and self.retrieved_at < self.scheduled_start_time
            and self.home_lineup_state is MlbLineupState.POSTED
            and self.away_lineup_state is MlbLineupState.POSTED
            and self.home_probable_pitcher is not None
            and self.away_probable_pitcher is not None
        )
        if self.complete_for_pregame_model is not expected_complete:
            raise ValueError("pregame completeness must follow source availability and timing")
        return self
