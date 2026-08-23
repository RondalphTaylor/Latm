from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient

from app.api.mlb_modeling import (
    get_mlb_game_feature_repository,
    get_mlb_game_feature_service,
)
from app.domain.mlb_modeling import (
    MlbDatasetReadinessAssessment,
    MlbDatasetReadinessInput,
    MlbDatasetSplit,
    approved_mlb_dataset_readiness_policy,
)
from app.main import create_app
from app.services.mlb_modeling.engine import (
    DeterministicMlbDatasetReadinessEngine,
    mlb_chronological_split_policy_fingerprint,
)
from app.services.mlb_modeling.repository import (
    MlbCanonicalDatasetSelection,
    MlbDatasetInventory,
)

EVENT_ID = UUID("10000000-0000-0000-0000-000000000001")


class EmptyRepository:
    async def list_vectors(self, **_: object) -> list[object]:
        return []

    async def get_vector(self, _: UUID) -> None:
        return None


class InventoryService:
    async def label(self, **_: object) -> None:
        raise AssertionError("invalid split boundaries must fail before service execution")

    async def inventory(self, fingerprint: str) -> MlbDatasetInventory:
        return MlbDatasetInventory(
            split_policy_fingerprint=fingerprint,
            example_count=3,
            unique_event_count=2,
            operational_example_count=1,
            retrospective_example_count=2,
            split_counts={"train": 2, "test": 1},
            operational_split_counts={"test": 1},
            retrospective_split_counts={"train": 2},
        )

    async def canonical_dataset(self, **kwargs: object) -> MlbCanonicalDatasetSelection:
        return MlbCanonicalDatasetSelection(
            split_policy_fingerprint=str(kwargs["split_policy_fingerprint"]),
            include_retrospective_research=bool(kwargs["include_retrospective_research"]),
            selected_example_count=0,
            operational_example_count=0,
            retrospective_example_count=0,
            split_counts={},
            operational_split_counts={},
            retrospective_split_counts={},
            examples=(),
        )

    async def approved_dataset_readiness(self) -> MlbDatasetReadinessAssessment:
        policy = approved_mlb_dataset_readiness_policy()
        split_fingerprint = mlb_chronological_split_policy_fingerprint(policy.split_policy)
        return DeterministicMlbDatasetReadinessEngine().evaluate(
            MlbDatasetReadinessInput(
                split_policy_fingerprint=split_fingerprint,
                operational_split_counts={MlbDatasetSplit.PROSPECTIVE_HOLDOUT: 12},
                retrospective_split_counts={MlbDatasetSplit.TRAIN: 120},
                policy=policy,
            )
        )


def test_model_design_exposes_frozen_research_only_boundary() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/mlb-model-design")

    assert response.status_code == 200
    body = response.json()
    assert body["candidate_name"] == "mlb_pregame_regularized_logistic"
    assert len(body["selected_features"]) == 8
    assert body["validation_strategy"].startswith("chronological")
    assert body["random_shuffle"] is False
    assert body["fitted_model_available"] is False
    assert body["probability_generation_enabled"] is False
    assert body["automatic_trading_enabled"] is False


def test_read_routes_are_bounded_and_missing_detail_is_404() -> None:
    app = create_app()
    app.dependency_overrides[get_mlb_game_feature_repository] = EmptyRepository
    with TestClient(app) as client:
        listed = client.get(f"/events/{EVENT_ID}/mlb-game-features?limit=10")
        invalid = client.get("/mlb-game-features?limit=101")
        missing = client.get(f"/mlb-game-features/{EVENT_ID}")

    assert listed.status_code == 200
    assert listed.json() == []
    assert invalid.status_code == 422
    assert missing.status_code == 404


def test_openapi_build_has_one_explicit_source_and_no_probability_or_trade_input() -> None:
    with TestClient(create_app()) as client:
        operation = client.get("/openapi.json").json()["paths"]["/mlb-game-features/run"]["post"]

    assert [item["name"] for item in operation["parameters"]] == ["statcast_snapshot_id"]
    assert "requestBody" not in operation


def test_dataset_inventory_separates_provenance_and_keeps_model_disabled() -> None:
    app = create_app()
    app.dependency_overrides[get_mlb_game_feature_service] = InventoryService
    with TestClient(app) as client:
        response = client.get(f"/mlb-dataset-readiness?split_policy_fingerprint={'a' * 64}")

    assert response.status_code == 200
    body = response.json()
    assert body["example_count"] == 3
    assert body["unique_event_count"] == 2
    assert body["duplicate_event_example_count"] == 1
    assert body["operational_example_count"] == 1
    assert body["retrospective_example_count"] == 2
    assert body["canonical_training_dataset_available"] is False
    assert body["model_fitting_enabled"] is False
    assert body["probability_generation_enabled"] is False
    assert body["automatic_trading_enabled"] is False
    assert any("retrospective" in warning for warning in body["warnings"])


def test_dataset_label_boundaries_fail_validation_before_service() -> None:
    app = create_app()
    app.dependency_overrides[get_mlb_game_feature_service] = InventoryService
    query = (
        f"game_feature_vector_id={EVENT_ID}&"
        "validation_start=2026-07-01T00:00:00Z&"
        "test_start=2026-06-01T00:00:00Z&"
        "prospective_holdout_start=2026-08-01T00:00:00Z"
    )
    with TestClient(app) as client:
        response = client.post(f"/mlb-dataset-examples/run?{query}")

    assert response.status_code == 422


def test_canonical_dataset_contract_remains_non_fitting_and_non_trading() -> None:
    app = create_app()
    app.dependency_overrides[get_mlb_game_feature_service] = InventoryService
    with TestClient(app) as client:
        response = client.get(f"/mlb-canonical-dataset?split_policy_fingerprint={'a' * 64}")

    assert response.status_code == 200
    body = response.json()
    assert body["selected_example_count"] == 0
    assert body["include_retrospective_research"] is False
    assert body["canonical_selection_policy"].startswith("one_per_event")
    assert body["minimum_sample_threshold_approved"] is True
    assert body["model_fitting_enabled"] is False
    assert body["automatic_trading_enabled"] is False


def test_approved_dataset_readiness_exposes_thresholds_and_shortfalls() -> None:
    app = create_app()
    app.dependency_overrides[get_mlb_game_feature_service] = InventoryService
    with TestClient(app) as client:
        response = client.get("/mlb-approved-dataset-readiness")

    assert response.status_code == 200
    body = response.json()
    assert body["validation_start"] == "2026-06-01T00:00:00Z"
    assert body["test_start"] == "2026-07-01T00:00:00Z"
    assert body["prospective_holdout_start"] == "2026-08-23T00:00:00Z"
    assert body["minimum_split_counts"] == {
        "train": 500,
        "validation": 150,
        "test": 150,
        "prospective_holdout": 200,
    }
    assert body["eligible_split_counts"]["train"] == 120
    assert body["eligible_split_counts"]["prospective_holdout"] == 12
    assert body["shortfall_by_split"]["train"] == 380
    assert body["shortfall_by_split"]["prospective_holdout"] == 188
    assert body["exploratory_fit_data_ready"] is False
    assert body["model_fitting_enabled"] is False
    assert body["probability_generation_enabled"] is False
    assert body["automatic_trading_enabled"] is False
