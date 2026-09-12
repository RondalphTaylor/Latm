from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from app.api.nfl_pilot import router
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.models.nfl_pilot import NflPilotEntryRecord
from app.services.nfl_pilot.entries import NflPilotEntryService
from app.services.nfl_pilot.lifecycle import NflPilotLifecycleService


def entry() -> NflPilotEntryRecord:
    return NflPilotEntryRecord(
        id=UUID(int=1),
        idempotency_key="pilot:entry",
        scenario_id=UUID(int=2),
        portfolio_id=UUID(int=3),
        preflight_id=UUID(int=4),
        opportunity_id=UUID(int=5),
        market_id=UUID(int=6),
        direction="yes",
        entered_at=datetime(2026, 9, 11, tzinfo=UTC),
        status="filled",
        quantity=2,
        gross_cost=Decimal("0.80"),
        estimated_fee=Decimal("0.01"),
        total_cost=Decimal("0.81"),
        adjusted_edge=Decimal("0.100000"),
        minimum_adjusted_edge=Decimal("0.030000"),
        entry_cap=Decimal("1.00"),
        aggregate_cap=Decimal("5.00"),
        execution_mode="paper",
        live_trading_enabled=False,
        policy_version="nfl-paper-pilot-entry-v1",
        policy_fingerprint="a" * 64,
        audit={},
    )


def application() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: object()
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="postgresql+asyncpg://test:test@localhost/test", _env_file=None
    )
    return app


def test_pilot_entry_is_explicitly_paper_only(monkeypatch: MonkeyPatch) -> None:
    async def run_stub(
        self: NflPilotEntryService,
        scenario_id: UUID,
        preflight_id: UUID,
        idempotency_key: str,
    ) -> tuple[NflPilotEntryRecord, bool]:
        assert scenario_id == UUID(int=2) and preflight_id == UUID(int=4)
        assert idempotency_key == "pilot:entry"
        return entry(), True

    monkeypatch.setattr(NflPilotEntryService, "run", run_stub)
    app = application()
    with TestClient(app) as client:
        response = client.post(
            "/nfl-pilot-entries/run",
            params={
                "scenario_id": str(UUID(int=2)),
                "preflight_id": str(UUID(int=4)),
                "idempotency_key": "pilot:entry",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True and body["entry"]["total_cost"] == "0.81"
    assert body["entry"]["execution_mode"] == "paper"
    assert body["entry"]["live_trading_enabled"] is False


def test_pilot_entry_rejects_nonpaper_mode() -> None:
    app = application()
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="postgresql+asyncpg://test:test@localhost/test", _env_file=None
    ).model_copy(update={"trading_mode": "live"})
    with TestClient(app) as client:
        response = client.post(
            "/nfl-pilot-entries/run",
            params={
                "scenario_id": str(UUID(int=2)),
                "preflight_id": str(UUID(int=4)),
                "idempotency_key": "pilot:entry",
            },
        )
    assert response.status_code == 409


def test_pilot_monitor_reports_stale_quote_skip(monkeypatch: MonkeyPatch) -> None:
    async def monitor_stub(
        self: NflPilotLifecycleService, scenario_id: UUID
    ) -> tuple[int, int, int]:
        assert scenario_id == UUID(int=2)
        return 1, 0, 1

    monkeypatch.setattr(NflPilotLifecycleService, "monitor", monitor_stub)
    with TestClient(application()) as client:
        response = client.post(f"/nfl-pilot-monitor/run?scenario_id={UUID(int=2)}")
    assert response.status_code == 200
    assert response.json() == {"examined": 1, "marks_created": 0, "skipped": 1}
