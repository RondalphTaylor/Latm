from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.mlb_modeling import (
    MlbChronologicalDatasetPolicy,
    MlbGameFeatureVector,
    MlbLabeledFeatureExample,
)
from app.models.mlb import (
    MlbGameFeatureVectorRecord,
    MlbLabeledFeatureExampleRecord,
    MlbLineupSnapshotRecord,
    MlbStatcastFeatureSnapshotRecord,
)
from app.models.sports import SportsEventRecord

_NAMESPACE = UUID("8e69a4a8-abd8-4680-a5f0-17f176a40813")
_EXAMPLE_NAMESPACE = UUID("e8bdad87-f3a4-439a-a93e-7e14e171077d")


class MlbGameFeatureConflictError(RuntimeError):
    """The exact persisted source lineage changed before vector creation."""


def mlb_game_feature_vector_record_id(statcast_snapshot_id: UUID, input_fingerprint: str) -> UUID:
    return uuid5(_NAMESPACE, f"vector:{statcast_snapshot_id}:{input_fingerprint}")


def mlb_labeled_feature_example_record_id(example_fingerprint: str) -> UUID:
    return uuid5(_EXAMPLE_NAMESPACE, f"example:{example_fingerprint}")


@dataclass(frozen=True)
class MlbDatasetLabelCandidate:
    vector: MlbGameFeatureVectorRecord
    event: SportsEventRecord


