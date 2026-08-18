from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter

from app.domain.forecast_evaluation import (
    ForecastCalibrationReport,
    ModelEvaluationSummary,
    PairedModelComparison,
)
from app.domain.forecasts import ForecastPurpose
from app.domain.trading_evaluation import TradingPerformanceEvaluation
from app.models.evaluation import ForecastEvaluationRecord
from app.schemas.forecasts import ModelVersionResponse
from app.services.evaluation.service import (
    ForecastEvaluationRunResult,
    ForecastPerformanceResult,
)

_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JsonValue])


class ForecastEvaluationResponse(BaseModel):
    """One immutable forecast score against a frozen normalized game result."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    base_forecast_id: UUID
    sports_event_id: UUID
    model_version_id: UUID
    home_team_id: UUID
    away_team_id: UUID
    purpose: ForecastPurpose
    event_date: date
    scheduled_start_time: datetime
    forecast_as_of: datetime
    forecast_generated_at: datetime
    outcome_source_last_seen_at: datetime
    home_win_probability: Decimal
    predicted_home_win: bool | None
    observed_home_win: bool
    home_score: int
    away_score: int
    brier_score: Decimal
    correct: bool | None
    evaluator_name: str
    evaluator_version: str
    evaluator_fingerprint: str
    outcome_fingerprint: str
    input_fingerprint: str
    source_snapshot: dict[str, JsonValue]
    evaluated_at: datetime
    model: ModelVersionResponse

    @classmethod
    def from_record(cls, record: ForecastEvaluationRecord) -> ForecastEvaluationResponse:
        return cls(
            id=record.id,
            base_forecast_id=record.base_forecast_id,
            sports_event_id=record.sports_event_id,
            model_version_id=record.model_version_id,
            home_team_id=record.home_team_id,
            away_team_id=record.away_team_id,
            purpose=ForecastPurpose(record.purpose),
            event_date=record.event_date,
            scheduled_start_time=record.result_scheduled_start_time,
            forecast_as_of=record.forecast_as_of,
            forecast_generated_at=record.forecast_generated_at,
            outcome_source_last_seen_at=record.result_source_last_seen_at,
            home_win_probability=record.home_win_probability,
            predicted_home_win=record.predicted_home_win,
            observed_home_win=record.home_won,
            home_score=record.result_home_score,
            away_score=record.result_away_score,
            brier_score=record.brier_score,
            correct=record.correct,
            evaluator_name=record.policy_name,
            evaluator_version=record.policy_version,
            evaluator_fingerprint=record.policy_fingerprint,
            outcome_fingerprint=record.outcome_fingerprint,
            input_fingerprint=record.input_fingerprint,
            source_snapshot=_JSON_OBJECT_ADAPTER.validate_python(record.audit_snapshot),
            evaluated_at=record.evaluated_at,
            model=ModelVersionResponse.from_record(record.model_version),
        )


class ForecastEvaluationRunResponse(BaseModel):
    """Counts and scoring identity for one bounded evaluation materialization."""

    model_config = ConfigDict(frozen=True)

    purpose: ForecastPurpose
    start_date: date
    end_date: date
    examined: int
    eligible: int
    persisted: int
    replayed: int
    skip_counts: dict[str, int]
    evaluator_name: str
    evaluator_version: str
    evaluator_fingerprint: str

    @classmethod
    def from_result(cls, result: ForecastEvaluationRunResult) -> ForecastEvaluationRunResponse:
        return cls(**result.__dict__)


class ForecastModelPerformanceResponse(BaseModel):
    """Current canonical score and calibration metrics for one model version."""

    model_config = ConfigDict(frozen=True)

    summary: ModelEvaluationSummary
    calibration: ForecastCalibrationReport


class ForecastPerformanceResponse(BaseModel):
    """Purpose-separated current performance for all requested model versions."""

    model_config = ConfigDict(frozen=True)

    purpose: ForecastPurpose
    evaluation_count: int
    unique_event_count: int
    model_count: int
    models: tuple[ForecastModelPerformanceResponse, ...]
    evaluator_name: str
    evaluator_version: str
    evaluator_fingerprint: str
    warnings: tuple[str, ...]

    @classmethod
    def from_result(cls, result: ForecastPerformanceResult) -> ForecastPerformanceResponse:
        return cls(
            purpose=result.purpose,
            evaluation_count=result.evaluation_count,
            unique_event_count=result.unique_event_count,
            model_count=result.model_count,
            models=tuple(
                ForecastModelPerformanceResponse(
                    summary=item.summary,
                    calibration=item.calibration,
                )
                for item in result.models
            ),
            evaluator_name=result.evaluator_name,
            evaluator_version=result.evaluator_version,
            evaluator_fingerprint=result.evaluator_fingerprint,
            warnings=result.warnings,
        )


class TradingPerformanceResponse(TradingPerformanceEvaluation):
    """Read-only ledger-derived paper-trading performance response."""


class PairedModelComparisonResponse(BaseModel):
    """Paired model comparison plus purpose-specific interpretation warnings."""

    model_config = ConfigDict(frozen=True)

    comparison: PairedModelComparison
    warnings: tuple[str, ...]
