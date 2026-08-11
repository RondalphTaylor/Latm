from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from itertools import batched
from uuid import UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlalchemy.sql.selectable import Subquery

from app.domain.forecasts import BaseForecast, EloConfiguration, ForecastPurpose
from app.models.forecasts import BaseForecastRecord, ModelVersionRecord
from app.models.matching import MarketEventMatchRecord
from app.models.sports import SportsEventRecord

_LATM_FORECAST_NAMESPACE = UUID("afde0c75-a962-45f3-89fc-253491dbdfd9")
_FORECAST_INSERT_BATCH_SIZE = 500


def model_version_record_id(model_name: str, model_version: str) -> UUID:
    """Return a stable registry ID for one effective model identity."""
    return uuid5(_LATM_FORECAST_NAMESPACE, f"model:{model_name}:{model_version}")


def forecast_record_id(forecast: BaseForecast) -> UUID:
    """Return a stable ID for one event/model/purpose/input combination."""
    return uuid5(
        _LATM_FORECAST_NAMESPACE,
        f"forecast:{forecast.sports_event_id}:{forecast.model_version}:"
        f"{forecast.purpose.value}:{forecast.input_fingerprint}",
    )


class ForecastRepository:
    """Read local event history and persist append-only base forecasts."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _latest_match_ranking() -> Subquery:
        return select(
            MarketEventMatchRecord.sports_event_id.label("sports_event_id"),
            MarketEventMatchRecord.automatic_trading_eligible.label("eligible"),
            func.row_number()
            .over(
                partition_by=MarketEventMatchRecord.market_id,
                order_by=(
                    MarketEventMatchRecord.evaluated_at.desc(),
                    MarketEventMatchRecord.id.desc(),
                ),
            )
            .label("row_number"),
        ).subquery()

    async def list_forecast_targets(
        self,
        *,
        provider_name: str,
        purpose: ForecastPurpose,
        start_date: date,
        end_date: date,
        run_at: datetime,
        event_id: UUID | None,
        limit: int,
        offset: int,
    ) -> list[SportsEventRecord]:
        """Return a bounded deterministic target set from local event snapshots."""
        statement = select(SportsEventRecord).where(
            SportsEventRecord.provider_name == provider_name,
            SportsEventRecord.league == "nba",
            SportsEventRecord.event_date >= start_date,
            SportsEventRecord.event_date <= end_date,
            SportsEventRecord.postponed.is_(False),
        )
        if purpose is ForecastPurpose.OPERATIONAL:
            ranked = self._latest_match_ranking()
            eligible_event_ids = select(ranked.c.sports_event_id).where(
                ranked.c.row_number == 1,
                ranked.c.eligible.is_(True),
                ranked.c.sports_event_id.is_not(None),
            )
            statement = statement.where(
                SportsEventRecord.status == "scheduled",
                SportsEventRecord.scheduled_start_time > run_at,
                SportsEventRecord.id.in_(eligible_event_ids),
            )
        else:
            statement = statement.where(
                SportsEventRecord.status == "final",
                SportsEventRecord.home_score.is_not(None),
                SportsEventRecord.away_score.is_not(None),
                SportsEventRecord.home_score != SportsEventRecord.away_score,
            )
        if event_id is not None:
            statement = statement.where(SportsEventRecord.id == event_id)
        statement = (
            statement.order_by(
                SportsEventRecord.scheduled_start_time,
                SportsEventRecord.id,
            )
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.scalars(statement)
        return list(result.all())

    async def list_final_history(
        self,
        *,
        provider_name: str,
        before: datetime,
    ) -> list[SportsEventRecord]:
        """Return final local NBA games before a strict chronological cutoff."""
        statement = (
            select(SportsEventRecord)
            .where(
                SportsEventRecord.provider_name == provider_name,
                SportsEventRecord.league == "nba",
                SportsEventRecord.status == "final",
                SportsEventRecord.postponed.is_(False),
                SportsEventRecord.scheduled_start_time < before,
            )
            .order_by(
                SportsEventRecord.scheduled_start_time,
                SportsEventRecord.id,
            )
        )
        result = await self._session.scalars(statement)
        return list(result.all())

    async def persist_forecasts(
        self,
        forecasts: Sequence[BaseForecast],
        *,
        configuration: EloConfiguration,
        formula: str,
    ) -> int:
        """Ensure immutable model metadata and insert new semantic forecasts atomically."""
        if not forecasts:
            return 0
        first = forecasts[0]
        if any(
            forecast.model_name != first.model_name
            or forecast.model_version != first.model_version
            or forecast.configuration_fingerprint != first.configuration_fingerprint
            for forecast in forecasts
        ):
            raise ValueError("forecast batch must use one effective model configuration")

        model_id = model_version_record_id(first.model_name, first.model_version)
        model_values = {
            "id": model_id,
            "model_name": first.model_name,
            "model_version": first.model_version,
            "algorithm": "elo",
            "configuration": configuration.model_dump(mode="json"),
            "configuration_fingerprint": first.configuration_fingerprint,
            "formula": formula,
            "description": "Deterministic NBA Elo base probability; no market prices or AI evidence",
            "created_at": first.generated_at,
        }
        inserted = 0
        try:
            await self._session.execute(
                insert(ModelVersionRecord)
                .values(model_values)
                .on_conflict_do_nothing(constraint="uq_model_versions_identity")
            )
            existing = await self._session.scalar(
                select(ModelVersionRecord).where(ModelVersionRecord.id == model_id)
            )
            if existing is None or (
                existing.configuration_fingerprint != first.configuration_fingerprint
            ):
                raise ValueError("model version identity conflicts with persisted configuration")

            for batch in batched(forecasts, _FORECAST_INSERT_BATCH_SIZE, strict=False):
                statement = (
                    insert(BaseForecastRecord)
                    .values(
                        [
                            self._forecast_values(forecast, model_id, configuration)
                            for forecast in batch
                        ]
                    )
                    .on_conflict_do_nothing(constraint="uq_base_forecasts_semantic_input")
                    .returning(BaseForecastRecord.id)
                )
                result = await self._session.scalars(statement)
                inserted += len(result.all())
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        return inserted

    @staticmethod
    def _forecast_values(
        forecast: BaseForecast,
        model_version_id: UUID,
        configuration: EloConfiguration,
    ) -> dict[str, object]:
        features: dict[str, object] = {
            "model_configuration": configuration.model_dump(mode="json"),
            "configuration_fingerprint": forecast.configuration_fingerprint,
            "source_event_fingerprint": forecast.source_event_fingerprint,
            "training_data_fingerprint": forecast.training_data_fingerprint,
            "home_team_rating": str(forecast.home_team_rating),
            "away_team_rating": str(forecast.away_team_rating),
            "adjusted_rating_difference": str(forecast.adjusted_rating_difference),
            "home_prior_games": forecast.home_prior_games,
            "away_prior_games": forecast.away_prior_games,
            "home_cold_start": forecast.home_prior_games == 0,
            "away_cold_start": forecast.away_prior_games == 0,
        }
        return {
            "id": forecast_record_id(forecast),
            "sports_event_id": forecast.sports_event_id,
            "model_version_id": model_version_id,
            "purpose": forecast.purpose.value,
            "home_team_id": forecast.home_team_id,
            "away_team_id": forecast.away_team_id,
            "home_win_probability": forecast.home_win_probability,
            "away_win_probability": forecast.away_win_probability,
            "home_team_rating": forecast.home_team_rating,
            "away_team_rating": forecast.away_team_rating,
            "adjusted_rating_difference": forecast.adjusted_rating_difference,
            "training_data_fingerprint": forecast.training_data_fingerprint,
            "input_fingerprint": forecast.input_fingerprint,
            "input_features": features,
            "training_games_seen": forecast.training_games_seen,
            "training_games_processed": forecast.training_games_processed,
            "skipped_tied_games": forecast.skipped_tied_games,
            "skipped_incomplete_games": forecast.skipped_incomplete_games,
            "home_prior_games": forecast.home_prior_games,
            "away_prior_games": forecast.away_prior_games,
            "latest_training_event_time": forecast.latest_training_event_time,
            "forecast_as_of": forecast.forecast_as_of,
            "source_event_last_seen_at": forecast.source_event_last_seen_at,
            "generated_at": forecast.generated_at,
        }

    async def list_forecasts(
        self,
        *,
        latest_only: bool,
        purpose: ForecastPurpose | None,
        sports_event_id: UUID | None,
        model_name: str | None,
        model_version: str | None,
        limit: int,
        offset: int,
    ) -> list[BaseForecastRecord]:
        """Return forecast history with deterministic latest-per-model semantics."""
        if latest_only:
            ranked = select(
                BaseForecastRecord.id.label("forecast_id"),
                func.row_number()
                .over(
                    partition_by=(
                        BaseForecastRecord.sports_event_id,
                        BaseForecastRecord.model_version_id,
                        BaseForecastRecord.purpose,
                    ),
                    order_by=(
                        BaseForecastRecord.generated_at.desc(),
                        BaseForecastRecord.id.desc(),
                    ),
                )
                .label("row_number"),
            ).subquery()
            statement = select(BaseForecastRecord).join(
                ranked,
                BaseForecastRecord.id == ranked.c.forecast_id,
            )
            statement = statement.where(ranked.c.row_number == 1)
        else:
            statement = select(BaseForecastRecord)

        statement = statement.join(ModelVersionRecord).options(
            joinedload(BaseForecastRecord.model_version)
        )
        if purpose is not None:
            statement = statement.where(BaseForecastRecord.purpose == purpose.value)
        if sports_event_id is not None:
            statement = statement.where(BaseForecastRecord.sports_event_id == sports_event_id)
        if model_name is not None:
            statement = statement.where(ModelVersionRecord.model_name == model_name)
        if model_version is not None:
            statement = statement.where(ModelVersionRecord.model_version == model_version)
        statement = (
            statement.order_by(
                BaseForecastRecord.generated_at.desc(),
                BaseForecastRecord.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.scalars(statement)
        return list(result.unique().all())

    async def get_forecast(self, forecast_id: UUID) -> BaseForecastRecord | None:
        """Return one forecast snapshot with its immutable model metadata."""
        statement = (
            select(BaseForecastRecord)
            .where(BaseForecastRecord.id == forecast_id)
            .options(joinedload(BaseForecastRecord.model_version))
        )
        result = await self._session.scalars(statement)
        return result.unique().one_or_none()

    async def list_model_versions(self) -> list[ModelVersionRecord]:
        """Return registered forecasting configurations."""
        result = await self._session.scalars(
            select(ModelVersionRecord).order_by(
                ModelVersionRecord.model_name,
                ModelVersionRecord.created_at,
            )
        )
        return list(result.all())
