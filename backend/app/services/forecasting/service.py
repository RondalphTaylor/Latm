from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.forecasts import (
    EloConfiguration,
    ForecastPurpose,
    ForecastTargetInput,
    HistoricalGameInput,
)
from app.models.sports import SportsEventRecord
from app.services.forecasting.elo import ELO_FORMULA, EloForecastModel
from app.services.forecasting.repository import ForecastRepository

_MAX_FORECAST_RANGE_DAYS = 31


class ForecastRunResult(BaseModel):
    """Audit summary for one bounded local forecast run."""

    model_config = ConfigDict(frozen=True)

    model_name: str
    model_version: str
    purpose: ForecastPurpose
    start_date: date
    end_date: date
    examined: int = Field(ge=0)
    generated: int = Field(ge=0)
    persisted: int = Field(ge=0)
    training_games_seen: int = Field(ge=0)
    training_games_processed: int = Field(ge=0)
    skipped_tied_games: int = Field(ge=0)
    skipped_incomplete_games: int = Field(ge=0)


class BaseForecastService:
    """Coordinate deterministic Elo generation from local normalized events."""

    def __init__(
        self,
        *,
        repository: ForecastRepository,
        sports_provider_name: str,
        configuration: EloConfiguration | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._sports_provider_name = sports_provider_name
        self._configuration = configuration or EloConfiguration()
        self._clock = clock or (lambda: datetime.now(UTC))

    async def run(
        self,
        *,
        purpose: ForecastPurpose,
        start_date: date,
        end_date: date,
        event_id: UUID | None,
        limit: int,
        offset: int,
    ) -> ForecastRunResult:
        """Generate and append one bounded forecast batch without provider calls."""
        self._validate_date_range(start_date, end_date)
        run_at = self._clock()
        if run_at.tzinfo is None or run_at.utcoffset() is None:
            raise ValueError("forecast clock must return a timezone-aware datetime")

        targets = await self._repository.list_forecast_targets(
            provider_name=self._sports_provider_name,
            purpose=purpose,
            start_date=start_date,
            end_date=end_date,
            run_at=run_at,
            event_id=event_id,
            limit=limit,
            offset=offset,
        )
        model = EloForecastModel(self._configuration, generated_at=run_at)
        if not targets:
            return self._summary(
                model=model,
                purpose=purpose,
                start_date=start_date,
                end_date=end_date,
            )

        target_inputs = tuple(self._target_input(target, purpose, run_at) for target in targets)
        latest_cutoff = max(target.history_cutoff for target in target_inputs)
        history = await self._repository.list_final_history(
            provider_name=self._sports_provider_name,
            before=latest_cutoff,
        )
        forecasts = model.forecast_many(
            target_inputs,
            tuple(self._history_input(game) for game in history),
        )
        persisted = await self._repository.persist_forecasts(
            forecasts,
            configuration=self._configuration,
            formula=ELO_FORMULA,
        )
        last = forecasts[-1] if forecasts else None
        return self._summary(
            model=model,
            purpose=purpose,
            start_date=start_date,
            end_date=end_date,
            examined=len(targets),
            generated=len(forecasts),
            persisted=persisted,
            training_games_seen=last.training_games_seen if last is not None else 0,
            training_games_processed=last.training_games_processed if last is not None else 0,
            skipped_tied_games=last.skipped_tied_games if last is not None else 0,
            skipped_incomplete_games=last.skipped_incomplete_games if last is not None else 0,
        )

    @staticmethod
    def _target_input(
        record: SportsEventRecord,
        purpose: ForecastPurpose,
        run_at: datetime,
    ) -> ForecastTargetInput:
        cutoff = run_at if purpose is ForecastPurpose.OPERATIONAL else record.scheduled_start_time
        return ForecastTargetInput(
            event_id=record.id,
            scheduled_start_time=record.scheduled_start_time,
            home_team_id=record.home_team_id,
            away_team_id=record.away_team_id,
            event_status=record.status,
            purpose=purpose,
            history_cutoff=cutoff,
            source_last_seen_at=record.last_seen_at,
        )

    @staticmethod
    def _history_input(record: SportsEventRecord) -> HistoricalGameInput:
        return HistoricalGameInput(
            event_id=record.id,
            scheduled_start_time=record.scheduled_start_time,
            home_team_id=record.home_team_id,
            away_team_id=record.away_team_id,
            home_score=record.home_score,
            away_score=record.away_score,
            source_last_seen_at=record.last_seen_at,
        )

    @staticmethod
    def _validate_date_range(start_date: date, end_date: date) -> None:
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        if (end_date - start_date).days + 1 > _MAX_FORECAST_RANGE_DAYS:
            raise ValueError(
                f"forecast date range cannot exceed {_MAX_FORECAST_RANGE_DAYS} inclusive days"
            )

    @staticmethod
    def _summary(
        *,
        model: EloForecastModel,
        purpose: ForecastPurpose,
        start_date: date,
        end_date: date,
        examined: int = 0,
        generated: int = 0,
        persisted: int = 0,
        training_games_seen: int = 0,
        training_games_processed: int = 0,
        skipped_tied_games: int = 0,
        skipped_incomplete_games: int = 0,
    ) -> ForecastRunResult:
        return ForecastRunResult(
            model_name=model.configuration.model_name,
            model_version=model.model_version,
            purpose=purpose,
            start_date=start_date,
            end_date=end_date,
            examined=examined,
            generated=generated,
            persisted=persisted,
            training_games_seen=training_games_seen,
            training_games_processed=training_games_processed,
            skipped_tied_games=skipped_tied_games,
            skipped_incomplete_games=skipped_incomplete_games,
        )
