from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter

from app.domain.forecasts import ForecastPurpose
from app.models.forecasts import BaseForecastRecord, ModelVersionRecord

_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JsonValue])


class ModelVersionResponse(BaseModel):
    """Registered immutable forecasting configuration."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    model_name: str
    model_version: str
    algorithm: str
    configuration: dict[str, JsonValue]
    configuration_fingerprint: str
    formula: str
    description: str
    created_at: datetime

    @classmethod
    def from_record(cls, record: ModelVersionRecord) -> ModelVersionResponse:
        return cls(
            id=record.id,
            model_name=record.model_name,
            model_version=record.model_version,
            algorithm=record.algorithm,
            configuration=_JSON_OBJECT_ADAPTER.validate_python(record.configuration),
            configuration_fingerprint=record.configuration_fingerprint,
            formula=record.formula,
            description=record.description,
            created_at=record.created_at,
        )


class BaseForecastResponse(BaseModel):
    """One reproducible event-level probability snapshot."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    sports_event_id: UUID
    purpose: ForecastPurpose
    home_team_id: UUID
    away_team_id: UUID
    home_win_probability: Decimal
    away_win_probability: Decimal
    home_team_rating: Decimal
    away_team_rating: Decimal
    adjusted_rating_difference: Decimal
    training_data_fingerprint: str
    input_fingerprint: str
    input_features: dict[str, JsonValue]
    training_games_seen: int
    training_games_processed: int
    skipped_tied_games: int
    skipped_incomplete_games: int
    home_prior_games: int
    away_prior_games: int
    latest_training_event_time: datetime | None
    forecast_as_of: datetime
    source_event_last_seen_at: datetime
    generated_at: datetime
    model: ModelVersionResponse

    @classmethod
    def from_record(cls, record: BaseForecastRecord) -> BaseForecastResponse:
        return cls(
            id=record.id,
            sports_event_id=record.sports_event_id,
            purpose=ForecastPurpose(record.purpose),
            home_team_id=record.home_team_id,
            away_team_id=record.away_team_id,
            home_win_probability=record.home_win_probability,
            away_win_probability=record.away_win_probability,
            home_team_rating=record.home_team_rating,
            away_team_rating=record.away_team_rating,
            adjusted_rating_difference=record.adjusted_rating_difference,
            training_data_fingerprint=record.training_data_fingerprint,
            input_fingerprint=record.input_fingerprint,
            input_features=_JSON_OBJECT_ADAPTER.validate_python(record.input_features),
            training_games_seen=record.training_games_seen,
            training_games_processed=record.training_games_processed,
            skipped_tied_games=record.skipped_tied_games,
            skipped_incomplete_games=record.skipped_incomplete_games,
            home_prior_games=record.home_prior_games,
            away_prior_games=record.away_prior_games,
            latest_training_event_time=record.latest_training_event_time,
            forecast_as_of=record.forecast_as_of,
            source_event_last_seen_at=record.source_event_last_seen_at,
            generated_at=record.generated_at,
            model=ModelVersionResponse.from_record(record.model_version),
        )


class ForecastRunResponse(BaseModel):
    """Counts returned by a bounded local forecast run."""

    model_config = ConfigDict(frozen=True)

    model_name: str
    model_version: str
    purpose: ForecastPurpose
    start_date: date
    end_date: date
    examined: int
    generated: int
    persisted: int
    training_games_seen: int
    training_games_processed: int
    skipped_tied_games: int
    skipped_incomplete_games: int
