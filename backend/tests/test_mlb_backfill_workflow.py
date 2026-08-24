from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest

from app.domain.mlb_modeling import (
    MlbDatasetReadinessAssessment,
    MlbDatasetSplit,
    approved_mlb_historical_backfill_policy,
)
from app.models.mlb import MlbBackfillBatchRecord, MlbBackfillCheckpointRecord
from app.services.mlb_backfill_workflow import (
    MlbBackfillPlan,
    MlbBackfillWorkflowRepository,
    MlbBackfillWorkflowRetryableError,
    MlbHistoricalBackfillWorkflowService,
    _event_results_json,
)
from app.services.mlb_collection import (
    MlbBackfillEventResult,
    MlbBackfillRunResult,
    MlbRetrospectiveBackfillService,
)
from app.services.mlb_modeling.service import MlbGameFeatureService

NOW = datetime(2026, 8, 23, 12, tzinfo=UTC)
CHECKPOINT_ID = UUID("92000000-0000-0000-0000-000000000001")


def test_backfill_event_audit_payload_is_json_safe() -> None:
    event = MlbBackfillEventResult(
        event_id=UUID("92000000-0000-0000-0000-000000000010"),
        provider_event_id="823421",
        scheduled_start_time=NOW,
        stage="labeled",
        reason_code="retrospective_example_ready",
        lineup_snapshot_id=UUID("92000000-0000-0000-0000-000000000011"),
        statcast_snapshot_id=UUID("92000000-0000-0000-0000-000000000012"),
        game_feature_vector_id=UUID("92000000-0000-0000-0000-000000000013"),
        dataset_example_id=UUID("92000000-0000-0000-0000-000000000014"),
        split="test",
        lineup_created=True,
        statcast_created=True,
        feature_vector_created=True,
        dataset_example_created=True,
    )

    payload = _event_results_json((event,))

    assert json.loads(json.dumps(payload)) == payload
    assert payload[0]["event_id"] == str(event.event_id)
    assert payload[0]["scheduled_start_time"] == "2026-08-23T12:00:00Z"
    assert payload[0]["dataset_example_id"] == str(event.dataset_example_id)


def _readiness(
    *, train: int = 0, validation: int = 0, test: int = 14
) -> MlbDatasetReadinessAssessment:
    minimums = {
        MlbDatasetSplit.TRAIN: 500,
        MlbDatasetSplit.VALIDATION: 150,
        MlbDatasetSplit.TEST: 150,
        MlbDatasetSplit.PROSPECTIVE_HOLDOUT: 200,
    }
    eligible = {
        MlbDatasetSplit.TRAIN: train,
        MlbDatasetSplit.VALIDATION: validation,
        MlbDatasetSplit.TEST: test,
        MlbDatasetSplit.PROSPECTIVE_HOLDOUT: 0,
    }
    shortfalls = {split: max(minimums[split] - eligible[split], 0) for split in minimums}
    exploratory_ready = all(
        shortfalls[split] == 0
        for split in (
            MlbDatasetSplit.TRAIN,
            MlbDatasetSplit.VALIDATION,
            MlbDatasetSplit.TEST,
        )
    )
    return MlbDatasetReadinessAssessment(
        policy_name="mlb_dataset_readiness",
        policy_version="v1",
        policy_fingerprint="a" * 64,
        split_policy_fingerprint="b" * 64,
        minimum_split_counts=minimums,
        eligible_split_counts=eligible,
        shortfall_by_split=shortfalls,
        exploratory_fit_data_ready=exploratory_ready,
        prospective_evaluation_data_ready=False,
        blockers=tuple(
            f"{split.value}_shortfall:{count}"
            for split, count in shortfalls.items()
            if count > 0
        ),
    )


