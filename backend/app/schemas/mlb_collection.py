from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.services.mlb_collection import MlbBackfillRunResult, MlbCollectionRunResult


class MlbCollectionEventResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    event_id: UUID
    provider_event_id: str
    scheduled_start_time: datetime
    stage: Literal["skipped", "lineup_observed", "feature_built", "failed"]
    reason_code: str
    lineup_snapshot_id: UUID | None
    statcast_snapshot_id: UUID | None
    game_feature_vector_id: UUID | None
    lineup_created: bool
    statcast_created: bool
    feature_vector_created: bool
    operational_model_input_eligible: bool


class MlbCollectionRunResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    start_date: date
    end_date: date
    run_at: datetime
    events_refreshed: int
    examined: int
    lineup_observed: int
    complete_lineups: int
    feature_vectors_built: int
    operational_feature_vectors: int
    result_counts: dict[str, int]
    events: tuple[MlbCollectionEventResponse, ...]
    research_only: Literal[True]
    probability_generated: Literal[False]
    automatic_trading_eligible: Literal[False]

    @classmethod
    def from_result(cls, result: MlbCollectionRunResult) -> MlbCollectionRunResponse:
        return cls.model_validate(result)


class MlbBackfillEventResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    event_id: UUID
    provider_event_id: str
    scheduled_start_time: datetime
    stage: Literal["skipped", "lineup_observed", "feature_built", "labeled", "failed"]
    reason_code: str
    lineup_snapshot_id: UUID | None
    statcast_snapshot_id: UUID | None
    game_feature_vector_id: UUID | None
    dataset_example_id: UUID | None
    split: str | None
    lineup_created: bool
    statcast_created: bool
    feature_vector_created: bool
    dataset_example_created: bool


class MlbBackfillRunResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    start_date: date
    end_date: date
    run_at: datetime
    events_refreshed: int
    examined: int
    retrospective_vectors_built: int
    examples_labeled: int
    result_counts: dict[str, int]
    events: tuple[MlbBackfillEventResponse, ...]
    research_only: Literal[True]
    probability_generated: Literal[False]
    automatic_trading_eligible: Literal[False]

    @classmethod
    def from_result(cls, result: MlbBackfillRunResult) -> MlbBackfillRunResponse:
        return cls.model_validate(result)
