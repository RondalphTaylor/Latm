from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.nfl_shadow_evaluation import get_nfl_shadow_evaluation_repository, router
from app.core.config import Settings, get_settings
from app.models.nfl_shadow_evaluation import NflShadowEvaluationRecord
from app.services.nfl_research.shadow_evaluation_repository import NflShadowCanonicalPerformance


def label_record() -> NflShadowEvaluationRecord:
    return NflShadowEvaluationRecord(
        id=UUID(int=1),
        snapshot_id=UUID(int=2),
        sports_event_id=UUID(int=3),
        model_version="nfl-shadow-frozen-preseason2026-v1",
        seed_fingerprint="a" * 64,
        evaluation_version="nfl-shadow-payout-evaluation-v1",
        snapshot_fingerprint="b" * 64,
        result_fingerprint="c" * 64,
        input_fingerprint="d" * 64,
        label_time=datetime(2026, 9, 14, tzinfo=UTC),
        generated_at=datetime(2026, 9, 10, tzinfo=UTC),
        scheduled_start_time=datetime(2026, 9, 13, 17, tzinfo=UTC),
        result_source_last_seen_at=datetime(2026, 9, 13, 21, tzinfo=UTC),
        expected_home_payout=Decimal("0.600000"),
        expected_yes_payout=Decimal("0.400000"),
        actual_home_payout=Decimal("0.500000"),
        actual_yes_payout=Decimal("0.500000"),
        squared_home_payout_error=Decimal("0.010000000000"),
        constant_half_squared_error=Decimal("0.000000000000"),
        research_only=True,
        trading_enabled=False,
        audit={"result": {"home_score": 20, "away_score": 20}},
    )


class StubRepository:
    def __init__(self, error: Exception | None = None, *, missing: bool = False) -> None:
        self.error = error
        self.missing = missing

    async def run(self, snapshot_id: UUID) -> tuple[NflShadowEvaluationRecord, bool]:
        assert snapshot_id == UUID(int=2)
        if self.error is not None:
            raise self.error
        return label_record(), False

    async def get_label(self, label_id: UUID) -> NflShadowEvaluationRecord | None:
        assert label_id == UUID(int=1)
        return None if self.missing else label_record()

    async def list_labels(self, *, limit: int, offset: int) -> list[NflShadowEvaluationRecord]:
        assert limit > 0 and offset >= 0
        return [label_record()]

    async def performance(self) -> NflShadowCanonicalPerformance:
        if self.error is not None:
            raise self.error
        return NflShadowCanonicalPerformance(
            total_snapshots=2,
            canonical_snapshots=1,
            labeled=0,
            pending_result=1,
            pending_label=0,
            ineligible=0,
            reason_counts={"pending_result": 1},
            groups=(),
        )


def application(repository: StubRepository) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_nfl_shadow_evaluation_repository] = lambda: repository
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="postgresql+asyncpg://test:test@localhost/test", _env_file=None
    )
    return app


def test_label_replay_preserves_tie_and_exact_decimal_score() -> None:
    with TestClient(application(StubRepository())) as client:
        response = client.post("/nfl-shadow-labels/run", params={"snapshot_id": str(UUID(int=2))})
    assert response.status_code == 200
    body = response.json()
    assert body["created"] is False
    assert body["label"]["actual_home_payout"] == "0.500000"
    assert body["label"]["squared_home_payout_error"] == "0.010000000000"
    assert body["label"]["settlement_performed"] is False
    assert body["label"]["trading_enabled"] is False
    assert "audit" not in body["label"]


@pytest.mark.parametrize(
    ("error", "status"),
    [(LookupError("snapshot not found"), 404), (ValueError("result is not final"), 409)],
)
def test_label_errors_do_not_return_fake_scores(error: Exception, status: int) -> None:
    with TestClient(application(StubRepository(error))) as client:
        response = client.post("/nfl-shadow-labels/run", params={"snapshot_id": str(UUID(int=2))})
    assert response.status_code == status
    assert response.json() == {"detail": str(error)}


def test_label_list_is_compact_and_detail_has_frozen_result() -> None:
    with TestClient(application(StubRepository())) as client:
        rows = client.get("/nfl-shadow-labels").json()
        detail = client.get(f"/nfl-shadow-labels/{UUID(int=1)}").json()
    assert "audit" not in rows[0]
    assert detail["audit"]["result"]["home_score"] == 20


def test_missing_label_is_404() -> None:
    with TestClient(application(StubRepository(missing=True))) as client:
        response = client.get(f"/nfl-shadow-labels/{UUID(int=1)}")
    assert response.status_code == 404


def test_performance_keeps_pending_games_unscored() -> None:
    with TestClient(application(StubRepository())) as client:
        response = client.get("/nfl-shadow-performance")
    assert response.status_code == 200
    assert response.json()["groups"] == []
    assert response.json()["pending_result"] == 1
    assert response.json()["canonical_snapshots"] == 1
    assert response.json()["trading_enabled"] is False


def test_performance_integrity_failure_is_conflict() -> None:
    with TestClient(application(StubRepository(ValueError("integrity_failure")))) as client:
        response = client.get("/nfl-shadow-performance")
    assert response.status_code == 409
    assert response.json() == {"detail": "integrity_failure"}


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
def test_label_read_pagination_bounds(query: str) -> None:
    with TestClient(application(StubRepository())) as client:
        response = client.get(f"/nfl-shadow-labels?{query}")
    assert response.status_code == 422
