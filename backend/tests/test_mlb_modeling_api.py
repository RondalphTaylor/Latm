from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient

from app.api.mlb_modeling import get_mlb_game_feature_repository
from app.main import create_app

EVENT_ID = UUID("10000000-0000-0000-0000-000000000001")


class EmptyRepository:
    async def list_vectors(self, **_: object) -> list[object]:
        return []

    async def get_vector(self, _: UUID) -> None:
        return None


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
