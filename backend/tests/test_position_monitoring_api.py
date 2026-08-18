from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.position_monitoring import (
    get_position_monitoring_repository,
    get_position_monitoring_service,
)
from app.main import create_app
from app.models.execution import PaperPositionRecord, PositionEventRecord
from app.services.position_monitoring.service import (
    PositionMonitoringResult,
    PositionMonitoringRunResult,
)
from tests.test_execution_api import POSITION_ID
from tests.test_position_monitoring_service import FakeMonitoringRepository, service

UNKNOWN_ID = UUID("89000000-0000-0000-0000-000000000099")


class FakeApiMonitoringService:
    def __init__(
        self,
        result: PositionMonitoringRunResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def run(self, **kwargs: object) -> PositionMonitoringRunResult:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise AssertionError("fake monitoring service has no result")
        return self.result


class FakeApiMonitoringRepository:
    def __init__(
        self,
        *,
        event: PositionEventRecord,
        position: PaperPositionRecord,
    ) -> None:
        self.event = event
        self.position = position
        self.filters: dict[str, object] | None = None

    async def list_events(self, **kwargs: object) -> list[PositionEventRecord]:
        self.filters = kwargs
        return [self.event]

    async def get_event(self, event_id: UUID) -> PositionEventRecord | None:
        return self.event if event_id == self.event.id else None

    async def get_position(self, position_id: UUID) -> PaperPositionRecord | None:
        return self.position if position_id == self.position.id else None


def _created_result() -> PositionMonitoringResult:
    repository = FakeMonitoringRepository()
    return asyncio.run(service(repository).evaluate(POSITION_ID))


def _run_result(item: PositionMonitoringResult) -> PositionMonitoringRunResult:
    return PositionMonitoringRunResult(
        examined=1,
        results=(item,),
        decision_counts={item.event.decision: 1},
        reason_counts={item.event.reason_code: 1},
    )


def api_client(
    *,
    monitoring_service: FakeApiMonitoringService | None = None,
    repository: FakeApiMonitoringRepository | None = None,
) -> tuple[FastAPI, TestClient]:
    application = create_app()
    if monitoring_service is not None:
        application.dependency_overrides[get_position_monitoring_service] = lambda: (
            monitoring_service
        )
    if repository is not None:
        application.dependency_overrides[get_position_monitoring_repository] = lambda: repository
    return application, TestClient(application)


def test_run_returns_bounded_audit_summary_and_forwards_scope() -> None:
    item = _created_result()
    monitoring = FakeApiMonitoringService(result=_run_result(item))
    _, client = api_client(monitoring_service=monitoring)

    with client:
        response = client.post(
            f"/position-monitoring/run?position_id={POSITION_ID}&limit=25&offset=2"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["examined"] == payload["created"] == 1
    assert payload["replayed"] == payload["snapshots_appended"] == 0
    assert payload["decision_counts"] == {"hold": 1}
    assert payload["results"][0]["event"]["position_id"] == str(POSITION_ID)
    assert payload["results"][0]["position"]["status"] == "open"
    assert monitoring.calls == [
        {
            "position_id": POSITION_ID,
            "portfolio_id": None,
            "limit": 25,
            "offset": 2,
        }
    ]


def test_run_maps_unknown_position_to_404() -> None:
    monitoring = FakeApiMonitoringService(error=LookupError("position not found"))
    _, client = api_client(monitoring_service=monitoring)

    with client:
        response = client.post(f"/position-monitoring/run?position_id={UNKNOWN_ID}")

    assert response.status_code == 404
    assert response.json() == {"detail": "position not found"}


def test_event_lists_details_and_nested_history_are_auditable() -> None:
    item = _created_result()
    repository = FakeApiMonitoringRepository(event=item.event, position=item.position)
    _, client = api_client(repository=repository)

    with client:
        listing = client.get(
            f"/position-events?position_id={POSITION_ID}&portfolio_id={item.position.portfolio_id}"
            f"&market_id={item.position.market_id}&decision=hold"
            "&reason_code=minimum_hold_edge_met&policy_version=v1&limit=20&offset=3"
        )
        detail = client.get(f"/position-events/{item.event.id}")
        missing = client.get(f"/position-events/{UNKNOWN_ID}")
        nested = client.get(f"/positions/{POSITION_ID}/events?limit=10&offset=1")
        missing_position = client.get(f"/positions/{UNKNOWN_ID}/events")

    assert listing.status_code == detail.status_code == nested.status_code == 200
    assert listing.json()[0]["id"] == detail.json()["id"] == str(item.event.id)
    assert nested.json()[0]["position_id"] == str(POSITION_ID)
    assert missing.status_code == missing_position.status_code == 404
    assert repository.filters == {
        "position_id": POSITION_ID,
        "portfolio_id": None,
        "market_id": None,
        "decision": None,
        "reason_code": None,
        "policy_version": None,
        "limit": 10,
        "offset": 1,
    }


def test_invalid_filters_and_live_controls_are_not_in_contract() -> None:
    item = _created_result()
    monitoring = FakeApiMonitoringService(result=_run_result(item))
    repository = FakeApiMonitoringRepository(event=item.event, position=item.position)
    application, client = api_client(
        monitoring_service=monitoring,
        repository=repository,
    )
    operation = application.openapi()["paths"]["/position-monitoring/run"]["post"]

    assert {parameter["name"] for parameter in operation["parameters"]} == {
        "position_id",
        "portfolio_id",
        "limit",
        "offset",
    }
    assert "requestBody" not in operation

    with client:
        invalid_action = client.get("/position-events?decision=increase")
        invalid_limit = client.post("/position-monitoring/run?limit=501")
        harmless_extra = client.post(
            f"/position-monitoring/run?position_id={POSITION_ID}"
            "&trading_mode=live&provider_order_id=external"
        )

    assert invalid_action.status_code == invalid_limit.status_code == 422
    assert harmless_extra.status_code == 200
    assert monitoring.calls == [
        {
            "position_id": POSITION_ID,
            "portfolio_id": None,
            "limit": 100,
            "offset": 0,
        }
    ]
