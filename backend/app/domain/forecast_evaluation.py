from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from app.domain.forecasts import ForecastPurpose

Probability = Annotated[
    Decimal,
    Field(ge=Decimal("0"), le=Decimal("1"), max_digits=7, decimal_places=6),
]
UnitMetric = Annotated[
    Decimal,
    Field(ge=Decimal("0"), le=Decimal("1"), max_digits=13, decimal_places=12),
]
SignedUnitMetric = Annotated[
    Decimal,
    Field(ge=Decimal("-1"), le=Decimal("1"), max_digits=13, decimal_places=12),
]


class ForecastEvaluationPolicy(BaseModel):
    """Versioned assumptions shared by scoring, calibration, and comparison."""

    model_config = ConfigDict(frozen=True)

    policy_name: str = "binary_home_brier"
    code_version: str = "1.0.0"
    formula_version: str = "binary_home_brier_calibration_comparison_v1"
    calibration_bin_count: int = Field(default=10, ge=2, le=50)


class ForecastEvaluationInput(BaseModel):
    """One immutable forecast and one completed provider-result observation."""

    model_config = ConfigDict(frozen=True)

    forecast_id: UUID
    sports_event_id: UUID
    model_version_id: UUID
    model_name: str = Field(min_length=1, max_length=50)
    model_version: str = Field(min_length=1, max_length=100)
    purpose: ForecastPurpose
    forecast_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_configuration_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    home_team_id: UUID
    away_team_id: UUID
    home_win_probability: Probability
    forecast_as_of: datetime
    forecast_generated_at: datetime
    result_provider_name: str = Field(min_length=1, max_length=50)
    result_league: str = Field(min_length=1, max_length=20)
    result_status: str = Field(pattern=r"^final$")
    result_postponed: bool
    result_event_date: date
    result_scheduled_start_time: datetime
    result_home_team_id: UUID
    result_away_team_id: UUID
    result_home_score: int = Field(ge=0)
    result_away_score: int = Field(ge=0)
    result_source_last_seen_at: datetime
    evaluated_at: datetime

    @field_validator(
        "forecast_as_of",
        "forecast_generated_at",
        "result_scheduled_start_time",
        "result_source_last_seen_at",
        "evaluated_at",
    )
    @classmethod
    def datetimes_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("forecast-evaluation datetimes must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_completed_pregame_observation(self) -> Self:
        if self.home_team_id == self.away_team_id:
            raise ValueError("forecast teams must be distinct")
        if self.result_home_team_id == self.result_away_team_id:
            raise ValueError("result teams must be distinct")
        if (
            self.home_team_id != self.result_home_team_id
            or self.away_team_id != self.result_away_team_id
        ):
            raise ValueError("forecast and result team orientation must match")
        if self.result_home_score == self.result_away_score:
            raise ValueError("tied final scores cannot produce an NBA binary outcome")
        if self.result_postponed:
            raise ValueError("postponed result semantics are not evaluation eligible")
        if self.purpose is ForecastPurpose.OPERATIONAL:
            if self.forecast_as_of != self.forecast_generated_at:
                raise ValueError("operational forecast as-of time must equal generation time")
            if self.forecast_as_of >= self.result_scheduled_start_time:
                raise ValueError("operational forecasts must be as-of strictly before tip")
            if self.forecast_generated_at >= self.result_scheduled_start_time:
                raise ValueError("operational forecasts must be generated strictly before tip")
        else:
            if self.forecast_as_of != self.result_scheduled_start_time:
                raise ValueError("historical replay forecasts must use scheduled tip as cutoff")
            if self.forecast_generated_at < self.forecast_as_of:
                raise ValueError("historical replay generation cannot precede its cutoff")
        if self.forecast_generated_at > self.evaluated_at:
            raise ValueError("forecast generation cannot be after evaluation")
        if self.result_source_last_seen_at > self.evaluated_at:
            raise ValueError("result observation cannot be after evaluation")
        return self


class ForecastEvaluation(BaseModel):
    """Exact immutable binary-home score for one forecast and result assertion."""

    model_config = ConfigDict(frozen=True)

    forecast_id: UUID
    sports_event_id: UUID
    model_version_id: UUID
    model_name: str
    model_version: str
    purpose: ForecastPurpose
    home_win_probability: Probability
    home_won: bool
    result_home_score: int = Field(ge=0)
    result_away_score: int = Field(ge=0)
    brier_score: UnitMetric
    predicted_home_win: bool | None
    prediction_correct: bool | None
    result_scheduled_start_time: datetime
    result_source_last_seen_at: datetime
    outcome_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_name: str
    policy_version: str
    policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluated_at: datetime
    audit_snapshot: dict[str, JsonValue]

    @field_validator(
        "result_scheduled_start_time",
        "result_source_last_seen_at",
        "evaluated_at",
    )
    @classmethod
    def datetimes_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("forecast-evaluation datetimes must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_score_and_accuracy(self) -> Self:
        if self.result_home_score == self.result_away_score:
            raise ValueError("evaluations require a decisive result")
        if self.home_won != (self.result_home_score > self.result_away_score):
            raise ValueError("home outcome must reproduce from final scores")
        outcome = Decimal("1") if self.home_won else Decimal("0")
        expected_brier = (self.home_win_probability - outcome) ** 2
        if self.brier_score != expected_brier:
            raise ValueError("Brier score must equal the squared binary-home error")
        expected_prediction = (
            None
            if self.home_win_probability == Decimal("0.5")
            else self.home_win_probability > Decimal("0.5")
        )
        expected_correct = (
            None if expected_prediction is None else expected_prediction is self.home_won
        )
        if self.predicted_home_win is not expected_prediction:
            raise ValueError("predicted outcome must use strict 0.5 threshold abstention")
        if self.prediction_correct is not expected_correct:
            raise ValueError("accuracy result does not match prediction and outcome")
        return self


class ForecastCalibrationBin(BaseModel):
    """One fixed-width reliability bin, including an explicit empty-bin shape."""

    model_config = ConfigDict(frozen=True)

    index: int = Field(ge=0)
    lower_bound: UnitMetric
    upper_bound: UnitMetric
    upper_bound_inclusive: bool
    sample_size: int = Field(ge=0)
    home_wins: int = Field(ge=0)
    mean_prediction: UnitMetric | None
    observed_frequency: UnitMetric | None
    signed_calibration_gap: SignedUnitMetric | None
    absolute_calibration_gap: UnitMetric | None
    mean_brier_score: UnitMetric | None

    @model_validator(mode="after")
    def validate_bin_shape(self) -> Self:
        metrics = (
            self.mean_prediction,
            self.observed_frequency,
            self.signed_calibration_gap,
            self.absolute_calibration_gap,
            self.mean_brier_score,
        )
        if self.home_wins > self.sample_size:
            raise ValueError("calibration-bin wins cannot exceed sample size")
        if self.sample_size == 0 and any(value is not None for value in metrics):
            raise ValueError("empty calibration bins require null metrics")
        if self.sample_size > 0 and any(value is None for value in metrics):
            raise ValueError("nonempty calibration bins require all metrics")
        if self.lower_bound >= self.upper_bound:
            raise ValueError("calibration-bin bounds must be ordered")
        return self


class ForecastCalibrationReport(BaseModel):
    """Reliability table and aggregate calibration error for one model group."""

    model_config = ConfigDict(frozen=True)

    model_version_id: UUID | None
    model_name: str | None
    model_version: str | None
    purpose: ForecastPurpose | None
    sample_size: int = Field(ge=0)
    bin_count: int = Field(ge=2, le=50)
    mean_brier_score: UnitMetric | None
    expected_calibration_error: UnitMetric | None
    maximum_calibration_error: UnitMetric | None
    bins: tuple[ForecastCalibrationBin, ...]
    policy_version: str
    policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_report_shape(self) -> Self:
        if len(self.bins) != self.bin_count:
            raise ValueError("calibration report must contain every configured bin")
        if sum(item.sample_size for item in self.bins) != self.sample_size:
            raise ValueError("calibration-bin samples must reconcile to report total")
        metrics = (
            self.mean_brier_score,
            self.expected_calibration_error,
            self.maximum_calibration_error,
        )
        identities = (self.model_version_id, self.model_name, self.model_version, self.purpose)
        if self.sample_size == 0:
            if any(value is not None for value in metrics):
                raise ValueError("empty calibration reports require null metrics")
            if any(value is not None for value in identities):
                raise ValueError("empty calibration reports require null model identity")
        elif any(value is None for value in metrics + identities):
            raise ValueError("nonempty calibration reports require metrics and model identity")
        return self


class ModelEvaluationSummary(BaseModel):
    """Descriptive score and calibration summary for one model and purpose."""

    model_config = ConfigDict(frozen=True)

    model_version_id: UUID
    model_name: str
    model_version: str
    purpose: ForecastPurpose
    sample_size: int = Field(ge=1)
    home_wins: int = Field(ge=0)
    decisive_prediction_count: int = Field(ge=0)
    correct_prediction_count: int = Field(ge=0)
    mean_brier_score: UnitMetric
    prediction_accuracy: UnitMetric | None
    expected_calibration_error: UnitMetric
    maximum_calibration_error: UnitMetric
    policy_version: str
    policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_summary_counts(self) -> Self:
        if self.home_wins > self.sample_size:
            raise ValueError("home wins cannot exceed model-summary sample size")
        if self.decisive_prediction_count > self.sample_size:
            raise ValueError("decisive predictions cannot exceed sample size")
        if self.correct_prediction_count > self.decisive_prediction_count:
            raise ValueError("correct predictions cannot exceed decisive predictions")
        if (self.decisive_prediction_count == 0) != (self.prediction_accuracy is None):
            raise ValueError("accuracy is null exactly when all predictions abstain")
        return self


class PairedModelComparison(BaseModel):
    """Brier comparison over the exact common event/result intersection."""

    model_config = ConfigDict(frozen=True)

    model_a_version_id: UUID
    model_b_version_id: UUID
    purpose: ForecastPurpose
    model_a_sample_size: int = Field(ge=0)
    model_b_sample_size: int = Field(ge=0)
    paired_sample_size: int = Field(ge=0)
    model_a_unpaired_count: int = Field(ge=0)
    model_b_unpaired_count: int = Field(ge=0)
    outcome_mismatch_count: int = Field(ge=0)
    model_a_mean_brier: UnitMetric | None
    model_b_mean_brier: UnitMetric | None
    mean_brier_delta_a_minus_b: SignedUnitMetric | None
    model_a_lower_brier_count: int = Field(ge=0)
    model_b_lower_brier_count: int = Field(ge=0)
    equal_brier_count: int = Field(ge=0)
    paired_event_ids: tuple[UUID, ...]
    policy_version: str
    policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_comparison_shape(self) -> Self:
        if self.model_a_version_id == self.model_b_version_id:
            raise ValueError("paired comparison requires distinct model versions")
        if len(self.paired_event_ids) != self.paired_sample_size:
            raise ValueError("paired event IDs must reconcile to paired sample size")
        if (
            self.model_a_lower_brier_count + self.model_b_lower_brier_count + self.equal_brier_count
            != self.paired_sample_size
        ):
            raise ValueError("paired win/tie counts must reconcile to paired sample size")
        metrics = (
            self.model_a_mean_brier,
            self.model_b_mean_brier,
            self.mean_brier_delta_a_minus_b,
        )
        if self.paired_sample_size == 0 and any(value is not None for value in metrics):
            raise ValueError("empty paired comparisons require null metrics")
        if self.paired_sample_size > 0 and any(value is None for value in metrics):
            raise ValueError("nonempty paired comparisons require all metrics")
        if self.model_a_unpaired_count != self.model_a_sample_size - self.paired_sample_size:
            raise ValueError("model A unpaired count does not reconcile")
        if self.model_b_unpaired_count != self.model_b_sample_size - self.paired_sample_size:
            raise ValueError("model B unpaired count does not reconcile")
        return self
