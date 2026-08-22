from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from app.domain.mlb_lineups import MlbLineupEntry, MlbProbablePitcher

Metric = Annotated[Decimal, Field(ge=Decimal("0"), decimal_places=6)]
Rate = Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"), decimal_places=6)]
_METRIC_QUANTUM = Decimal("0.000001")


def quantize_statcast_metric(value: Decimal) -> Decimal:
    """Quantize derived Statcast metrics with one documented rounding rule."""
    return value.quantize(_METRIC_QUANTUM, rounding=ROUND_HALF_EVEN)


class MlbStatcastPlayerRole(StrEnum):
    """Player identity used to select official Statcast rows."""

    BATTER = "batter"
    PITCHER = "pitcher"


class MlbStatcastObservationBasis(StrEnum):
    """Whether the quantitative source was actually retrieved before first pitch."""

    OPERATIONAL_PREGAME = "operational_pregame"
    RETROSPECTIVE = "retrospective"


class MlbStatcastPitchObservation(BaseModel):
    """Typed, bounded subset of one official Baseball Savant pitch row."""

    model_config = ConfigDict(frozen=True)

    query_role: MlbStatcastPlayerRole
    game_pk: int = Field(gt=0)
    game_date: date
    game_type: str = Field(pattern=r"^[RFDLW]$")
    batter_id: str = Field(min_length=1, max_length=100)
    pitcher_id: str = Field(min_length=1, max_length=100)
    at_bat_number: int = Field(ge=1)
    pitch_number: int = Field(ge=1)
    event: str | None = Field(default=None, max_length=100)
    description: str = Field(min_length=1, max_length=100)
    result_type: str = Field(min_length=1, max_length=10)
    release_speed_mph: Decimal | None = Field(default=None, ge=0, le=120)
    release_spin_rate_rpm: Decimal | None = Field(default=None, ge=0, le=5000)
    launch_speed_mph: Decimal | None = Field(default=None, ge=0, le=130)
    launch_angle_degrees: Decimal | None = Field(default=None, ge=-90, le=90)
    launch_speed_angle: int | None = Field(default=None, ge=1, le=6)
    estimated_woba_on_contact: Decimal | None = Field(default=None, ge=0, le=5)
    woba_value: Decimal | None = Field(default=None, ge=0, le=5)
    woba_denom: Decimal | None = Field(default=None, ge=0, le=1)