def _checkpoint(**overrides: object) -> MlbBackfillCheckpointRecord:
    values: dict[str, object] = {
        "id": CHECKPOINT_ID,
        "policy_fingerprint": "c" * 64,
        "state_fingerprint": "d" * 64,
        "status": "active",
        "regular_season_start": date(2026, 3, 25),
        "validation_start_date": date(2026, 6, 1),
        "test_start_date": date(2026, 7, 1),
        "prospective_holdout_start_date": date(2026, 8, 23),
        "train_cursor_date": date(2026, 5, 31),
        "train_cursor_offset": 0,
        "validation_cursor_date": date(2026, 6, 30),
        "validation_cursor_offset": 0,
        "test_cursor_date": date(2026, 8, 22),
        "test_cursor_offset": 0,
        "batch_limit": 10,
        "version": 0,
        "batches_completed": 0,
        "events_examined": 0,
        "examples_created": 0,
    }
    values.update(overrides)
    return cast(MlbBackfillCheckpointRecord, SimpleNamespace(**values))


class FakeRepository:
    def __init__(self, checkpoint: MlbBackfillCheckpointRecord) -> None:
        self.checkpoint = checkpoint
        self.persisted_plan: MlbBackfillPlan | None = None
        self.finalized_status: str | None = None

    async def get_or_create_checkpoint(self, _: object) -> MlbBackfillCheckpointRecord:
        return self.checkpoint

    async def persist_batch(self, **kwargs: object) -> tuple[
        MlbBackfillCheckpointRecord, MlbBackfillBatchRecord, bool
    ]:
        self.persisted_plan = cast(MlbBackfillPlan, kwargs["plan"])
        return (
            self.checkpoint,
            cast(MlbBackfillBatchRecord, SimpleNamespace(id=UUID(int=2))),
            True,
        )

    async def finalize_checkpoint(
        self, *, checkpoint: MlbBackfillCheckpointRecord, status: str
    ) -> MlbBackfillCheckpointRecord:
        self.finalized_status = status
        checkpoint.status = status
        return checkpoint


class FakeBackfillService:
    def __init__(self, *, examined: int, source_failure: bool = False) -> None:
        self.examined = examined
        self.source_failure = source_failure
        self.calls: list[dict[str, object]] = []

    async def run(self, **kwargs: object) -> MlbBackfillRunResult:
        self.calls.append(kwargs)
        result_counts = (
            {"official_source_unavailable": 1}
            if self.source_failure
            else {"retrospective_example_ready": self.examined}
        )
        events = tuple(
            MlbBackfillEventResult(
                event_id=UUID(int=index + 100),
                provider_event_id=str(index + 100),
                scheduled_start_time=NOW - timedelta(days=1),
                stage="failed" if self.source_failure else "labeled",
                reason_code=(
                    "official_source_unavailable"
                    if self.source_failure
                    else "retrospective_example_ready"
                ),
                dataset_example_created=not self.source_failure,
            )
            for index in range(self.examined)
        )
        return MlbBackfillRunResult(
            start_date=cast(date, kwargs["start_date"]),
            end_date=cast(date, kwargs["end_date"]),
            run_at=NOW,
            events_refreshed=15,
            examined=self.examined,
            retrospective_vectors_built=0 if self.source_failure else self.examined,
            examples_labeled=0 if self.source_failure else self.examined,
            result_counts=result_counts,
            events=events,
        )


class FakeFeatureService:
    def __init__(self, *assessments: MlbDatasetReadinessAssessment) -> None:
        self.assessments = list(assessments)

    async def approved_dataset_readiness(self) -> MlbDatasetReadinessAssessment:
        return self.assessments.pop(0)


def _service(
    *,
    repository: FakeRepository,
    backfill: FakeBackfillService,
    assessments: tuple[MlbDatasetReadinessAssessment, ...],
) -> MlbHistoricalBackfillWorkflowService:
    return MlbHistoricalBackfillWorkflowService(
        repository=cast(MlbBackfillWorkflowRepository, repository),
        backfill_service=cast(MlbRetrospectiveBackfillService, backfill),
        feature_service=cast(MlbGameFeatureService, FakeFeatureService(*assessments)),
        policy=approved_mlb_historical_backfill_policy(),
    )


