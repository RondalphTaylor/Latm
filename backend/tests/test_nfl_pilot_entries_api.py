from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from app.api.nfl_pilot import _audit_export_fingerprint, router
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
    ) -> tuple[int, int, int, int, int, int, int, int, int, int, int, int]:
        assert scenario_id == UUID(int=2)
        return 1, 1, 0, 1, 0, 0, 0, 1, 1, 0, 0, 1

    monkeypatch.setattr(NflPilotLifecycleService, "monitor", monitor_stub)
    with TestClient(application()) as client:
        response = client.post(f"/nfl-pilot-monitor/run?scenario_id={UUID(int=2)}")
    assert response.status_code == 200
    assert response.json() == {
        "examined": 1,
        "quote_checks_created": 1,
        "fresh": 0,
        "stale": 1,
        "unusable": 0,
        "missing": 0,
        "marks_created": 0,
        "skipped": 1,
        "holds": 1,
        "reduces": 0,
        "closes": 0,
        "attention_required": 1,
    }


def test_recommendation_audit_accepts_only_bounded_recommendation_filters(
    monkeypatch: MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def audit_stub(
        self: NflPilotLifecycleService,
        scenario_id: UUID,
        recommendation: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, object]]:
        captured.update(
            scenario_id=scenario_id,
            recommendation=recommendation,
            limit=limit,
            offset=offset,
        )
        return []

    monkeypatch.setattr(NflPilotLifecycleService, "recommendation_audit", audit_stub)
    with TestClient(application()) as client:
        response = client.get(
            f"/nfl-pilot-monitor/audit?scenario_id={UUID(int=2)}&recommendation=reduce"
        )
        invalid_response = client.get(
            f"/nfl-pilot-monitor/audit?scenario_id={UUID(int=2)}&recommendation=buy"
        )

    assert response.status_code == 200
    assert captured == {
        "scenario_id": UUID(int=2),
        "recommendation": "reduce",
        "limit": 8,
        "offset": 0,
    }
    assert invalid_response.status_code == 422


def test_recommendation_audit_detail_is_scenario_scoped_and_read_only(
    monkeypatch: MonkeyPatch,
) -> None:
    captured: dict[str, UUID] = {}

    async def detail_stub(
        self: NflPilotLifecycleService, scenario_id: UUID, decision_id: UUID
    ) -> None:
        captured.update(scenario_id=scenario_id, decision_id=decision_id)
        return None

    monkeypatch.setattr(NflPilotLifecycleService, "recommendation_audit_detail", detail_stub)
    with TestClient(application()) as client:
        response = client.get(f"/nfl-pilot-monitor/audit/{UUID(int=3)}?scenario_id={UUID(int=2)}")

    assert response.status_code == 404
    assert captured == {"scenario_id": UUID(int=2), "decision_id": UUID(int=3)}


def test_recommendation_audit_summary_and_export_are_bounded_reads(
    monkeypatch: MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def summary_stub(self: NflPilotLifecycleService, scenario_id: UUID) -> dict[str, int]:
        captured["summary_scenario_id"] = scenario_id
        return {"total": 4, "hold": 1, "reduce": 2, "close": 1, "attention_required": 3}

    async def export_stub(
        self: NflPilotLifecycleService,
        scenario_id: UUID,
        recommendation: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, object]]:
        captured.update(
            export_scenario_id=scenario_id,
            recommendation=recommendation,
            limit=limit,
            offset=offset,
        )
        return []

    async def export_metadata_stub(
        self: NflPilotLifecycleService,
        scenario_id: UUID,
        recommendation: str | None,
        limit: int,
        offset: int,
        row_count: int,
    ) -> dict[str, object]:
        assert row_count == 0
        return {
            "generated_at": datetime(2026, 9, 14, tzinfo=UTC),
            "scenario_id": scenario_id,
            "recommendation_filter": recommendation,
            "limit": limit,
            "offset": offset,
            "row_count": row_count,
            "scenario_policy_version": "nfl-paper-pilot-v1",
            "scenario_policy_fingerprint": "a" * 64,
            "retention_policy_version": "nfl-pilot-audit-append-only-no-auto-delete-v1",
        }

    monkeypatch.setattr(NflPilotLifecycleService, "recommendation_audit_summary", summary_stub)
    monkeypatch.setattr(NflPilotLifecycleService, "recommendation_audit", export_stub)
    monkeypatch.setattr(
        NflPilotLifecycleService, "recommendation_audit_export_metadata", export_metadata_stub
    )
    with TestClient(application()) as client:
        summary = client.get(f"/nfl-pilot-monitor/audit/summary?scenario_id={UUID(int=2)}")
        export = client.get(
            f"/nfl-pilot-monitor/audit/export?scenario_id={UUID(int=2)}&format=csv&recommendation=reduce&limit=100"
        )
        json_export = client.get(
            f"/nfl-pilot-monitor/audit/export?scenario_id={UUID(int=2)}&format=json&recommendation=reduce&limit=100"
        )

    assert summary.status_code == 200
    assert summary.json() == {
        "total": 4,
        "hold": 1,
        "reduce": 2,
        "close": 1,
        "attention_required": 3,
    }
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("text/csv")
    assert export.text.startswith("generated_at,scenario_id,recommendation_filter")
    assert json_export.status_code == 200
    assert len(json_export.json()["metadata"]["export_fingerprint"]) == 64
    assert captured == {
        "summary_scenario_id": UUID(int=2),
        "export_scenario_id": UUID(int=2),
        "recommendation": "reduce",
        "limit": 100,
        "offset": 0,
    }


def test_audit_export_fingerprint_is_stable_across_generation_times() -> None:
    metadata = {
        "generated_at": datetime(2026, 9, 14, tzinfo=UTC),
        "scenario_id": UUID(int=2),
        "recommendation_filter": "reduce",
        "limit": 100,
        "offset": 0,
        "row_count": 0,
        "scenario_policy_version": "nfl-paper-pilot-v1",
        "scenario_policy_fingerprint": "a" * 64,
        "retention_policy_version": "nfl-pilot-audit-append-only-no-auto-delete-v1",
    }
    later_metadata = {**metadata, "generated_at": datetime(2026, 9, 15, tzinfo=UTC)}

    assert _audit_export_fingerprint(metadata, []) == _audit_export_fingerprint(later_metadata, [])


def test_pilot_disposition_rejects_nonpaper_mode() -> None:
    app = application()
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="postgresql+asyncpg://test:test@localhost/test", _env_file=None
    ).model_copy(update={"trading_mode": "live"})
    with TestClient(app) as client:
        response = client.post(
            "/nfl-pilot-dispositions/run",
            params={"decision_id": str(UUID(int=7)), "idempotency_key": "pilot:dispose"},
        )
    assert response.status_code == 409