class MlbStatcastPlayerFeatures(BaseModel):
    """Deterministic rolling-window quantitative features for one lineup player."""

    model_config = ConfigDict(frozen=True)

    role: MlbStatcastPlayerRole
    provider_player_id: str = Field(min_length=1, max_length=100)
    full_name: str = Field(min_length=1, max_length=200)
    pitch_count: int = Field(ge=0)
    plate_appearance_count: int = Field(ge=0)
    batted_ball_event_count: int = Field(ge=0)
    source_game_count: int = Field(ge=0)
    first_game_date: date | None = None
    last_game_date: date | None = None
    release_speed_sample_size: int = Field(ge=0)
    average_release_speed_mph: Metric | None = None
    spin_rate_sample_size: int = Field(ge=0)
    average_release_spin_rate_rpm: Metric | None = None
    exit_velocity_sample_size: int = Field(ge=0)
    average_exit_velocity_mph: Metric | None = None
    hard_hit_count: int = Field(ge=0)
    hard_hit_rate: Rate | None = None
    launch_quality_sample_size: int = Field(ge=0)
    barrel_count: int = Field(ge=0)
    barrel_rate: Rate | None = None
    estimated_woba_contact_sample_size: int = Field(ge=0)
    average_estimated_woba_on_contact: Metric | None = None
    complete_woba_sample_size: int = Field(ge=0)
    incomplete_woba_sample_size: int = Field(ge=0)
    woba_numerator: Metric
    woba_denominator: Metric
    observed_woba: Metric | None = None

    @staticmethod
    def _validate_average(count: int, value: Decimal | None, name: str) -> None:
        if (count == 0) != (value is None):
            raise ValueError(f"{name} must be null exactly when its sample size is zero")

    @model_validator(mode="after")
    def validate_counts_and_rates(self) -> Self:
        """Reconcile every derived metric to its explicit denominator."""
        for count in (
            self.plate_appearance_count,
            self.batted_ball_event_count,
            self.release_speed_sample_size,
            self.spin_rate_sample_size,
            self.exit_velocity_sample_size,
            self.launch_quality_sample_size,
            self.estimated_woba_contact_sample_size,
            self.complete_woba_sample_size,
            self.incomplete_woba_sample_size,
        ):
            if count > self.pitch_count:
                raise ValueError("feature sample counts cannot exceed pitch_count")
        if self.hard_hit_count > self.exit_velocity_sample_size:
            raise ValueError("hard_hit_count cannot exceed its sample size")
        if self.barrel_count > self.launch_quality_sample_size:
            raise ValueError("barrel_count cannot exceed its sample size")
        if self.complete_woba_sample_size + self.incomplete_woba_sample_size > self.pitch_count:
            raise ValueError("wOBA source counts cannot exceed pitch_count")
        self._validate_average(
            self.release_speed_sample_size,
            self.average_release_speed_mph,
            "average_release_speed_mph",
        )
        self._validate_average(
            self.spin_rate_sample_size,
            self.average_release_spin_rate_rpm,
            "average_release_spin_rate_rpm",
        )
        self._validate_average(
            self.exit_velocity_sample_size,
            self.average_exit_velocity_mph,
            "average_exit_velocity_mph",
        )
        self._validate_average(
            self.estimated_woba_contact_sample_size,
            self.average_estimated_woba_on_contact,
            "average_estimated_woba_on_contact",
        )
        expected_hard_hit_rate = (
            None
            if self.exit_velocity_sample_size == 0
            else quantize_statcast_metric(
                Decimal(self.hard_hit_count) / Decimal(self.exit_velocity_sample_size)
            )
        )
        expected_barrel_rate = (
            None
            if self.launch_quality_sample_size == 0
            else quantize_statcast_metric(
                Decimal(self.barrel_count) / Decimal(self.launch_quality_sample_size)
            )
        )
        expected_woba = (
            None
            if self.woba_denominator == 0
            else quantize_statcast_metric(self.woba_numerator / self.woba_denominator)
        )
        if self.hard_hit_rate != expected_hard_hit_rate:
            raise ValueError("hard_hit_rate does not reconcile")
        if self.barrel_rate != expected_barrel_rate:
            raise ValueError("barrel_rate does not reconcile")
        if self.observed_woba != expected_woba:
            raise ValueError("observed_woba does not reconcile")
        if self.pitch_count == 0:
            if self.source_game_count != 0 or self.first_game_date is not None:
                raise ValueError("empty profiles cannot claim source games")
            if self.last_game_date is not None:
                raise ValueError("empty profiles cannot claim source dates")
        elif (
            self.source_game_count == 0
            or self.first_game_date is None
            or self.last_game_date is None
        ):
            raise ValueError("nonempty profiles require source-game provenance")
        if (
            self.first_game_date is not None
            and self.last_game_date is not None
            and self.first_game_date > self.last_game_date
        ):
            raise ValueError("first_game_date cannot follow last_game_date")
        if self.role is MlbStatcastPlayerRole.BATTER and (
            self.release_speed_sample_size != 0 or self.spin_rate_sample_size != 0
        ):
            raise ValueError("batter profiles cannot expose opponent pitch-arsenal averages")
        return self


class MlbStatcastFeaturePolicy(BaseModel):
    """Versioned deterministic source-window and aggregation policy."""

    model_config = ConfigDict(frozen=True)

    policy_name: str = Field(default="mlb_statcast_pregame_features", min_length=1, max_length=100)
    policy_version: str = Field(default="v1", min_length=1, max_length=50)
    lookback_days: int = Field(default=30, ge=1, le=90)
    hard_hit_threshold_mph: Decimal = Field(default=Decimal("95"), gt=0, le=130)
    allowed_game_types: tuple[str, ...] = ("R", "F", "D", "L", "W")

    @field_validator("allowed_game_types")
    @classmethod
    def game_types_must_be_unique_and_supported(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) != len(set(value)) or not set(value) <= set("RFDLW"):
            raise ValueError("allowed_game_types must be a unique supported nonempty set")
        return value


