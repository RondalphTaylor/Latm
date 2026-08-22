from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.mlb_statcast import MlbStatcastPlayerFeatures
from app.models.mlb import MlbStatcastFeatureSnapshotRecord


class MlbStatcastSnapshotResponse(BaseModel):
    """Quantitative Statcast snapshot without its potentially large raw row payload."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    sports_event_id: UUID
    lineup_snapshot_id: UUID
    provider_name: str
    provider_event_id: str
    target_event_date: date
    scheduled_start_time: datetime
    window_start_date: date
    window_end_date: date
    lookback_days: int
    source_retrieved_at: datetime
    observation_basis: str
    operational_pregame_eligible: bool
    policy_name: str
    policy_version: str
    policy_fingerprint: str
    home_starting_pitcher: MlbStatcastPlayerFeatures
    away_starting_pitcher: MlbStatcastPlayerFeatures
    home_batters: tuple[MlbStatcastPlayerFeatures, ...]
    away_batters: tuple[MlbStatcastPlayerFeatures, ...]
    source_fingerprint: str
    input_fingerprint: str
    source_manifest: dict[str, Any]
    source_row_count: int

    @classmethod
    def from_record(cls, record: MlbStatcastFeatureSnapshotRecord) -> MlbStatcastSnapshotResponse:
        """Build the bounded public response from an immutable database record."""
        return cls(
            id=record.id,
            sports_event_id=record.sports_event_id,
            lineup_snapshot_id=record.lineup_snapshot_id,
            provider_name=record.provider_name,
            provider_event_id=record.provider_event_id,
            target_event_date=record.target_event_date,
            scheduled_start_time=record.scheduled_start_time,
            window_start_date=record.window_start_date,
            window_end_date=record.window_end_date,
            lookback_days=record.lookback_days,
            source_retrieved_at=record.source_retrieved_at,
            observation_basis=record.observation_basis,
            operational_pregame_eligible=record.operational_pregame_eligible,
            policy_name=record.policy_name,
            policy_version=record.policy_version,
            policy_fingerprint=record.policy_fingerprint,
            home_starting_pitcher=MlbStatcastPlayerFeatures.model_validate(
                record.home_starting_pitcher
            ),
            away_starting_pitcher=MlbStatcastPlayerFeatures.model_validate(
                record.away_starting_pitcher
            ),
            home_batters=tuple(
                MlbStatcastPlayerFeatures.model_validate(item) for item in record.home_batters
            ),
            away_batters=tuple(
                MlbStatcastPlayerFeatures.model_validate(item) for item in record.away_batters
            ),
            source_fingerprint=record.source_fingerprint,
            input_fingerprint=record.input_fingerprint,
            source_manifest=record.source_manifest,
            source_row_count=len(record.source_rows),
        )


class MlbStatcastIngestionResponse(BaseModel):
    """Create-or-replay response for one explicit quantitative snapshot."""

    model_config = ConfigDict(frozen=True)

    created: bool
    snapshot: MlbStatcastSnapshotResponse
