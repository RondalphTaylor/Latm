from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.mlb_collection import (
    get_mlb_backfill_service,
    get_mlb_backfill_workflow_repository,
    get_mlb_backfill_workflow_service,
    get_mlb_collection_service,
)
from app.domain.mlb_modeling import MlbDatasetReadinessAssessment, MlbDatasetSplit
from app.main import create_app
from app.models.mlb import MlbBackfillBatchRecord, MlbBackfillCheckpointRecord
from app.services.mlb_backfill_workflow import MlbBackfillWorkflowRunResult
from app.services.mlb_collection import MlbBackfillRunResult, MlbCollectionRunResult


class FakeCollectionService:
    async def run(self, **_: object) -> MlbCollectionRunResult:
        return MlbCollectionRunResult(
            start_date=date(2026, 8, 22),
            end_date=date(2026, 8, 22),
            run_at=datetime(2026, 8, 22, 12, tzinfo=UTC),
            events_refreshed=15,
            examined=15,
            lineup_observed=0,
            complete_lineups=0,
            feature_vectors_built=0,
            operational_feature_vectors=0,
            result_counts={"first_pitch_reached": 15},
            events=(),
        )


class FakeBackfillService:
    async def run(self, **_: object) -> MlbBackfillRunResult:
        return MlbBackfillRunResult(
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 1),
            run_at=datetime(2026, 8, 22, 12, tzinfo=UTC),
            events_refreshed=15,
            examined=5,
            retrospective_vectors_built=4,
            examples_labeled=4,
            result_counts={"retrospective_example_ready": 4, "historical_lineup_incomplete": 1},
            events=(),
        )


def test_collection_api_is_bounded_research_only_and_has_no_trade_controls() -> None:
    app = create_app()
    app.dependency_overrides[get_mlb_collection_service] = FakeCollectionService
    with TestClient(app) as client:
        response = client.post(
            "/mlb-research-collection/run?start_date=2026-08-22&end_date=2026-08-22"
        )
        operation = client.get("/openapi.json").json()["paths"]["/mlb-research-collection/run"][
            "post"
        ]

    assert response.status_code == 200
    body = response.json()
    assert body["events_refreshed"] == 15
    assert body["research_only"] is True
    assert body["probability_generated"] is False
    assert body["automatic_trading_eligible"] is False
    assert [item["name"] for item in operation["parameters"]] == [
        "start_date",
        "end_date",
        "limit",
        "offset",
    ]
    assert "requestBody" not in operation


def test_backfill_api_is_bounded_and_keeps_probability_and_trading_disabled() -> None:
    app = create_app()
    app.dependency_overrides[get_mlb_backfill_service] = FakeBackfillService
    with TestClient(app) as client:
        response = client.post(
            "/mlb-research-backfill/run?start_date=2026-07-01&end_date=2026-07-01"
        )
        operation = client.get("/openapi.json").json()["paths"]["/mlb-research-backfill/run"][
            "post"
        ]

    assert response.status_code == 200
    body = response.json()
    assert body["examples_labeled"] == 4
    assert body["research_only"] is True
    assert body["probability_generated"] is False
    assert body["automatic_trading_eligible"] is False
    assert [item["name"] for item in operation["parameters"]] == [
        "start_date",
        "end_date",
        "limit",
        "offset",
    ]
    assert "requestBody" not in operation


def _workflow_checkpoint() -> MlbBackfillCheckpointRecord:
    return cast(
        MlbBackfillCheckpointRecord,
        SimpleNamespace(
            id=UUID("93000000-0000-0000-0000-000000000001"),
            policy_name="mlb_historical_backfill",
            policy_version="v1",
            policy_fingerprint="a" * 64,
            split_policy_fingerprint="b" * 64,
            status="active",
            regular_season_start=date(2026, 3, 25),
            validation_start_date=date(2026, 6, 1),
            test_start_date=date(2026, 7, 1),
            prospective_holdout_start_date=date(2026, 8, 23),
            train_cursor_date=date(2026, 5, 31),
            train_cursor_offset=0,
            validation_cursor_date=date(2026, 6, 30),
            validation_cursor_offset=0,
            test_cursor_date=date(2026, 8, 22),
            test_cursor_offset=10,
            batch_limit=10,
            version=1,
            batches_completed=1,
            events_examined=10,
            examples_created=8,
            last_run_at=datetime(2026, 8, 23, 12, tzinfo=UTC),
            finished_at=None,
            state_fingerprint="c" * 64,
            research_only=True,
            probability_generated=False,
            automatic_trading_eligible=False,
            created_at=datetime(2026, 8, 23, 12, tzinfo=UTC),
            updated_at=datetime(2026, 8, 23, 12, tzinfo=UTC),
        ),
    )


