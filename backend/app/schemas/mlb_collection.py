from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.mlb import MlbBackfillBatchRecord, MlbBackfillCheckpointRecord
from app.schemas.mlb_modeling import MlbApprovedDatasetReadinessResponse
from app.services.mlb_backfill_workflow import MlbBackfillWorkflowRunResult
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


class MlbBackfillCheckpointResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    policy_name: str
    policy_version: str
    policy_fingerprint: str
    split_policy_fingerprint: str
    status: Literal["active", "complete", "exhausted"]
    regular_season_start: date
    validation_start_date: date
    test_start_date: date
    prospective_holdout_start_date: date
    train_cursor_date: date
    train_cursor_offset: int
    validation_cursor_date: date
    validation_cursor_offset: int
    test_cursor_date: date
    test_cursor_offset: int
    batch_limit: int
    version: int
    batches_completed: int
    events_examined: int
    examples_created: int
    last_run_at: datetime | None
    finished_at: datetime | None
    state_fingerprint: str
    research_only: Literal[True]
    probability_generated: Literal[False]
    automatic_trading_eligible: Literal[False]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: MlbBackfillCheckpointRecord) -> MlbBackfillCheckpointResponse:
        return cls.model_validate(record)


class MlbBackfillBatchResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    checkpoint_id: UUID
    sequence: int
    split: Literal["train", "validation", "test"]
    window_date: date
    offset: int
    batch_limit: int
    cursor_date_after: date
    cursor_offset_after: int
    run_at: datetime
    events_refreshed: int
    examined: int
    retrospective_vectors_built: int
    examples_labeled: int
    examples_created: int
    result_counts: dict[str, int]
    event_results: list[dict[str, object]]
    readiness_before: dict[str, object]
    readiness_after: dict[str, object]
    input_fingerprint: str
    result_fingerprint: str
    research_only: Literal[True]
    probability_generated: Literal[False]
    automatic_trading_eligible: Literal[False]
    created_at: datetime

    @classmethod
    def from_record(cls, record: MlbBackfillBatchRecord) -> MlbBackfillBatchResponse:
        return cls.model_validate(record)


class MlbBackfillWorkflowRunResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: Literal["ran_batch", "complete", "exhausted"]
    created: bool
    checkpoint: MlbBackfillCheckpointResponse
    batch: MlbBackfillBatchResponse | None
    readiness: MlbApprovedDatasetReadinessResponse
    research_only: Literal[True] = True
    probability_generated: Literal[False] = False
    automatic_trading_eligible: Literal[False] = False

    @classmethod
    def from_result(cls, result: MlbBackfillWorkflowRunResult) -> MlbBackfillWorkflowRunResponse:
        return cls(
            action=result.action,
            created=result.created,
            checkpoint=MlbBackfillCheckpointResponse.from_record(result.checkpoint),
            batch=(
                MlbBackfillBatchResponse.from_record(result.batch)
                if result.batch is not None
                else None
            ),
            readiness=MlbApprovedDatasetReadinessResponse.from_assessment(result.readiness),
        )
