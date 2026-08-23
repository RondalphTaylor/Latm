from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient

from app.api.mlb_modeling import (
    get_mlb_game_feature_repository,
    get_mlb_game_feature_service,
)
from app.main import create_app
from app.services.mlb_modeling.repository import MlbDatasetInventory

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
