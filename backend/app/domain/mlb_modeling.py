from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.mlb_statcast import (
    MlbStatcastObservationBasis,
    MlbStatcastPlayerFeatures,
    MlbStatcastPlayerRole,
)

Metric = Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("5"), decimal_places=6)]
Difference = Annotated[Decimal, Field(ge=Decimal("-5"), le=Decimal("5"), decimal_places=6)]


class MlbSelectedFeatureName(StrEnum):
    """Fixed candidate features whose positive direction always favors the home team."""

    LINEUP_OBSERVED_WOBA_DIFFERENCE = "lineup_observed_woba_difference"
    LINEUP_EXPECTED_WOBA_CONTACT_DIFFERENCE = "lineup_expected_woba_contact_difference"
    LINEUP_HARD_HIT_RATE_DIFFERENCE = "lineup_hard_hit_rate_difference"
    LINEUP_BARREL_RATE_DIFFERENCE = "lineup_barrel_rate_difference"
    STARTER_OBSERVED_WOBA_ALLOWED_DIFFERENCE = "starting_pitcher_observed_woba_allowed_difference"
    STARTER_EXPECTED_WOBA_CONTACT_ALLOWED_DIFFERENCE = (
        "starting_pitcher_expected_woba_contact_allowed_difference"
    )
    STARTER_HARD_HIT_RATE_ALLOWED_DIFFERENCE = "starting_pitcher_hard_hit_rate_allowed_difference"
    STARTER_BARREL_RATE_ALLOWED_DIFFERENCE = "starting_pitcher_barrel_rate_allowed_difference"


SELECTED_MLB_FEATURES = tuple(MlbSelectedFeatureName)


class MlbDatasetSplit(StrEnum):
    """Chronological role assigned without random shuffling."""

    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"
    PROSPECTIVE_HOLDOUT = "prospective_holdout"


class MlbFeatureSelectionPolicy(BaseModel):
    """Versioned, conservative selection and missing-data policy."""

    model_config = ConfigDict(frozen=True)

    policy_name: str = "mlb_pregame_feature_selection"
    policy_version: str = "v1"
    model_candidate_name: str = "mlb_pregame_regularized_logistic"
    selected_features: tuple[MlbSelectedFeatureName, ...] = SELECTED_MLB_FEATURES
    required_lineup_batter_coverage: int = Field(default=9, ge=1, le=9)
    pooling_policy: Literal["sample_weighted"] = "sample_weighted"
    missing_value_policy: Literal["no_imputation"] = "no_imputation"
    difference_orientation: Literal["positive_favors_home"] = "positive_favors_home"

    @model_validator(mode="after")
    def fixed_v1_feature_set(self) -> Self:
        if self.selected_features != SELECTED_MLB_FEATURES:
            raise ValueError("MLB feature-selection V1 requires its exact ordered feature set")
        return self