class MlbStatcastFeatureInput(BaseModel):
    """Exact event, lineup, and official source rows evaluated by the feature engine."""

    model_config = ConfigDict(frozen=True)

    sports_event_id: UUID
    lineup_snapshot_id: UUID
    provider_event_id: str = Field(min_length=1, max_length=100)
    target_event_date: date
    scheduled_start_time: datetime
    lineup_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    home_probable_pitcher: MlbProbablePitcher
    away_probable_pitcher: MlbProbablePitcher
    home_lineup: tuple[MlbLineupEntry, ...]
    away_lineup: tuple[MlbLineupEntry, ...]
    pitcher_rows: tuple[MlbStatcastPitchObservation, ...]
    batter_rows: tuple[MlbStatcastPitchObservation, ...]
    pitcher_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    batter_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_retrieved_at: datetime
    policy: MlbStatcastFeaturePolicy

    @field_validator("scheduled_start_time", "source_retrieved_at")
    @classmethod
    def datetimes_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Statcast snapshot datetimes must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_lineage_and_source_roles(self) -> Self:
        if len(self.home_lineup) != 9 or len(self.away_lineup) != 9:
            raise ValueError("Statcast snapshots require two posted nine-player lineups")
        if any(row.query_role is not MlbStatcastPlayerRole.PITCHER for row in self.pitcher_rows):
            raise ValueError("pitcher_rows must contain only pitcher query observations")
        if any(row.query_role is not MlbStatcastPlayerRole.BATTER for row in self.batter_rows):
            raise ValueError("batter_rows must contain only batter query observations")
        return self


class MlbStatcastFeatureSnapshot(BaseModel):
    """Append-only pregame quantitative snapshot with complete source lineage."""

    model_config = ConfigDict(frozen=True)

    sports_event_id: UUID
    lineup_snapshot_id: UUID
    provider_name: str = Field(pattern=r"^baseball_savant$")
    provider_event_id: str = Field(min_length=1, max_length=100)
    target_event_date: date
    scheduled_start_time: datetime
    window_start_date: date
    window_end_date: date
    lookback_days: int = Field(ge=1, le=90)
    source_retrieved_at: datetime
    observation_basis: MlbStatcastObservationBasis
    operational_pregame_eligible: bool
    policy_name: str = Field(min_length=1, max_length=100)
    policy_version: str = Field(min_length=1, max_length=100)
    policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    home_starting_pitcher: MlbStatcastPlayerFeatures
    away_starting_pitcher: MlbStatcastPlayerFeatures
    home_batters: tuple[MlbStatcastPlayerFeatures, ...]
    away_batters: tuple[MlbStatcastPlayerFeatures, ...]
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_manifest: dict[str, JsonValue]
    source_rows: tuple[MlbStatcastPitchObservation, ...]

    @field_validator("scheduled_start_time", "source_retrieved_at")
    @classmethod
    def snapshot_datetimes_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Statcast snapshot datetimes must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_snapshot_contract(self) -> Self:
        expected_eligible = (
            self.observation_basis is MlbStatcastObservationBasis.OPERATIONAL_PREGAME
            and self.source_retrieved_at < self.scheduled_start_time
        )
        if self.operational_pregame_eligible is not expected_eligible:
            raise ValueError("operational eligibility must follow retrieval timing")
        if self.window_end_date >= self.target_event_date:
            raise ValueError("Statcast source window must end before the target game date")
        if (self.window_end_date - self.window_start_date).days + 1 != self.lookback_days:
            raise ValueError("Statcast source window must match lookback_days")
        if len(self.home_batters) != 9 or len(self.away_batters) != 9:
            raise ValueError("Statcast snapshots require exactly nine batter profiles per side")
        if self.home_starting_pitcher.role is not MlbStatcastPlayerRole.PITCHER:
            raise ValueError("home starting pitcher profile has the wrong role")
        if self.away_starting_pitcher.role is not MlbStatcastPlayerRole.PITCHER:
            raise ValueError("away starting pitcher profile has the wrong role")
        if any(profile.role is not MlbStatcastPlayerRole.BATTER for profile in self.home_batters):
            raise ValueError("home batting profiles have the wrong role")
        if any(profile.role is not MlbStatcastPlayerRole.BATTER for profile in self.away_batters):
            raise ValueError("away batting profiles have the wrong role")
        return self
