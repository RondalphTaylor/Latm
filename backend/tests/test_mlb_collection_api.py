from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi.testclient import TestClient

from app.api.mlb_collection import get_mlb_backfill_service, get_mlb_collection_service
from app.main import create_app
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
