from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.mlb_lineups import MlbLineupEntry, MlbProbablePitcher
from app.models.mlb import MlbLineupSnapshotRecord


class MlbLineupSnapshotResponse(BaseModel):
    """Typed official probable-pitcher and batting-order observation."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    sports_event_id: UUID
    provider_name: str
    provider_event_id: str
    home_team_id: UUID
    away_team_id: UUID
    scheduled_start_time: datetime
    source_updated_at: datetime
    retrieved_at: datetime
    source_abstract_state: str
    source_detailed_state: str
    observation_phase: str
    home_probable_pitcher: MlbProbablePitcher | None
    away_probable_pitcher: MlbProbablePitcher | None
    home_lineup_state: str
    away_lineup_state: str
    home_lineup: tuple[MlbLineupEntry, ...]
    away_lineup: tuple[MlbLineupEntry, ...]
    complete_for_pregame_model: bool
    input_fingerprint: str
    source_snapshot: dict[str, Any]

    @classmethod
    def from_record(cls, record: MlbLineupSnapshotRecord) -> MlbLineupSnapshotResponse:
        """Build the public response from one immutable persistence record."""
        return cls(
            id=record.id,
            sports_event_id=record.sports_event_id,
            provider_name=record.provider_name,
            provider_event_id=record.provider_event_id,
            home_team_id=record.home_team_id,
            away_team_id=record.away_team_id,
            scheduled_start_time=record.scheduled_start_time,
            source_updated_at=record.source_updated_at,
            retrieved_at=record.retrieved_at,
            source_abstract_state=record.source_abstract_state,
            source_detailed_state=record.source_detailed_state,
            observation_phase=record.observation_phase,
            home_probable_pitcher=(
                MlbProbablePitcher.model_validate(record.home_probable_pitcher)
                if record.home_probable_pitcher is not None
                else None
            ),
            away_probable_pitcher=(
                MlbProbablePitcher.model_validate(record.away_probable_pitcher)
                if record.away_probable_pitcher is not None
                else None
            ),
            home_lineup_state=record.home_lineup_state,
            away_lineup_state=record.away_lineup_state,
            home_lineup=tuple(MlbLineupEntry.model_validate(item) for item in record.home_lineup),
            away_lineup=tuple(MlbLineupEntry.model_validate(item) for item in record.away_lineup),
            complete_for_pregame_model=record.complete_for_pregame_model,
            input_fingerprint=record.input_fingerprint,
            source_snapshot=record.source_snapshot,
        )


class MlbLineupIngestionResponse(BaseModel):
    """Create-or-replay response for one explicit lineup ingestion."""

    model_config = ConfigDict(frozen=True)

    created: bool
    snapshot: MlbLineupSnapshotResponse
