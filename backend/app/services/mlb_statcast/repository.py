from __future__ import annotations

from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.domain.mlb_statcast import MlbStatcastFeatureSnapshot
from app.models.markets import Provider
from app.models.mlb import MlbLineupSnapshotRecord, MlbStatcastFeatureSnapshotRecord
from app.models.sports import SportsEventRecord

_LATM_MLB_STATCAST_NAMESPACE = UUID("a96e5fc1-d50b-4cfb-85c1-c71fba90d0a6")


class MlbStatcastSourceConflictError(RuntimeError):
    """The event or lineup lineage changed before Statcast persistence."""


def mlb_statcast_snapshot_record_id(lineup_snapshot_id: UUID, input_fingerprint: str) -> UUID:
    """Return a stable ID for one lineup and semantic quantitative source."""
    return uuid5(
        _LATM_MLB_STATCAST_NAMESPACE,
        f"snapshot:{lineup_snapshot_id}:{input_fingerprint}",
    )


class MlbStatcastRepository:
    """Persist and query append-only official Statcast feature snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_lineup_snapshot(
        self,
        lineup_snapshot_id: UUID,
    ) -> MlbLineupSnapshotRecord | None:
        """Return one exact lineup observation and normalized event lineage."""
        result = await self._session.scalars(
            select(MlbLineupSnapshotRecord)
            .where(MlbLineupSnapshotRecord.id == lineup_snapshot_id)
            .options(joinedload(MlbLineupSnapshotRecord.sports_event))
        )
        return result.unique().one_or_none()

    @staticmethod
    def _validate_lineage(
        event: SportsEventRecord,
        lineup: MlbLineupSnapshotRecord,
        snapshot: MlbStatcastFeatureSnapshot,
    ) -> None:
        if event.provider_name != "mlb" or event.league != "mlb":
            raise MlbStatcastSourceConflictError("Statcast snapshots require an official MLB event")
        if lineup.sports_event_id != event.id or snapshot.sports_event_id != event.id:
            raise MlbStatcastSourceConflictError(
                "Statcast lineup and event identities do not match"
            )
        if snapshot.lineup_snapshot_id != lineup.id:
            raise MlbStatcastSourceConflictError("Statcast snapshot points to the wrong lineup")
        if not lineup.complete_for_pregame_model:
            raise MlbStatcastSourceConflictError(
                "Statcast snapshots require a complete pregame lineup observation"
            )
        if event.provider_event_id != snapshot.provider_event_id:
            raise MlbStatcastSourceConflictError("official MLB event identity changed")
        if event.event_date != snapshot.target_event_date:
            raise MlbStatcastSourceConflictError("official MLB event date changed")
        if event.scheduled_start_time != snapshot.scheduled_start_time:
            raise MlbStatcastSourceConflictError("official MLB scheduled start changed")
        home_pitcher = lineup.home_probable_pitcher or {}
        away_pitcher = lineup.away_probable_pitcher or {}
        if (
            home_pitcher.get("provider_player_id")
            != snapshot.home_starting_pitcher.provider_player_id
        ):
            raise MlbStatcastSourceConflictError("home probable pitcher identity changed")
        if (
            away_pitcher.get("provider_player_id")
            != snapshot.away_starting_pitcher.provider_player_id
        ):
            raise MlbStatcastSourceConflictError("away probable pitcher identity changed")
        home_ids = [str(entry.get("provider_player_id")) for entry in lineup.home_lineup]
        away_ids = [str(entry.get("provider_player_id")) for entry in lineup.away_lineup]
        if home_ids != [profile.provider_player_id for profile in snapshot.home_batters]:
            raise MlbStatcastSourceConflictError("home batting order identity changed")
        if away_ids != [profile.provider_player_id for profile in snapshot.away_batters]:
            raise MlbStatcastSourceConflictError("away batting order identity changed")

    async def persist_snapshot(
        self,
        snapshot: MlbStatcastFeatureSnapshot,
    ) -> tuple[MlbStatcastFeatureSnapshotRecord, bool]:
        """Lock event then lineup, revalidate exact lineage, and append or replay."""
        try:
            event = await self._session.scalar(
                select(SportsEventRecord)
                .where(SportsEventRecord.id == snapshot.sports_event_id)
                .with_for_update(of=SportsEventRecord)
            )
            if event is None:
                raise LookupError("sports event not found")
            lineup_result = await self._session.scalars(
                select(MlbLineupSnapshotRecord)
                .where(MlbLineupSnapshotRecord.id == snapshot.lineup_snapshot_id)
                .with_for_update(of=MlbLineupSnapshotRecord)
            )
            lineup = lineup_result.unique().one_or_none()
            if lineup is None:
                raise LookupError("MLB lineup snapshot not found")
            self._validate_lineage(event, lineup, snapshot)
            provider_insert = insert(Provider).values(
                name="baseball_savant",
                display_name="Baseball Savant / Statcast",
                is_read_only=True,
            )
            await self._session.execute(
                provider_insert.on_conflict_do_update(
                    index_elements=[Provider.name],
                    set_={
                        "display_name": provider_insert.excluded.display_name,
                        "is_read_only": True,
                    },
                )
            )
            record_id = mlb_statcast_snapshot_record_id(
                snapshot.lineup_snapshot_id,
                snapshot.input_fingerprint,
            )
            inserted_id = await self._session.scalar(
                insert(MlbStatcastFeatureSnapshotRecord)
                .values(
                    id=record_id,
                    sports_event_id=snapshot.sports_event_id,
                    lineup_snapshot_id=snapshot.lineup_snapshot_id,
                    provider_name=snapshot.provider_name,
                    provider_event_id=snapshot.provider_event_id,
                    target_event_date=snapshot.target_event_date,
                    scheduled_start_time=snapshot.scheduled_start_time,
                    window_start_date=snapshot.window_start_date,
                    window_end_date=snapshot.window_end_date,
                    lookback_days=snapshot.lookback_days,
                    source_retrieved_at=snapshot.source_retrieved_at,
                    observation_basis=snapshot.observation_basis.value,
                    operational_pregame_eligible=snapshot.operational_pregame_eligible,
                    policy_name=snapshot.policy_name,
                    policy_version=snapshot.policy_version,
                    policy_fingerprint=snapshot.policy_fingerprint,
                    home_starting_pitcher=snapshot.home_starting_pitcher.model_dump(mode="json"),
                    away_starting_pitcher=snapshot.away_starting_pitcher.model_dump(mode="json"),
                    home_batters=[item.model_dump(mode="json") for item in snapshot.home_batters],
                    away_batters=[item.model_dump(mode="json") for item in snapshot.away_batters],
                    source_fingerprint=snapshot.source_fingerprint,
                    input_fingerprint=snapshot.input_fingerprint,
                    source_manifest=snapshot.source_manifest,
                    source_rows=[item.model_dump(mode="json") for item in snapshot.source_rows],
                )
                .on_conflict_do_nothing(
                    constraint="uq_mlb_statcast_feature_snapshots_semantic_input"
                )
                .returning(MlbStatcastFeatureSnapshotRecord.id)
            )
            await self._session.commit()
            record = await self.get_snapshot(record_id)
            if record is None:
                raise RuntimeError("persisted MLB Statcast snapshot could not be reloaded")
            return record, inserted_id is not None
        except Exception:
            await self._session.rollback()
            raise

    async def list_snapshots(
        self,
        *,
        event_id: UUID | None,
        lineup_snapshot_id: UUID | None,
        operational_pregame_eligible: bool | None,
        limit: int,
        offset: int,
    ) -> list[MlbStatcastFeatureSnapshotRecord]:
        """Return immutable quantitative snapshots newest first."""
        statement = (
            select(MlbStatcastFeatureSnapshotRecord)
            .order_by(
                MlbStatcastFeatureSnapshotRecord.source_retrieved_at.desc(),
                MlbStatcastFeatureSnapshotRecord.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        if event_id is not None:
            statement = statement.where(
                MlbStatcastFeatureSnapshotRecord.sports_event_id == event_id
            )
        if lineup_snapshot_id is not None:
            statement = statement.where(
                MlbStatcastFeatureSnapshotRecord.lineup_snapshot_id == lineup_snapshot_id
            )
        if operational_pregame_eligible is not None:
            statement = statement.where(
                MlbStatcastFeatureSnapshotRecord.operational_pregame_eligible
                == operational_pregame_eligible
            )
        result = await self._session.scalars(statement)
        return list(result.unique().all())

    async def get_snapshot(
        self,
        snapshot_id: UUID,
    ) -> MlbStatcastFeatureSnapshotRecord | None:
        """Return one immutable quantitative snapshot by stable ID."""
        result = await self._session.scalars(
            select(MlbStatcastFeatureSnapshotRecord).where(
                MlbStatcastFeatureSnapshotRecord.id == snapshot_id
            )
        )
        return result.unique().one_or_none()
