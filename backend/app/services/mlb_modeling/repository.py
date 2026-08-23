from __future__ import annotations

from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.mlb_modeling import MlbGameFeatureVector
from app.models.mlb import (
    MlbGameFeatureVectorRecord,
    MlbLineupSnapshotRecord,
    MlbStatcastFeatureSnapshotRecord,
)
from app.models.sports import SportsEventRecord

_NAMESPACE = UUID("8e69a4a8-abd8-4680-a5f0-17f176a40813")


class MlbGameFeatureConflictError(RuntimeError):
    """The exact persisted source lineage changed before vector creation."""


def mlb_game_feature_vector_record_id(statcast_snapshot_id: UUID, input_fingerprint: str) -> UUID:
    return uuid5(_NAMESPACE, f"vector:{statcast_snapshot_id}:{input_fingerprint}")


class MlbGameFeatureRepository:
    """Persist and query append-only derived MLB feature vectors."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_statcast_snapshot(
        self, snapshot_id: UUID
    ) -> MlbStatcastFeatureSnapshotRecord | None:
        result = await self._session.scalars(
            select(MlbStatcastFeatureSnapshotRecord).where(
                MlbStatcastFeatureSnapshotRecord.id == snapshot_id
            )
        )
        return result.unique().one_or_none()

    @staticmethod
    def _validate_lineage(
        event: SportsEventRecord,
        lineup: MlbLineupSnapshotRecord,
        statcast: MlbStatcastFeatureSnapshotRecord,
        vector: MlbGameFeatureVector,
    ) -> None:
        if event.provider_name != "mlb" or event.league != "mlb":
            raise MlbGameFeatureConflictError("feature vectors require an official MLB event")
        if (lineup.sports_event_id, statcast.sports_event_id, vector.sports_event_id) != (
            event.id,
            event.id,
            event.id,
        ):
            raise MlbGameFeatureConflictError("event lineage changed")
        if statcast.lineup_snapshot_id != lineup.id or vector.lineup_snapshot_id != lineup.id:
            raise MlbGameFeatureConflictError("lineup lineage changed")
        if vector.statcast_snapshot_id != statcast.id:
            raise MlbGameFeatureConflictError("Statcast lineage changed")
        if not lineup.complete_for_pregame_model:
            raise MlbGameFeatureConflictError("source lineup is not complete")
        if (
            event.provider_event_id != vector.provider_event_id
            or event.event_date != vector.target_event_date
            or event.scheduled_start_time != vector.scheduled_start_time
            or event.home_team_id != vector.home_team_id
            or event.away_team_id != vector.away_team_id
        ):
            raise MlbGameFeatureConflictError("official MLB event semantics changed")
        if (
            statcast.source_fingerprint != vector.source_fingerprint
            or statcast.source_retrieved_at != vector.source_retrieved_at
            or statcast.observation_basis != vector.source_observation_basis.value
        ):
            raise MlbGameFeatureConflictError("quantitative source fingerprint changed")

    async def persist_vector(
        self, vector: MlbGameFeatureVector
    ) -> tuple[MlbGameFeatureVectorRecord, bool]:
        try:
            event = await self._session.scalar(
                select(SportsEventRecord)
                .where(SportsEventRecord.id == vector.sports_event_id)
                .with_for_update(of=SportsEventRecord)
            )
            if event is None:
                raise LookupError("sports event not found")
            lineup = await self._session.scalar(
                select(MlbLineupSnapshotRecord)
                .where(MlbLineupSnapshotRecord.id == vector.lineup_snapshot_id)
                .with_for_update(of=MlbLineupSnapshotRecord)
            )
            if lineup is None:
                raise LookupError("MLB lineup snapshot not found")
            statcast = await self._session.scalar(
                select(MlbStatcastFeatureSnapshotRecord)
                .where(MlbStatcastFeatureSnapshotRecord.id == vector.statcast_snapshot_id)
                .with_for_update(of=MlbStatcastFeatureSnapshotRecord)
            )
            if statcast is None:
                raise LookupError("MLB Statcast snapshot not found")
            self._validate_lineage(event, lineup, statcast, vector)
            record_id = mlb_game_feature_vector_record_id(
                vector.statcast_snapshot_id, vector.input_fingerprint
            )
            inserted_id = await self._session.scalar(
                insert(MlbGameFeatureVectorRecord)
                .values(
                    id=record_id,
                    sports_event_id=vector.sports_event_id,
                    lineup_snapshot_id=vector.lineup_snapshot_id,
                    statcast_snapshot_id=vector.statcast_snapshot_id,
                    provider_event_id=vector.provider_event_id,
                    target_event_date=vector.target_event_date,
                    scheduled_start_time=vector.scheduled_start_time,
                    home_team_id=vector.home_team_id,
                    away_team_id=vector.away_team_id,
                    source_retrieved_at=vector.source_retrieved_at,
                    source_observation_basis=vector.source_observation_basis.value,
                    built_at=vector.built_at,
                    feature_availability_basis=vector.feature_availability_basis.value,
                    policy_name=vector.policy_name,
                    policy_version=vector.policy_version,
                    model_candidate_name=vector.model_candidate_name,
                    policy_fingerprint=vector.policy_fingerprint,
                    source_metrics=vector.source_metrics.model_dump(mode="json"),
                    coverage=vector.coverage.model_dump(mode="json"),
                    feature_values=vector.feature_values.model_dump(mode="json"),
                    missing_features=[feature.value for feature in vector.missing_features],
                    complete_feature_vector=vector.complete_feature_vector,
                    operational_model_input_eligible=vector.operational_model_input_eligible,
                    research_only=vector.research_only,
                    probability_generated=vector.probability_generated,
                    automatic_trading_eligible=vector.automatic_trading_eligible,
                    source_fingerprint=vector.source_fingerprint,
                    input_fingerprint=vector.input_fingerprint,
                )
                .on_conflict_do_nothing(constraint="uq_mlb_game_feature_vectors_semantic_input")
                .returning(MlbGameFeatureVectorRecord.id)
            )
            await self._session.commit()
            record = await self.get_vector(record_id)
            if record is None:
                raise RuntimeError("persisted MLB game feature vector could not be reloaded")
            return record, inserted_id is not None
        except Exception:
            await self._session.rollback()
            raise

    async def list_vectors(
        self,
        *,
        event_id: UUID | None,
        statcast_snapshot_id: UUID | None,
        operational_model_input_eligible: bool | None,
        limit: int,
        offset: int,
    ) -> list[MlbGameFeatureVectorRecord]:
        statement = (
            select(MlbGameFeatureVectorRecord)
            .order_by(
                MlbGameFeatureVectorRecord.built_at.desc(),
                MlbGameFeatureVectorRecord.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        if event_id is not None:
            statement = statement.where(MlbGameFeatureVectorRecord.sports_event_id == event_id)
        if statcast_snapshot_id is not None:
            statement = statement.where(
                MlbGameFeatureVectorRecord.statcast_snapshot_id == statcast_snapshot_id
            )
        if operational_model_input_eligible is not None:
            statement = statement.where(
                MlbGameFeatureVectorRecord.operational_model_input_eligible
                == operational_model_input_eligible
            )
        return list((await self._session.scalars(statement)).unique().all())

    async def get_vector(self, vector_id: UUID) -> MlbGameFeatureVectorRecord | None:
        result = await self._session.scalars(
            select(MlbGameFeatureVectorRecord).where(MlbGameFeatureVectorRecord.id == vector_id)
        )
        return result.unique().one_or_none()
