from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.mlb_modeling import (
    SELECTED_MLB_FEATURES,
    MlbChronologicalDatasetPolicy,
    MlbDatasetSplit,
    MlbMatchupFeatureCoverage,
    MlbSelectedFeatureName,
    MlbSelectedFeatureValues,
)
from app.domain.mlb_statcast import MlbStatcastObservationBasis


class MlbDatasetQualitySeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class MlbDatasetQualityPolicy(BaseModel):
    """Frozen checks for one canonical, research-only MLB dataset snapshot."""

    model_config = ConfigDict(frozen=True)

    policy_name: Literal["mlb_dataset_quality_audit"] = "mlb_dataset_quality_audit"
    policy_version: Literal["v1"] = "v1"
    selected_features: tuple[MlbSelectedFeatureName, ...] = SELECTED_MLB_FEATURES
    feature_statistic_scale: int = Field(default=12, ge=6, le=18)
    source_support_scale: int = Field(default=6, ge=0, le=12)
    canonical_selection: Literal[
        "one_per_event_prefer_operational_then_latest_vector_and_outcome"
    ] = "one_per_event_prefer_operational_then_latest_vector_and_outcome"
    missing_value_policy: Literal["no_imputation"] = "no_imputation"
    prospective_holdout_provenance: Literal["operational_pregame_only"] = "operational_pregame_only"
    research_only: Literal[True] = True
    probability_generation_enabled: Literal[False] = False
    automatic_trading_enabled: Literal[False] = False

    @model_validator(mode="after")
    def exact_features(self) -> Self:
        if self.selected_features != SELECTED_MLB_FEATURES:
            raise ValueError("MLB dataset-quality V1 requires the exact selected feature set")
        return self


class MlbDatasetQualityExample(BaseModel):
    """Exact canonical example projection supplied to the pure quality engine."""

    model_config = ConfigDict(frozen=True)

    example_id: UUID
    game_feature_vector_id: UUID
    sports_event_id: UUID
    scheduled_start_time: datetime
    home_team_id: UUID
    away_team_id: UUID
    split: MlbDatasetSplit
    availability_basis: MlbStatcastObservationBasis
    home_won: bool
    feature_values: MlbSelectedFeatureValues
    coverage: MlbMatchupFeatureCoverage
    feature_policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_vector_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    example_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_retrieved_at: datetime
    vector_built_at: datetime
    outcome_source_last_seen_at: datetime
    labeled_at: datetime
    complete_feature_vector: bool
    operational_model_input_eligible: bool
    vector_research_only: bool
    vector_probability_generated: bool
    vector_automatic_trading_eligible: bool
    research_only: bool
    probability_generated: bool
    automatic_trading_eligible: bool

    @field_validator(
        "scheduled_start_time",
        "source_retrieved_at",
        "vector_built_at",
        "outcome_source_last_seen_at",
        "labeled_at",
    )
    @classmethod
    def aware_datetimes(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("MLB dataset-quality datetimes must be timezone-aware")
        return value


class MlbDatasetQualityInput(BaseModel):
    """One exact canonical selection and the policies used to audit it."""

    model_config = ConfigDict(frozen=True)

    split_policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    split_policy: MlbChronologicalDatasetPolicy
    feature_policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    examples: tuple[MlbDatasetQualityExample, ...]
    policy: MlbDatasetQualityPolicy


class MlbDatasetQualityIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    severity: MlbDatasetQualitySeverity
    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=500)
    example_id: UUID | None = None
    sports_event_id: UUID | None = None
    split: MlbDatasetSplit | None = None
    feature: MlbSelectedFeatureName | None = None


class MlbDatasetNumericSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    count: int = Field(ge=0)
    minimum: Decimal | None = None
    median: Decimal | None = None
    mean: Decimal | None = None
    maximum: Decimal | None = None

    @model_validator(mode="after")
    def empty_is_null(self) -> Self:
        values = (self.minimum, self.median, self.mean, self.maximum)
        if self.count == 0 and any(value is not None for value in values):
            raise ValueError("empty numeric summaries must have null statistics")
        if self.count > 0 and any(value is None for value in values):
            raise ValueError("non-empty numeric summaries require every statistic")
        return self


class MlbFeatureQualitySummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    feature: MlbSelectedFeatureName
    example_count: int = Field(ge=0)
    available_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    mean: Decimal | None = None
    population_standard_deviation: Decimal | None = None
    zero_variance: bool

    @model_validator(mode="after")
    def counts_reconcile(self) -> Self:
        if self.available_count + self.missing_count != self.example_count:
            raise ValueError("feature quality counts must reconcile")
        if self.available_count == 0 and any(
            value is not None
            for value in (
                self.minimum,
                self.maximum,
                self.mean,
                self.population_standard_deviation,
            )
        ):
            raise ValueError("unavailable features cannot have statistics")
        return self


class MlbSplitQualitySummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    split: MlbDatasetSplit
    example_count: int = Field(ge=0)
    operational_example_count: int = Field(ge=0)
    retrospective_example_count: int = Field(ge=0)
    home_win_count: int = Field(ge=0)
    away_win_count: int = Field(ge=0)
    home_win_rate: Decimal | None = Field(default=None, ge=0, le=1)
    unique_team_count: int = Field(ge=0)
    first_scheduled_start_time: datetime | None = None
    last_scheduled_start_time: datetime | None = None

    @model_validator(mode="after")
    def counts_reconcile(self) -> Self:
        if self.operational_example_count + self.retrospective_example_count != self.example_count:
            raise ValueError("split provenance counts must reconcile")
        if self.home_win_count + self.away_win_count != self.example_count:
            raise ValueError("split outcome counts must reconcile")
        if (self.home_win_rate is None) != (self.example_count == 0):
            raise ValueError("split home-win rate must be null only for an empty split")
        if (self.first_scheduled_start_time is None) != (self.example_count == 0):
            raise ValueError("split date bounds must be null only for an empty split")
        if (self.last_scheduled_start_time is None) != (self.example_count == 0):
            raise ValueError("split date bounds must be null only for an empty split")
        return self


class MlbTeamCoverageSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    team_id: UUID
    appearance_count: int = Field(ge=1)
    home_game_count: int = Field(ge=0)
    away_game_count: int = Field(ge=0)

    @model_validator(mode="after")
    def appearances_reconcile(self) -> Self:
        if self.home_game_count + self.away_game_count != self.appearance_count:
            raise ValueError("team appearance counts must reconcile")
        return self


class MlbDatasetQualityReport(BaseModel):
    """Deterministic audit result; quality status grants no model or trading authority."""

    model_config = ConfigDict(frozen=True)

    policy_name: str
    policy_version: str
    policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    split_policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_data_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_example_count: int = Field(ge=0)
    operational_example_count: int = Field(ge=0)
    retrospective_example_count: int = Field(ge=0)
    unique_event_count: int = Field(ge=0)
    unique_team_count: int = Field(ge=0)
    home_win_count: int = Field(ge=0)
    away_win_count: int = Field(ge=0)
    home_win_rate: Decimal | None = Field(default=None, ge=0, le=1)
    first_scheduled_start_time: datetime | None = None
    last_scheduled_start_time: datetime | None = None
    split_summaries: dict[MlbDatasetSplit, MlbSplitQualitySummary]
    feature_summaries: dict[MlbSelectedFeatureName, MlbFeatureQualitySummary]
    minimum_side_source_support: dict[str, MlbDatasetNumericSummary]
    team_coverage: tuple[MlbTeamCoverageSummary, ...]
    issues: tuple[MlbDatasetQualityIssue, ...]
    error_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    quality_passed: bool
    research_only: Literal[True] = True
    probability_generation_enabled: Literal[False] = False
    automatic_trading_enabled: Literal[False] = False

    @model_validator(mode="after")
    def report_reconciles(self) -> Self:
        if self.operational_example_count + self.retrospective_example_count != (
            self.selected_example_count
        ):
            raise ValueError("quality report provenance counts must reconcile")
        if self.home_win_count + self.away_win_count != self.selected_example_count:
            raise ValueError("quality report outcome counts must reconcile")
        if self.unique_event_count > self.selected_example_count:
            raise ValueError("unique events cannot exceed selected examples")
        if self.unique_team_count != len(self.team_coverage):
            raise ValueError("team coverage count must reconcile")
        error_count = sum(
            issue.severity is MlbDatasetQualitySeverity.ERROR for issue in self.issues
        )
        warning_count = len(self.issues) - error_count
        if self.error_count != error_count or self.warning_count != warning_count:
            raise ValueError("quality issue counts must reconcile")
        if self.quality_passed != (self.error_count == 0):
            raise ValueError("quality_passed must mean that no error issue exists")
        if set(self.split_summaries) != set(MlbDatasetSplit):
            raise ValueError("quality report requires every chronological split")
        if set(self.feature_summaries) != set(SELECTED_MLB_FEATURES):
            raise ValueError("quality report requires every selected feature")
        return self
