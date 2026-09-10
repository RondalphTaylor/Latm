from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.nfl_opportunities import get_nfl_opportunity_repository, router
from app.core.config import Settings, get_settings
from app.models.nfl_opportunities import NflPaperOpportunityRecord


def record() -> NflPaperOpportunityRecord:
    now = datetime(2026, 9, 10, 16, tzinfo=UTC)
    return NflPaperOpportunityRecord(
        id=UUID(int=1),
        idempotency_key="test:comparison",
        forecast_id=UUID(int=2),
        market_id=UUID(int=3),
        match_id=UUID(int=4),
        event_id=UUID(int=5),
        price_id=UUID(int=6),
        price_retrieved_at=now,
        evaluated_at=now,
        valid_until=now + timedelta(minutes=15),
        yes_expected_payout=Decimal("0.600000"),
        no_expected_payout=Decimal("0.400000"),
        yes_direct_ask=Decimal("0.500000"),
        no_direct_ask=Decimal("0.550000"),
        yes_raw_edge=Decimal("0.100000"),
        no_raw_edge=Decimal("-0.150000"),
        yes_status="paper_candidate",
        no_status="ignore",
        yes_reason="candidate_threshold_met",
        no_reason="below_watch_threshold",
        policy_version="nfl-paper-raw-edge-v1",
        policy_fingerprint="a" * 64,
        input_fingerprint="b" * 64,
        execution_mode="paper",
        promotion_state="blocked",
        operational_eligible=False,
        trading_enabled=False,
        costs_included=False,
        depth_verified=False,
        audit={"price": {"yes_ask": "0.5"}},
    )


class StubRepository:
    def __init__(self, error: Exception | None = None, *, missing: bool = False) -> None:
        self.error = error
        self.missing = missing

    async def run(
        self, forecast_id: UUID, idempotency_key: str
    ) -> tuple[NflPaperOpportunityRecord, bool]:
        assert forecast_id == UUID(int=2) and idempotency_key == "test:comparison"
        if self.error is not None:
            raise self.error
        return record(), False

    async def get_opportunity(self, opportunity_id: UUID) -> NflPaperOpportunityRecord | None:
        return None if self.missing else record()

    async def list_opportunities(
        self, *, limit: int, offset: int
    ) -> list[NflPaperOpportunityRecord]:
        return [record()]


def application(repository: StubRepository) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_nfl_opportunity_repository] = lambda: repository
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="postgresql+asyncpg://test:test@localhost/test", _env_file=None
    )
    return app


def test_comparison_replay_keeps_both_sides_and_safety_flags() -> None:
    with TestClient(application(StubRepository())) as client:
        response = client.post(
            "/nfl-paper-opportunities/run",
            params={
                "forecast_id": str(UUID(int=2)),
                "idempotency_key": "test:comparison",
            },
        )
    assert response.status_code == 200
    assert response.json()["created"] is False
    row = response.json()["opportunity"]
    assert row["yes_raw_edge"] == "0.100000" and row["no_raw_edge"] == "-0.150000"
    assert row["yes_status"] == "paper_candidate" and row["no_status"] == "ignore"
    assert row["valid_until"] == "2026-09-10T16:15:00Z"
    assert row["trading_enabled"] is False and row["operational_eligible"] is False
    assert row["costs_included"] is False and row["depth_verified"] is False
    assert "audit" not in row


@pytest.mark.parametrize(
    "error,code", [(LookupError("missing"), 404), (ValueError("expired"), 409)]
)
def test_comparison_error_codes(error: Exception, code: int) -> None:
    with TestClient(application(StubRepository(error))) as client:
        response = client.post(
            "/nfl-paper-opportunities/run",
            params={
                "forecast_id": str(UUID(int=2)),
                "idempotency_key": "test:comparison",
            },
        )
    assert response.status_code == code


def test_list_is_history_and_detail_has_audit() -> None:
    with TestClient(application(StubRepository())) as client:
        rows = client.get("/nfl-paper-opportunities").json()
        detail = client.get(f"/nfl-paper-opportunities/{UUID(int=1)}").json()
    assert "audit" not in rows[0]
    assert detail["audit"]["price"]["yes_ask"] == "0.5"


def test_nonpaper_guard_and_missing_detail() -> None:
    app = application(StubRepository(missing=True))
    with TestClient(app) as client:
        assert client.get(f"/nfl-paper-opportunities/{UUID(int=1)}").status_code == 404
        app.dependency_overrides[get_settings] = lambda: Settings(
            database_url="postgresql+asyncpg://test:test@localhost/test", _env_file=None
        ).model_copy(update={"trading_mode": "live"})
        assert (
            client.post(
                "/nfl-paper-opportunities/run",
                params={
                    "forecast_id": str(UUID(int=2)),
                    "idempotency_key": "test:comparison",
                },
            ).status_code
            == 409
        )


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
def test_pagination_bounds(query: str) -> None:
    with TestClient(application(StubRepository())) as client:
        assert client.get(f"/nfl-paper-opportunities?{query}").status_code == 422


@pytest.mark.parametrize("key", ["", "bad key", "a" * 101])
def test_invalid_request_key(key: str) -> None:
    with TestClient(application(StubRepository())) as client:
        assert (
            client.post(
                "/nfl-paper-opportunities/run",
                params={
                    "forecast_id": str(UUID(int=2)),
                    "idempotency_key": key,
                },
            ).status_code
            == 422
        )