def _workflow_batch(checkpoint_id: UUID) -> MlbBackfillBatchRecord:
    readiness: dict[str, object] = {"eligible_split_counts": {"test": 22}}
    return cast(
        MlbBackfillBatchRecord,
        SimpleNamespace(
            id=UUID("93000000-0000-0000-0000-000000000002"),
            checkpoint_id=checkpoint_id,
            sequence=1,
            split="test",
            window_date=date(2026, 8, 22),
            offset=0,
            batch_limit=10,
            cursor_date_after=date(2026, 8, 22),
            cursor_offset_after=10,
            run_at=datetime(2026, 8, 23, 12, tzinfo=UTC),
            events_refreshed=15,
            examined=10,
            retrospective_vectors_built=8,
            examples_labeled=8,
            examples_created=8,
            result_counts={"retrospective_example_ready": 8, "historical_lineup_incomplete": 2},
            event_results=[],
            readiness_before=readiness,
            readiness_after=readiness,
            input_fingerprint="d" * 64,
            result_fingerprint="e" * 64,
            research_only=True,
            probability_generated=False,
            automatic_trading_eligible=False,
            created_at=datetime(2026, 8, 23, 12, tzinfo=UTC),
        ),
    )


def _workflow_readiness() -> MlbDatasetReadinessAssessment:
    minimums = {
        MlbDatasetSplit.TRAIN: 500,
        MlbDatasetSplit.VALIDATION: 150,
        MlbDatasetSplit.TEST: 150,
        MlbDatasetSplit.PROSPECTIVE_HOLDOUT: 200,
    }
    eligible = {
        MlbDatasetSplit.TRAIN: 0,
        MlbDatasetSplit.VALIDATION: 0,
        MlbDatasetSplit.TEST: 22,
        MlbDatasetSplit.PROSPECTIVE_HOLDOUT: 0,
    }
    shortfalls = {split: minimums[split] - eligible[split] for split in minimums}
    return MlbDatasetReadinessAssessment(
        policy_name="mlb_dataset_readiness",
        policy_version="v1",
        policy_fingerprint="f" * 64,
        split_policy_fingerprint="b" * 64,
        minimum_split_counts=minimums,
        eligible_split_counts=eligible,
        shortfall_by_split=shortfalls,
        exploratory_fit_data_ready=False,
        prospective_evaluation_data_ready=False,
        blockers=tuple(f"{split.value}_shortfall:{count}" for split, count in shortfalls.items()),
    )


class FakeWorkflowService:
    async def run_once(self) -> MlbBackfillWorkflowRunResult:
        checkpoint = _workflow_checkpoint()
        return MlbBackfillWorkflowRunResult(
            action="ran_batch",
            created=True,
            checkpoint=checkpoint,
            batch=_workflow_batch(checkpoint.id),
            readiness=_workflow_readiness(),
        )


class FakeWorkflowRepository:
    async def get_for_policy(self, _: str) -> MlbBackfillCheckpointRecord:
        return _workflow_checkpoint()

    async def list_batches(self, **_: object) -> list[MlbBackfillBatchRecord]:
        checkpoint = _workflow_checkpoint()
        return [_workflow_batch(checkpoint.id)]


def test_checkpointed_backfill_api_has_no_arbitrary_window_or_trading_controls() -> None:
    app = create_app()
    app.dependency_overrides[get_mlb_backfill_workflow_service] = FakeWorkflowService
    with TestClient(app) as client:
        response = client.post("/mlb-research-backfill-workflow/run")
        operation = client.get("/openapi.json").json()["paths"][
            "/mlb-research-backfill-workflow/run"
        ]["post"]

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "ran_batch"
    assert body["batch"]["split"] == "test"
    assert body["checkpoint"]["test_cursor_offset"] == 10
    assert body["research_only"] is True
    assert body["probability_generated"] is False
    assert body["automatic_trading_eligible"] is False
    assert operation.get("parameters", []) == []
    assert "requestBody" not in operation


def test_checkpoint_and_batch_history_reads_are_exposed() -> None:
    app = create_app()
    app.dependency_overrides[get_mlb_backfill_workflow_repository] = FakeWorkflowRepository
    with TestClient(app) as client:
        checkpoint = client.get("/mlb-research-backfill-workflow")
        batches = client.get("/mlb-research-backfill-workflow/batches")

    assert checkpoint.status_code == 200
    assert checkpoint.json()["batches_completed"] == 1
    assert batches.status_code == 200
    assert batches.json()[0]["sequence"] == 1
