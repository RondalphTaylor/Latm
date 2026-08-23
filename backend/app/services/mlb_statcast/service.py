from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol
from uuid import UUID

from app.domain.mlb_lineups import MlbLineupEntry, MlbProbablePitcher
from app.domain.mlb_statcast import (
    MlbStatcastFeatureInput,
    MlbStatcastFeaturePolicy,
    MlbStatcastPlayerRole,
)
from app.models.mlb import MlbStatcastFeatureSnapshotRecord
from app.providers.sports.savant import BaseballSavantQueryBatch
from app.services.mlb_statcast.engine import DeterministicMlbStatcastFeatureEngine
from app.services.mlb_statcast.repository import MlbStatcastRepository


@dataclass(frozen=True)
class MlbStatcastIngestionResult:
    """Create-or-replay result for one quantitative feature snapshot."""

    created: bool
    snapshot: MlbStatcastFeatureSnapshotRecord


class MlbStatcastSource(Protocol):
    """Read-only quantitative-source boundary consumed by orchestration."""

    async def get_player_rows(
        self,
        *,
        role: MlbStatcastPlayerRole,
        player_ids: tuple[str, ...],
        window_start_date: date,
        window_end_date: date,
    ) -> BaseballSavantQueryBatch: ...


class MlbStatcastService:
    """Coordinate exact-lineup official Statcast retrieval and aggregation."""

    def __init__(
        self,
        *,
        provider: MlbStatcastSource,
        repository: MlbStatcastRepository,
        engine: DeterministicMlbStatcastFeatureEngine,
        policy: MlbStatcastFeaturePolicy,
    ) -> None:
        self._provider = provider
        self._repository = repository
        self._engine = engine
        self._policy = policy

    async def ingest(
        self,
        *,
        event_id: UUID,
        lineup_snapshot_id: UUID,
    ) -> MlbStatcastIngestionResult:
        """Build one rolling quantitative snapshot without forecasting or trading."""
        lineup = await self._repository.get_lineup_snapshot(lineup_snapshot_id)
        if lineup is None:
            raise LookupError("MLB lineup snapshot not found")
        if lineup.sports_event_id != event_id:
            raise ValueError("MLB lineup snapshot does not belong to the requested event")
        if not lineup.complete_for_research_features:
            raise ValueError("Statcast ingestion requires two complete lineups and starters")
        event = lineup.sports_event
        if event.provider_name != "mlb" or event.league != "mlb":
            raise ValueError("Statcast ingestion requires an official MLB event")
        home_pitcher = MlbProbablePitcher.model_validate(lineup.home_probable_pitcher)
        away_pitcher = MlbProbablePitcher.model_validate(lineup.away_probable_pitcher)
        home_lineup = tuple(MlbLineupEntry.model_validate(item) for item in lineup.home_lineup)
        away_lineup = tuple(MlbLineupEntry.model_validate(item) for item in lineup.away_lineup)
        window_end_date = event.event_date - timedelta(days=1)
        window_start_date = event.event_date - timedelta(days=self._policy.lookback_days)
        pitcher_batch = await self._provider.get_player_rows(
            role=MlbStatcastPlayerRole.PITCHER,
            player_ids=(
                home_pitcher.provider_player_id,
                away_pitcher.provider_player_id,
            ),
            window_start_date=window_start_date,
            window_end_date=window_end_date,
        )
        batter_batch = await self._provider.get_player_rows(
            role=MlbStatcastPlayerRole.BATTER,
            player_ids=tuple(entry.provider_player_id for entry in (*home_lineup, *away_lineup)),
            window_start_date=window_start_date,
            window_end_date=window_end_date,
        )
        snapshot = self._engine.evaluate(
            MlbStatcastFeatureInput(
                sports_event_id=event_id,
                lineup_snapshot_id=lineup_snapshot_id,
                provider_event_id=event.provider_event_id,
                target_event_date=event.event_date,
                scheduled_start_time=event.scheduled_start_time,
                lineup_input_fingerprint=lineup.input_fingerprint,
                home_probable_pitcher=home_pitcher,
                away_probable_pitcher=away_pitcher,
                home_lineup=home_lineup,
                away_lineup=away_lineup,
                pitcher_rows=pitcher_batch.rows,
                batter_rows=batter_batch.rows,
                pitcher_response_sha256=pitcher_batch.response_sha256,
                batter_response_sha256=batter_batch.response_sha256,
                source_retrieved_at=max(
                    pitcher_batch.retrieved_at,
                    batter_batch.retrieved_at,
                ),
                policy=self._policy,
            )
        )
        record, created = await self._repository.persist_snapshot(snapshot)
        return MlbStatcastIngestionResult(created=created, snapshot=record)
