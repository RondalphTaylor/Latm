from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.nfl_shadow import get_nfl_shadow_repository, router
from app.core.config import Settings, get_settings
from app.models.nfl_shadow import NflShadowForecastRecord


def snapshot() -> NflShadowForecastRecord:
    return NflShadowForecastRecord(
        id=UUID(int=1),
        match_id=UUID(int=2),
        market_id=UUID(int=3),
        sports_event_id=UUID(int=4),
        yes_team_id=UUID(int=5),
        model_version="nfl-shadow-frozen-2026-v1",
        seed_fingerprint="a" * 64,
        input_fingerprint="b" * 64,
        generated_at=datetime(2026, 9, 10, 12, tzinfo=UTC),
        scheduled_start_time=datetime(2026, 9, 14, 0, tzinfo=UTC),
        target_source_last_seen_at=datetime(2026, 9, 10, 11, tzinfo=UTC),
        expected_home_payout=Decimal("0.550000"),
        expected_away_payout=Decimal("0.450000"),
        expected_yes_payout=Decimal("0.550000"),
        expected_no_payout=Decimal("0.450000"),
        research_only=True,
        trading_enabled=False,
        audit={"seed_inputs": [], "target": {"season": 2026}},
    )


class StubRepository:
    def __init__(self, *, error: Exception | None = None, missing: bool = False) -> None:
        self.error = error
        self.missing = missing

    async def run(self, match_id: UUID) -> tuple[NflShadowForecastRecord, bool]:
        assert match_id == UUID(int=2)
        if self.error is not None:
            raise self.error
        return snapshot(), False

    async def list_snapshots(self, *, limit: int, offset: int) -> list[NflShadowForecastRecord]:
        assert limit > 0 and offset >= 0
        return [snapshot()]

    async def get_snapshot(self, snapshot_id: UUID) -> NflShadowForecastRecord | None:
        assert snapshot_id == UUID(int=1)
        return None if self.missing else snapshot()


def application(repository: StubRepository) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_nfl_shadow_repository] = lambda: repository
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="postgresql+asyncpg://test:test@localhost/test", _env_file=None
    )
    return app


def test_shadow_api_replay_preserves_decimal_payouts_and_safety() -> None:
    with TestClient(application(StubRepository())) as client:
        response = client.post("/nfl-shadow-forecasts/run", params={"match_id": str(UUID(int=2))})
    assert response.status_code == 200
    assert response.json()["created"] is False
    row = response.json()["snapshot"]
    assert row["expected_yes_payout"] == "0.550000"
    assert row["research_only"] is True and row["trading_enabled"] is False
    assert row["model_basis"] == "frozen_preseason_2026"
    assert "audit" not in row


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [(LookupError("match not found"), 404), (ValueError("kickoff has passed"), 409)],
)
def test_shadow_api_failures_are_explicit(error: Exception, expected_status: int) -> None:
    with TestClient(application(StubRepository(error=error))) as client:
        response = client.post("/nfl-shadow-forecasts/run", params={"match_id": str(UUID(int=2))})
    assert response.status_code == expected_status
    assert response.json()["detail"] == str(error)


def test_shadow_list_is_compact_and_detail_includes_evidence() -> None:
    with TestClient(application(StubRepository())) as client:
        rows = client.get("/nfl-shadow-forecasts").json()
        detail = client.get(f"/nfl-shadow-forecasts/{UUID(int=1)}").json()
    assert "audit" not in rows[0]
    assert detail["audit"]["target"]["season"] == 2026


def test_shadow_missing_detail_returns_404() -> None:
    with TestClient(application(StubRepository(missing=True))) as client:
        response = client.get(f"/nfl-shadow-forecasts/{UUID(int=1)}")
    assert response.status_code == 404


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
def test_shadow_list_is_bounded(query: str) -> None:
    with TestClient(application(StubRepository())) as client:
        response = client.get(f"/nfl-shadow-forecasts?{query}")
    assert response.status_code == 422