async def _run_full_page() -> None:
    repository = FakeRepository(_checkpoint())
    backfill = FakeBackfillService(examined=10)
    service = _service(
        repository=repository,
        backfill=backfill,
        assessments=(_readiness(), _readiness(test=24)),
    )
    result = await service.run_once()

    assert result.action == "ran_batch"
    assert result.created is True
    assert backfill.calls == [
        {
            "start_date": date(2026, 8, 22),
            "end_date": date(2026, 8, 22),
            "limit": 10,
            "offset": 0,
        }
    ]
    assert repository.persisted_plan is not None
    assert repository.persisted_plan.split is MlbDatasetSplit.TEST


def test_workflow_starts_with_latest_test_page() -> None:
    asyncio.run(_run_full_page())


async def _switch_to_validation() -> None:
    repository = FakeRepository(_checkpoint())
    backfill = FakeBackfillService(examined=4)
    service = _service(
        repository=repository,
        backfill=backfill,
        assessments=(
            _readiness(test=150),
            _readiness(test=150, validation=4),
        ),
    )
    await service.run_once()

    assert backfill.calls[0]["start_date"] == date(2026, 6, 30)
    assert repository.persisted_plan is not None
    assert repository.persisted_plan.split is MlbDatasetSplit.VALIDATION


def test_workflow_switches_splits_when_a_threshold_is_met() -> None:
    asyncio.run(_switch_to_validation())


async def _complete_without_provider_call() -> None:
    repository = FakeRepository(_checkpoint())
    backfill = FakeBackfillService(examined=0)
    ready = _readiness(train=500, validation=150, test=150)
    service = _service(
        repository=repository,
        backfill=backfill,
        assessments=(ready,),
    )
    result = await service.run_once()

    assert result.action == "complete"
    assert result.batch is None
    assert backfill.calls == []
    assert repository.finalized_status == "complete"


def test_workflow_completes_without_touching_providers_when_ready() -> None:
    asyncio.run(_complete_without_provider_call())


async def _keep_terminal_checkpoint_closed() -> None:
    repository = FakeRepository(_checkpoint(status="exhausted"))
    backfill = FakeBackfillService(examined=0)
    service = _service(
        repository=repository,
        backfill=backfill,
        assessments=(_readiness(),),
    )
    result = await service.run_once()

    assert result.action == "exhausted"
    assert result.created is False
    assert result.batch is None
    assert backfill.calls == []
    assert repository.finalized_status is None


def test_workflow_never_reopens_a_terminal_checkpoint() -> None:
    asyncio.run(_keep_terminal_checkpoint_closed())


async def _retain_cursor_on_provider_failure() -> None:
    repository = FakeRepository(_checkpoint())
    backfill = FakeBackfillService(examined=1, source_failure=True)
    service = _service(
        repository=repository,
        backfill=backfill,
        assessments=(_readiness(),),
    )
    with pytest.raises(MlbBackfillWorkflowRetryableError, match="cursor retained"):
        await service.run_once()
    assert repository.persisted_plan is None


def test_workflow_retains_checkpoint_when_an_official_source_fails() -> None:
    asyncio.run(_retain_cursor_on_provider_failure())


async def _exhausted_train_range() -> None:
    repository = FakeRepository(
        _checkpoint(train_cursor_date=date(2026, 3, 24), train_cursor_offset=0)
    )
    backfill = FakeBackfillService(examined=0)
    service = _service(
        repository=repository,
        backfill=backfill,
        assessments=(_readiness(validation=150, test=150),),
    )
    result = await service.run_once()

    assert result.action == "exhausted"
    assert repository.finalized_status == "exhausted"
    assert backfill.calls == []


def test_workflow_fails_closed_when_regular_season_range_is_exhausted() -> None:
    asyncio.run(_exhausted_train_range())
