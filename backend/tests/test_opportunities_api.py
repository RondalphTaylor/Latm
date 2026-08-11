from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.opportunities import get_opportunity_repository, get_opportunity_service
from app.domain.opportunities import OpportunityPolicy
from app.main import create_app
from app.models.forecasts import ModelVersionRecord
from app.models.opportunities import OpportunityRecord
from app.services.opportunities.engine import RawEdgeOpportunityEngine
from app.services.opportunities.service import OpportunityRunResult
from tests.test_opportunity_engine import evaluation_input

OPPORTUNITY_ID = UUID("40000000-0000-0000-0000-000000000001")
MARKET_ID = UUID("40d19d4f-817e-4b8e-b9fb-41ad7213d45f")
NOW = datetime(2026, 8, 8, 12, tzinfo=UTC)


def opportunity_record() -> OpportunityRecord:
    decision = RawEdgeOpportunityEngine(OpportunityPolicy()).evaluate(
        evaluation_input(market_probability=Decimal("0.550000"))
    )
    record = OpportunityRecord(id=OPPORTUNITY_ID, **decision.model_dump(mode="python"))
    record.model_version = ModelVersionRecord(
        id=decision.model_version_id,
        model_name="nba_elo",
        model_version="1.0.0+cfg.abcdef123456",
        algorithm="elo",
        configuration={},
        configuration_fingerprint="d" * 64,
        formula="fixture",
        description="fixture",
        created_at=NOW,
    )
    return record


class FakeOpportunityRepository:
    def __init__(self, record: OpportunityRecord | None = None) -> None:
        self.record = record
        self.arguments: dict[str, object] | None = None
        self.calls: list[dict[str, object]] = []

    async def list_opportunities(self, **kwargs: object) -> list[OpportunityRecord]:
        self.arguments = kwargs
        self.calls.append(kwargs)
        return [self.record] if self.record is not None else []

    async def get_opportunity(self, opportunity_id: UUID) -> OpportunityRecord | None:
        if self.record is not None and self.record.id == opportunity_id:
            return self.record
        return None


class FakeOpportunityService:
    async def run(
        self,
        *,
        start_date: date,
        end_date: date,
        market_id: UUID | None,
        limit: int,
        offset: int,
    ) -> OpportunityRunResult:
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        return OpportunityRunResult(
            strategy_name="raw_edge",
            strategy_version="1.0.0+cfg.abcdef123456",
            forecast_model_name="nba_elo",
            forecast_model_version="1.0.0+cfg.123456abcdef",
            start_date=start_date,
            end_date=end_date,
            examined=1,
            generated=2,
            persisted=2,
            yes_generated=1,
            no_generated=1,
            status_counts={"watch": 2},
            skip_counts={},
        )


def opportunity_client(
    repository: FakeOpportunityRepository,
    *,
    service: FakeOpportunityService | None = None,
) -> tuple[FastAPI, TestClient]:
    application = create_app()
    application.dependency_overrides[get_opportunity_repository] = lambda: repository
    if service is not None:
        application.dependency_overrides[get_opportunity_service] = lambda: service
    return application, TestClient(application)


def test_run_returns_directional_counts_and_skip_audit() -> None:
    _, client = opportunity_client(FakeOpportunityRepository(), service=FakeOpportunityService())

    with client:
        response = client.post(
            f"/opportunities/run?start_date=2026-08-08&end_date=2026-08-08&market_id={MARKET_ID}"
        )

    assert response.status_code == 200
    assert response.json()["generated"] == 2
    assert response.json()["yes_generated"] == 1
    assert response.json()["status_counts"] == {"watch": 2}


def test_list_detail_and_market_history_expose_audit_fields() -> None:
    repository = FakeOpportunityRepository(opportunity_record())
    _, client = opportunity_client(repository)

    with client:
        listed = client.get(
            f"/opportunities?latest_only=true&status=watch&direction=yes&market_id={MARKET_ID}"
            "&model_name=nba_elo&limit=25&offset=2"
        )
        detail = client.get(f"/opportunities/{OPPORTUNITY_ID}")
        history = client.get(f"/markets/{MARKET_ID}/opportunities")

    assert listed.status_code == 200
    assert listed.json()[0]["price_source"] == "direct_yes_ask"
    assert listed.json()[0]["raw_edge"] == "0.050000"
    assert listed.json()[0]["model"]["model_name"] == "nba_elo"
    assert detail.status_code == 200
    assert history.status_code == 200
    assert repository.calls[0]["current_only"] is True
    assert repository.arguments == {
        "latest_only": False,
        "current_only": False,
        "status": None,
        "direction": None,
        "market_id": MARKET_ID,
        "sports_event_id": None,
        "model_name": None,
        "model_version": None,
        "limit": 100,
        "offset": 0,
    }


def test_unknown_detail_and_invalid_range_return_clear_errors() -> None:
    _, client = opportunity_client(FakeOpportunityRepository(), service=FakeOpportunityService())

    with client:
        missing = client.get(f"/opportunities/{OPPORTUNITY_ID}")
        invalid = client.post("/opportunities/run?start_date=2026-08-09&end_date=2026-08-08")

    assert missing.status_code == 404
    assert missing.json() == {"detail": "opportunity not found"}
    assert invalid.status_code == 422
    assert invalid.json() == {"detail": "start_date must not be after end_date"}