@dataclass(frozen=True)
class MlbDatasetInventory:
    split_policy_fingerprint: str
    example_count: int
    unique_event_count: int
    operational_example_count: int
    retrospective_example_count: int
    split_counts: dict[str, int]
    operational_split_counts: dict[str, int]
    retrospective_split_counts: dict[str, int]


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

    async def database_time(self) -> datetime:
        value = await self._session.scalar(select(func.clock_timestamp()))
        if value is None:
            raise RuntimeError("database did not return an MLB dataset timestamp")
        return cast(datetime, value)

    async def get_label_candidate(self, vector_id: UUID) -> MlbDatasetLabelCandidate | None:
        """Lock the mutable official event before freezing its result."""
        row = (
            await self._session.execute(
                select(MlbGameFeatureVectorRecord, SportsEventRecord)
                .join(
                    SportsEventRecord,
                    SportsEventRecord.id == MlbGameFeatureVectorRecord.sports_event_id,
                )
                .where(MlbGameFeatureVectorRecord.id == vector_id)
                .with_for_update(of=SportsEventRecord)
            )
        ).one_or_none()
        if row is None:
            return None
        return MlbDatasetLabelCandidate(vector=row[0], event=row[1])

    async def persist_labeled_example(
        self,
        *,
        candidate: MlbDatasetLabelCandidate,
        example: MlbLabeledFeatureExample,
        policy: MlbChronologicalDatasetPolicy,
        labeled_at: datetime,
    ) -> tuple[MlbLabeledFeatureExampleRecord, bool]:
        """Freeze one exact official result and split assignment, or replay it."""
        event = candidate.event
        if event.id != example.sports_event_id or event.league != "mlb":
            raise MlbGameFeatureConflictError("labeled examples require the exact MLB event")
        if event.home_score is None or event.away_score is None:
            raise MlbGameFeatureConflictError("official MLB result scores disappeared")
        source_snapshot: dict[str, object] = {
            "provider_name": event.provider_name,
            "provider_event_id": event.provider_event_id,
            "league": event.league,
            "status": event.status,
            "status_detail": event.status_detail,
            "scheduled_start_time": event.scheduled_start_time.isoformat(),
            "home_team_id": str(event.home_team_id),
            "away_team_id": str(event.away_team_id),
            "home_score": event.home_score,
            "away_score": event.away_score,
            "source_last_seen_at": event.last_seen_at.isoformat(),
            "raw_data": event.raw_data,
        }
        record_id = mlb_labeled_feature_example_record_id(example.example_fingerprint)
        try:
            inserted_id = await self._session.scalar(
                insert(MlbLabeledFeatureExampleRecord)
                .values(
                    id=record_id,
                    game_feature_vector_id=candidate.vector.id,
                    sports_event_id=example.sports_event_id,
                    feature_vector_input_fingerprint=example.feature_vector_input_fingerprint,
                    feature_policy_fingerprint=example.feature_policy_fingerprint,
                    availability_basis=example.availability_basis.value,
                    scheduled_start_time=example.scheduled_start_time,
                    outcome_status="final",
                    home_score=event.home_score,
                    away_score=event.away_score,
                    home_won=example.home_won,
                    outcome_source_last_seen_at=event.last_seen_at,
                    outcome_source_snapshot=source_snapshot,
                    split=example.split.value,
                    split_policy_name=policy.policy_name,
                    split_policy_version=policy.policy_version,
                    validation_start=policy.validation_start,
                    test_start=policy.test_start,
                    prospective_holdout_start=policy.prospective_holdout_start,
                    split_policy_fingerprint=example.split_policy_fingerprint,
                    outcome_fingerprint=example.outcome_fingerprint,
                    example_fingerprint=example.example_fingerprint,
                    labeled_at=labeled_at,
                    research_only=True,
                    probability_generated=False,
                    automatic_trading_eligible=False,
                )
                .on_conflict_do_nothing(constraint="uq_mlb_labeled_feature_examples_semantic_input")
                .returning(MlbLabeledFeatureExampleRecord.id)
            )
            await self._session.commit()
            record = await self.get_labeled_example(record_id)
            if record is None:
                raise RuntimeError("persisted MLB labeled example could not be reloaded")
            return record, inserted_id is not None
        except Exception:
            await self._session.rollback()
            raise

    async def list_labeled_examples(
        self,
        *,
        sports_event_id: UUID | None,
        game_feature_vector_id: UUID | None,
        split_policy_fingerprint: str | None,
        availability_basis: str | None,
        split: str | None,
        limit: int,
        offset: int,
    ) -> list[MlbLabeledFeatureExampleRecord]:
        statement = (
            select(MlbLabeledFeatureExampleRecord)
            .order_by(
                MlbLabeledFeatureExampleRecord.scheduled_start_time.desc(),
                MlbLabeledFeatureExampleRecord.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        filters = (
            (MlbLabeledFeatureExampleRecord.sports_event_id, sports_event_id),
            (MlbLabeledFeatureExampleRecord.game_feature_vector_id, game_feature_vector_id),
            (
                MlbLabeledFeatureExampleRecord.split_policy_fingerprint,
                split_policy_fingerprint,
            ),
            (MlbLabeledFeatureExampleRecord.availability_basis, availability_basis),
            (MlbLabeledFeatureExampleRecord.split, split),
        )
        for column, value in filters:
            if value is not None:
                statement = statement.where(column == value)
        return list((await self._session.scalars(statement)).unique().all())

    async def get_labeled_example(self, example_id: UUID) -> MlbLabeledFeatureExampleRecord | None:
        result = await self._session.scalars(
            select(MlbLabeledFeatureExampleRecord).where(
                MlbLabeledFeatureExampleRecord.id == example_id
            )
        )
        return result.unique().one_or_none()

    async def dataset_inventory(self, split_policy_fingerprint: str) -> MlbDatasetInventory:
        rows = (
            await self._session.execute(
                select(
                    MlbLabeledFeatureExampleRecord.availability_basis,
                    MlbLabeledFeatureExampleRecord.split,
                    func.count(MlbLabeledFeatureExampleRecord.id),
                )
                .where(
                    MlbLabeledFeatureExampleRecord.split_policy_fingerprint
                    == split_policy_fingerprint
                )
                .group_by(
                    MlbLabeledFeatureExampleRecord.availability_basis,
                    MlbLabeledFeatureExampleRecord.split,
                )
            )
        ).all()
        unique_events = await self._session.scalar(
            select(func.count(func.distinct(MlbLabeledFeatureExampleRecord.sports_event_id))).where(
                MlbLabeledFeatureExampleRecord.split_policy_fingerprint == split_policy_fingerprint
            )
        )
        split_counts: dict[str, int] = {}
        operational_counts: dict[str, int] = {}
        retrospective_counts: dict[str, int] = {}
        for basis, split, count in rows:
            split_name = str(split)
            split_counts[split_name] = split_counts.get(split_name, 0) + int(count)
            target = operational_counts if basis == "operational_pregame" else retrospective_counts
            target[split_name] = int(count)
        operational = sum(operational_counts.values())
        retrospective = sum(retrospective_counts.values())
        return MlbDatasetInventory(
            split_policy_fingerprint=split_policy_fingerprint,
            example_count=operational + retrospective,
            unique_event_count=int(unique_events or 0),
            operational_example_count=operational,
            retrospective_example_count=retrospective,
            split_counts=split_counts,
            operational_split_counts=operational_counts,
            retrospective_split_counts=retrospective_counts,
        )
