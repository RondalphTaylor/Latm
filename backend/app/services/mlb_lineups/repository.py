from __future__ import annotations

from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.domain.mlb_lineups import MlbLineupSnapshot
from app.models.mlb import MlbLineupSnapshotRecord
from app.models.sports import SportsEventRecord

_LATM_MLB_LINEUP_NAMESPACE = UUID("da95fe4b-40c9-48e9-bb2b-1e3c715ef6d6")


class MlbLineupSourceConflictError(RuntimeError):
    """The official snapshot no longer matches the normalized local event."""


def mlb_lineup_snapshot_record_id(sports_event_id: UUID, input_fingerprint: str) -> UUID:
    """Return a stable ID for one event and semantic official observation."""
    return uuid5(
        _LATM_MLB_LINEUP_NAMESPACE,
        f"snapshot:{sports_event_id}:{input_fingerprint}",
    )


class MlbLineupRepository:
    """Persist and query append-only official MLB lineup observations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_event(self, event_id: UUID) -> SportsEventRecord | None:
        """Return one event and its team provider identities."""
        result = await self._session.scalars(
            select(SportsEventRecord)
            .where(SportsEventRecord.id == event_id)
            .options(
                joinedload(SportsEventRecord.home_team),
                joinedload(SportsEventRecord.away_team),
            )
        )
        return result.unique().one_or_none()

    @staticmethod
    def _validate_event(event: SportsEventRecord, snapshot: MlbLineupSnapshot) -> None:
        if event.provider_name != "mlb" or event.league != "mlb":
            raise MlbLineupSourceConflictError("lineup snapshots require an official MLB event")
        if event.provider_event_id != snapshot.provider_event_id:
            raise MlbLineupSourceConflictError("official feed event identity changed")
        if event.home_team.provider_team_id != snapshot.home_provider_team_id:
            raise MlbLineupSourceConflictError("official feed home-team identity changed")
        if event.away_team.provider_team_id != snapshot.away_provider_team_id:
            raise MlbLineupSourceConflictError("official feed away-team identity changed")
        if event.scheduled_start_time != snapshot.scheduled_start_time:
            raise MlbLineupSourceConflictError(
                "official feed schedule changed; refresh the sports event before ingesting lineups"
            )

    async def persist_snapshot(
        self,
        *,
        event_id: UUID,
        snapshot: MlbLineupSnapshot,
    ) -> tuple[MlbLineupSnapshotRecord, bool]:
        """Lock and revalidate the event, then append or replay one snapshot."""
        try:
            result = await self._session.scalars(
                select(SportsEventRecord)
                .where(SportsEventRecord.id == event_id)
                .options(
                    joinedload(SportsEventRecord.home_team),
                    joinedload(SportsEventRecord.away_team),
                )
                .with_for_update(of=SportsEventRecord)
            )
            event = result.unique().one_or_none()
            if event is None:
                raise LookupError("sports event not found")
            self._validate_event(event, snapshot)
            record_id = mlb_lineup_snapshot_record_id(event_id, snapshot.input_fingerprint)
            values = {
                "id": record_id,
                "sports_event_id": event_id,
                "provider_name": snapshot.provider_name,
                "provider_event_id": snapshot.provider_event_id,
                "home_team_id": event.home_team_id,
                "away_team_id": event.away_team_id,
                "scheduled_start_time": snapshot.scheduled_start_time,
                "source_updated_at": snapshot.source_updated_at,
                "retrieved_at": snapshot.retrieved_at,
                "source_abstract_state": snapshot.source_abstract_state,
                "source_detailed_state": snapshot.source_detailed_state,
                "observation_phase": snapshot.observation_phase.value,
                "home_probable_pitcher": (
                    snapshot.home_probable_pitcher.model_dump(mode="json")
                    if snapshot.home_probable_pitcher is not None
                    else None
                ),
                "away_probable_pitcher": (
                    snapshot.away_probable_pitcher.model_dump(mode="json")
                    if snapshot.away_probable_pitcher is not None
                    else None
                ),
                "home_lineup_state": snapshot.home_lineup_state.value,
                "away_lineup_state": snapshot.away_lineup_state.value,
                "home_lineup": [entry.model_dump(mode="json") for entry in snapshot.home_lineup],
                "away_lineup": [entry.model_dump(mode="json") for entry in snapshot.away_lineup],
                "complete_for_pregame_model": snapshot.complete_for_pregame_model,
                "input_fingerprint": snapshot.input_fingerprint,
                "source_snapshot": snapshot.source_snapshot,
            }
            inserted_id = await self._session.scalar(
                insert(MlbLineupSnapshotRecord)
                .values(values)
                .on_conflict_do_nothing(constraint="uq_mlb_lineup_snapshots_semantic_input")
                .returning(MlbLineupSnapshotRecord.id)
            )
            await self._session.commit()
            record = await self.get_snapshot(record_id)
            if record is None:
                raise RuntimeError("persisted MLB lineup snapshot could not be reloaded")
            return record, inserted_id is not None
        except Exception:
            await self._session.rollback()
            raise

    async def list_snapshots(
        self,
        *,
        event_id: UUID | None,
        observation_phase: str | None,
        complete_for_pregame_model: bool | None,
        limit: int,
        offset: int,
    ) -> list[MlbLineupSnapshotRecord]:
        """Return immutable observations newest first with bounded filters."""
        statement = (
            select(MlbLineupSnapshotRecord)
            .order_by(
                MlbLineupSnapshotRecord.retrieved_at.desc(),
                MlbLineupSnapshotRecord.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        if event_id is not None:
            statement = statement.where(MlbLineupSnapshotRecord.sports_event_id == event_id)
        if observation_phase is not None:
            statement = statement.where(
                MlbLineupSnapshotRecord.observation_phase == observation_phase
            )
        if complete_for_pregame_model is not None:
            statement = statement.where(
                MlbLineupSnapshotRecord.complete_for_pregame_model == complete_for_pregame_model
            )
        result = await self._session.scalars(statement)
        return list(result.unique().all())

    async def get_snapshot(self, snapshot_id: UUID) -> MlbLineupSnapshotRecord | None:
        """Return one immutable observation by stable ID."""
        result = await self._session.scalars(
            select(MlbLineupSnapshotRecord).where(MlbLineupSnapshotRecord.id == snapshot_id)
        )
        return result.unique().one_or_none()
