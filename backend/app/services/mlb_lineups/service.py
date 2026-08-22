from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.models.mlb import MlbLineupSnapshotRecord
from app.providers.sports.mlb import MlbStatsSportsDataProvider
from app.services.mlb_lineups.repository import MlbLineupRepository


@dataclass(frozen=True)
class MlbLineupIngestionResult:
    """Result of one explicit official MLB lineup observation."""

    created: bool
    snapshot: MlbLineupSnapshotRecord


class MlbLineupService:
    """Coordinate one-event official MLB lineup retrieval and persistence."""

    def __init__(
        self,
        *,
        provider: MlbStatsSportsDataProvider,
        repository: MlbLineupRepository,
    ) -> None:
        self._provider = provider
        self._repository = repository

    async def ingest(self, event_id: UUID) -> MlbLineupIngestionResult:
        """Fetch one local MLB event's official live-feed snapshot."""
        event = await self._repository.get_event(event_id)
        if event is None:
            raise LookupError("sports event not found")
        if event.provider_name != "mlb" or event.league != "mlb":
            raise ValueError("lineup snapshots are supported only for official MLB events")
        snapshot = await self._provider.get_lineup_snapshot(event.provider_event_id)
        record, created = await self._repository.persist_snapshot(
            event_id=event_id,
            snapshot=snapshot,
        )
        return MlbLineupIngestionResult(created=created, snapshot=record)
