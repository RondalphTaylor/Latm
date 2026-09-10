from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.nfl_forecasting import get_nfl_forecasting_repository, router
from app.core.config import Settings, get_settings
from app.models.nfl_forecasting import NflPayoutForecastRecord


def forecast() -> NflPayoutForecastRecord:
    generated = datetime(2026, 9, 10, 15, tzinfo=UTC)
    return NflPayoutForecastRecord(
        id=UUID(int=1),
        idempotency_key="test:forecast",
        match_id=UUID(int=2),
        market_id=UUID(int=3),
        event_id=UUID(int=4),
        source_shadow_snapshot_id=UUID(int=5),
        home_team_id=UUID(int=6),
        away_team_id=UUID(int=7),
        yes_team_id=UUID(int=6),
        model_version="nfl-shadow-frozen-preseason2026-v1",
        seed_fingerprint="a" * 64,
        generated_at=generated,
        valid_until=generated + timedelta(minutes=15),
        expected_home_payout=Decimal("0.600000"),
        expected_away_payout=Decimal("0.400000"),
        expected_yes_payout=Decimal("0.600000"),
        expected_no_payout=Decimal("0.400000"),
        purpose="paper_candidate",
        metric_kind="expected_payout",
        execution_mode="paper",
        promotion_state="blocked",
        operational_eligible=False,
        trading_enabled=False,
        input_fingerprint="b" * 64,
        audit={"prediction": {"expected_home_payout": "0.600000"}},
    )


class StubRepository:
    def __init__(self, error: Exception | None = None, *, missing: bool = False) -> None:
        self.error = error
        self.missing = missing

    async def run(
        self, match_id: UUID, idempotency_key: str
    ) -> tuple[NflPayoutForecastRecord, bool]:
        assert match_id == UUID(int=2) and idempotency_key == "test:forecast"
        if self.error is not None:
            raise self.error
        return forecast(), False

    async def list_forecasts(self, *, limit: int, offset: int) -> list[NflPayoutForecastRecord]:
        return [forecast()]

    async def get_forecast(self, forecast_id: UUID) -> NflPayoutForecastRecord | None:
        return None if self.missing else forecast()


def application(repository: StubRepository) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_nfl_forecasting_repository] = lambda: repository
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="postgresql+asyncpg://test:test@localhost/test", _env_file=None
    )
    return app


def test_candidate_replay_never_renews_expiry_or_promotes() -> None:
    with TestClient(application(StubRepository())) as client:
        response = client.post(
            "/nfl-operational-forecasts/run",
            params={
                "match_id": str(UUID(int=2)),
                "idempotency_key": "test:forecast",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["created"] is False
    assert body["forecast"]["expected_yes_payout"] == "0.600000"
    assert body["forecast"]["valid_until"] == "2026-09-10T15:15:00Z"
    assert body["forecast"]["operational_eligible"] is False
    assert body["forecast"]["trading_enabled"] is False
    assert body["forecast"]["promotion_state"] == "blocked"
    assert "audit" not in body["forecast"]


@pytest.mark.parametrize("error,code", [(LookupError("missing"), 404), (ValueError("stale"), 409)])
def test_forecast_failure_is_explicit(error: Exception, code: int) -> None:
    with TestClient(application(StubRepository(error))) as client:
        response = client.post(
            "/nfl-operational-forecasts/run",
            params={
                "match_id": str(UUID(int=2)),
                "idempotency_key": "test:forecast",
            },
        )
    assert response.status_code == code


@pytest.mark.parametrize("key", ["", "bad key", "a" * 101, "\ninvalid"])
def test_invalid_idempotency_keys_are_rejected(key: str) -> None:
    with TestClient(application(StubRepository())) as client:
        response = client.post(
            "/nfl-operational-forecasts/run",
            params={
                "match_id": str(UUID(int=2)),
                "idempotency_key": key,
            },
        )
    assert response.status_code == 422


def test_candidate_history_is_compact_and_detail_preserves_audit() -> None:
    with TestClient(application(StubRepository())) as client:
        rows = client.get("/nfl-operational-forecasts").json()
        detail = client.get(f"/nfl-operational-forecasts/{UUID(int=1)}").json()
    assert "audit" not in rows[0]
    assert detail["audit"]["prediction"]["expected_home_payout"] == "0.600000"


def test_missing_candidate_is_404() -> None:
    with TestClient(application(StubRepository(missing=True))) as client:
        assert client.get(f"/nfl-operational-forecasts/{UUID(int=1)}").status_code == 404


def test_nonpaper_runtime_cannot_run_candidate_generation() -> None:
    app = application(StubRepository())
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="postgresql+asyncpg://test:test@localhost/test", _env_file=None
    ).model_copy(update={"trading_mode": "live"})
    with TestClient(app) as client:
        response = client.post(
            "/nfl-operational-forecasts/run",
            params={
                "match_id": str(UUID(int=2)),
                "idempotency_key": "test:forecast",
            },
        )
    assert response.status_code == 409
    assert response.json()["detail"] == "NFL forecast candidates require paper mode"


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
def test_history_pagination_is_bounded(query: str) -> None:
    with TestClient(application(StubRepository())) as client:
        assert client.get(f"/nfl-operational-forecasts?{query}").status_code == 422