class MlbModelFeatureInput(BaseModel):
    """Exact Statcast snapshot projection supplied to deterministic feature selection."""

    model_config = ConfigDict(frozen=True)

    sports_event_id: UUID
    lineup_snapshot_id: UUID
    statcast_snapshot_id: UUID
    provider_event_id: str = Field(min_length=1, max_length=100)
    target_event_date: date
    scheduled_start_time: datetime
    home_team_id: UUID
    away_team_id: UUID
    source_retrieved_at: datetime
    source_observation_basis: MlbStatcastObservationBasis
    source_operational_pregame_eligible: bool
    statcast_policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    statcast_source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    statcast_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    home_starting_pitcher: MlbStatcastPlayerFeatures
    away_starting_pitcher: MlbStatcastPlayerFeatures
    home_batters: tuple[MlbStatcastPlayerFeatures, ...]
    away_batters: tuple[MlbStatcastPlayerFeatures, ...]
    built_at: datetime
    policy: MlbFeatureSelectionPolicy

    @field_validator("scheduled_start_time", "source_retrieved_at", "built_at")
    @classmethod
    def aware_datetimes(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("MLB feature datetimes must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_identity_and_source(self) -> Self:
        if self.home_team_id == self.away_team_id:
            raise ValueError("MLB feature teams must be distinct")
        if len(self.home_batters) != 9 or len(self.away_batters) != 9:
            raise ValueError("MLB feature selection requires two nine-player lineups")
        if (
            self.home_starting_pitcher.role is not MlbStatcastPlayerRole.PITCHER
            or self.away_starting_pitcher.role is not MlbStatcastPlayerRole.PITCHER
        ):
            raise ValueError("MLB starting-pitcher inputs must have pitcher role")
        if any(
            profile.role is not MlbStatcastPlayerRole.BATTER
            for profile in (*self.home_batters, *self.away_batters)
        ):
            raise ValueError("MLB lineup inputs must have batter role")
        player_ids = [
            self.home_starting_pitcher.provider_player_id,
            self.away_starting_pitcher.provider_player_id,
            *(profile.provider_player_id for profile in self.home_batters),
            *(profile.provider_player_id for profile in self.away_batters),
        ]
        if len(player_ids) != len(set(player_ids)):
            raise ValueError("MLB feature inputs require 20 distinct player identities")
        if self.source_operational_pregame_eligible != (
            self.source_observation_basis is MlbStatcastObservationBasis.OPERATIONAL_PREGAME
            and self.source_retrieved_at < self.scheduled_start_time
        ):
            raise ValueError("Statcast source eligibility is inconsistent")
        return self


class MlbLineupModelMetrics(BaseModel):
    """Pooled lineup metrics retained before home-minus-away transformation."""

    model_config = ConfigDict(frozen=True)

    observed_woba: Metric | None = None
    average_expected_woba_on_contact: Metric | None = None
    hard_hit_rate: Metric | None = None
    barrel_rate: Metric | None = None


class MlbStartingPitcherModelMetrics(BaseModel):
    """Starting-pitcher allowed-contact metrics retained in source orientation."""

    model_config = ConfigDict(frozen=True)

    observed_woba_allowed: Metric | None = None
    average_expected_woba_on_contact_allowed: Metric | None = None
    hard_hit_rate_allowed: Metric | None = None
    barrel_rate_allowed: Metric | None = None


class MlbMatchupSourceMetrics(BaseModel):
    """Auditable side-specific metrics from which selected differences are derived."""

    model_config = ConfigDict(frozen=True)

    home_lineup: MlbLineupModelMetrics
    away_lineup: MlbLineupModelMetrics
    home_starting_pitcher: MlbStartingPitcherModelMetrics
    away_starting_pitcher: MlbStartingPitcherModelMetrics


class MlbSideFeatureCoverage(BaseModel):
    """Explicit denominators and player coverage for one side."""

    model_config = ConfigDict(frozen=True)

    lineup_player_count: int = Field(ge=0, le=9)
    lineup_players_with_observed_woba: int = Field(ge=0, le=9)
    lineup_players_with_expected_woba_contact: int = Field(ge=0, le=9)
    lineup_players_with_hard_hit_rate: int = Field(ge=0, le=9)
    lineup_players_with_barrel_rate: int = Field(ge=0, le=9)
    lineup_plate_appearance_count: int = Field(ge=0)
    lineup_complete_woba_sample_size: int = Field(ge=0)
    lineup_incomplete_woba_sample_size: int = Field(ge=0)
    lineup_expected_woba_contact_sample_size: int = Field(ge=0)
    lineup_exit_velocity_sample_size: int = Field(ge=0)
    lineup_launch_quality_sample_size: int = Field(ge=0)
    starting_pitcher_pitch_count: int = Field(ge=0)
    starting_pitcher_plate_appearance_count: int = Field(ge=0)
    starting_pitcher_complete_woba_sample_size: int = Field(ge=0)
    starting_pitcher_incomplete_woba_sample_size: int = Field(ge=0)
    starting_pitcher_expected_woba_contact_sample_size: int = Field(ge=0)
    starting_pitcher_exit_velocity_sample_size: int = Field(ge=0)
    starting_pitcher_launch_quality_sample_size: int = Field(ge=0)


class MlbMatchupFeatureCoverage(BaseModel):
    """Source coverage for both teams and starters."""

    model_config = ConfigDict(frozen=True)

    home: MlbSideFeatureCoverage
    away: MlbSideFeatureCoverage


class MlbSelectedFeatureValues(BaseModel):
    """Ordered candidate model values; every positive value favors the home team."""

    model_config = ConfigDict(frozen=True)

    lineup_observed_woba_difference: Difference | None = None
    lineup_expected_woba_contact_difference: Difference | None = None
    lineup_hard_hit_rate_difference: Difference | None = None
    lineup_barrel_rate_difference: Difference | None = None
    starting_pitcher_observed_woba_allowed_difference: Difference | None = None
    starting_pitcher_expected_woba_contact_allowed_difference: Difference | None = None
    starting_pitcher_hard_hit_rate_allowed_difference: Difference | None = None
    starting_pitcher_barrel_rate_allowed_difference: Difference | None = None

    def ordered_values(self) -> tuple[Decimal | None, ...]:
        return tuple(getattr(self, feature.value) for feature in SELECTED_MLB_FEATURES)


class MlbGameFeatureVector(BaseModel):
    """Append-only candidate input vector that deliberately emits no probability."""

    model_config = ConfigDict(frozen=True)

    sports_event_id: UUID
    lineup_snapshot_id: UUID
    statcast_snapshot_id: UUID
    provider_event_id: str
    target_event_date: date
    scheduled_start_time: datetime
    home_team_id: UUID
    away_team_id: UUID
    source_retrieved_at: datetime
    source_observation_basis: MlbStatcastObservationBasis
    built_at: datetime
    feature_availability_basis: MlbStatcastObservationBasis
    policy_name: str
    policy_version: str
    model_candidate_name: str
    policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_metrics: MlbMatchupSourceMetrics
    coverage: MlbMatchupFeatureCoverage
    feature_values: MlbSelectedFeatureValues
    missing_features: tuple[MlbSelectedFeatureName, ...]
    complete_feature_vector: bool
    operational_model_input_eligible: bool
    research_only: Literal[True] = True
    probability_generated: Literal[False] = False
    automatic_trading_eligible: Literal[False] = False
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator(
        "scheduled_start_time",
        "source_retrieved_at",
        "built_at",
    )
    @classmethod
    def vector_datetimes_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("MLB feature-vector datetimes must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_safety_contract(self) -> Self:
        expected_missing = tuple(
            feature
            for feature, value in zip(
                SELECTED_MLB_FEATURES,
                self.feature_values.ordered_values(),
                strict=True,
            )
            if value is None
        )
        if self.missing_features != expected_missing:
            raise ValueError("missing_features must match null selected feature values")
        if self.complete_feature_vector != (not expected_missing):
            raise ValueError("complete_feature_vector must follow selected-feature missingness")
        expected_basis = (
            MlbStatcastObservationBasis.OPERATIONAL_PREGAME
            if self.source_observation_basis is MlbStatcastObservationBasis.OPERATIONAL_PREGAME
            and self.source_retrieved_at < self.scheduled_start_time
            and self.built_at < self.scheduled_start_time
            else MlbStatcastObservationBasis.RETROSPECTIVE
        )
        if self.feature_availability_basis is not expected_basis:
            raise ValueError("feature availability basis is inconsistent")
        expected_eligible = (
            self.complete_feature_vector
            and expected_basis is MlbStatcastObservationBasis.OPERATIONAL_PREGAME
        )
        if self.operational_model_input_eligible != expected_eligible:
            raise ValueError("operational model-input eligibility is inconsistent")
        return self


class MlbChronologicalDatasetPolicy(BaseModel):
    """Explicit, immutable time boundaries for train/validation/test/holdout roles."""

    model_config = ConfigDict(frozen=True)

    policy_name: str = "mlb_chronological_dataset_split"
    policy_version: str = "v1"
    validation_start: datetime
    test_start: datetime
    prospective_holdout_start: datetime
    ordering: Literal["scheduled_start_time_then_event_id"] = "scheduled_start_time_then_event_id"
    random_shuffle: Literal[False] = False

    @field_validator("validation_start", "test_start", "prospective_holdout_start")
    @classmethod
    def split_boundaries_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("MLB dataset split boundaries must be timezone-aware")
        return value

    @model_validator(mode="after")
    def boundaries_are_strictly_ordered(self) -> Self:
        if not self.validation_start < self.test_start < self.prospective_holdout_start:
            raise ValueError("MLB dataset boundaries must be strictly chronological")
        return self


class MlbOfficialOutcomeInput(BaseModel):
    """Official completed-game result used only to label a pregame vector."""

    model_config = ConfigDict(frozen=True)

    sports_event_id: UUID
    scheduled_start_time: datetime
    status: str
    home_score: int | None = Field(default=None, ge=0)
    away_score: int | None = Field(default=None, ge=0)
    source_last_seen_at: datetime

    @field_validator("scheduled_start_time", "source_last_seen_at")
    @classmethod
    def outcome_datetimes_are_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("MLB outcome datetimes must be timezone-aware")
        return value


class MlbLabeledFeatureExample(BaseModel):
    """Pure dataset contract; persistence and model fitting remain deferred."""

    model_config = ConfigDict(frozen=True)

    sports_event_id: UUID
    feature_vector_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    availability_basis: MlbStatcastObservationBasis
    scheduled_start_time: datetime
    home_won: bool
    split: MlbDatasetSplit
    split_policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    example_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
