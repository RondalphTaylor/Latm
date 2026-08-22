from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.mlb_lineups import get_mlb_lineup_repository, get_mlb_lineup_service
from app.core.config import Settings, get_settings
from app.main import create_app
from app.models.mlb import MlbLineupSnapshotRecord
from app.providers.sports.base import SportsProviderUnavailableError
from app.services.mlb_lineups.repository import MlbLineupSourceConflictError
from app.services.mlb_lineups.service import MlbLineupIngestionResult

EVENT_ID = UUID("bcf3c981-9530-464d-9fe4-1a6910f70068")
SNAPSHOT_ID = UUID("a2b048c6-8bcc-4f4e-8947-eb9e3c6c1421")
HOME_TEAM_ID = UUID("9287b4a5-dc43-4d82-a694-81b2ab001ca2")
AWAY_TEAM_ID = UUID("b1613458-b459-4c77-91d4-eb1f06f45629")


def lineup_entries(prefix: int) -> list[dict[str, object]]:
    return [
        {
            "batting_order": order,
            "provider_player_id": str(prefix + order),
            "full_name": f"Player {prefix + order}",
            "position": "CF",
            "bat_side": "R",
        }
        for order in range(1, 10)
    ]


def lineup_record() -> MlbLineupSnapshotRecord:
    return MlbLineupSnapshotRecord(
        id=SNAPSHOT_ID,
        sports_event_id=EVENT_ID,
        provider_name="mlb",
        provider_event_id="823509",
        home_team_id=HOME_TEAM_ID,
        away_team_id=AWAY_TEAM_ID,
        scheduled_start_time=datetime(2026, 8, 22, 17, 35, tzinfo=UTC),
        source_updated_at=datetime(2026, 8, 22, 16, tzinfo=UTC),
        retrieved_at=datetime(2026, 8, 22, 16, 1, tzinfo=UTC),
        source_abstract_state="Preview",
        source_detailed_state="Scheduled",
        observation_phase="pregame",
        home_probable_pitcher={
            "provider_player_id": "677960",
            "full_name": "Ryan Weathers",
            "pitch_hand": "L",
        },
        away_probable_pitcher={
            "provider_player_id": "656302",
            "full_name": "Dylan Cease",
            "pitch_hand": "R",
        },
        home_lineup_state="posted",
        away_lineup_state="posted",
        home_lineup=lineup_entries(1000),
        away_lineup=lineup_entries(2000),
        complete_for_pregame_model=True,
        input_fingerprint="a" * 64,
        source_snapshot={"provider": "mlb", "gamePk": 823509},
    )


class FakeMlbLineupRepository:
    def __init__(self, record: MlbLineupSnapshotRecord | None = None) -> None:
        self.record = record
        self.arguments: dict[str, object] | None = None

    async def list_snapshots(self, **kwargs: object) -> list[MlbLineupSnapshotRecord]:
        self.arguments = kwargs
        return [self.record] if self.record is not None else []

    async def get_snapshot(self, snapshot_id: UUID) -> MlbLineupSnapshotRecord | None:
        return self.record if self.record is not None and self.record.id == snapshot_id else None


class FakeMlbLineupService:
    def __init__(self, outcome: str = "success") -> None:
        self.outcome = outcome
        self.event_id: UUID | None = None

    async def ingest(self, event_id: UUID) -> MlbLineupIngestionResult:
        self.event_id = event_id
        if self.outcome == "missing":
            raise LookupError("sports event not found")
        if self.outcome == "conflict":
            raise MlbLineupSourceConflictError("official feed team identity changed")
        if self.outcome == "wrong_league":
            raise ValueError("lineup snapshots are supported only for official MLB events")
        if self.outcome == "offline":
            raise SportsProviderUnavailableError("offline")
        return MlbLineupIngestionResult(created=True, snapshot=lineup_record())


def lineup_client(
    *,
    repository: FakeMlbLineupRepository,
    service: FakeMlbLineupService | None = None,
) -> tuple[FastAPI, TestClient]:
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: Settings(
        database_url="postgresql+asyncpg://test:test@localhost/test",
        _env_file=None,
    )
    application.dependency_overrides[get_mlb_lineup_repository] = lambda: repository
    if service is not None:
        application.dependency_overrides[get_mlb_lineup_service] = lambda: service
    return application, TestClient(application)


def test_explicit_ingestion_returns_typed_created_snapshot() -> None:
    service = FakeMlbLineupService()
    _, client = lineup_client(repository=FakeMlbLineupRepository(), service=service)

    with client:
        response = client.post(f"/events/{EVENT_ID}/mlb-lineup-snapshots/ingest")

    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    assert body["snapshot"]["id"] == str(SNAPSHOT_ID)
    assert body["snapshot"]["home_lineup_state"] == "posted"
    assert body["snapshot"]["complete_for_pregame_model"] is True
    assert len(body["snapshot"]["home_lineup"]) == 9
    assert service.event_id == EVENT_ID


def test_ingestion_failures_are_safe_and_specific() -> None:
    expected = {
        "missing": 404,
        "conflict": 409,
        "wrong_league": 409,
        "offline": 502,
    }
    for outcome, status_code in expected.items():
        _, client = lineup_client(
            repository=FakeMlbLineupRepository(),
            service=FakeMlbLineupService(outcome),
        )
        with client:
            response = client.post(f"/events/{EVENT_ID}/mlb-lineup-snapshots/ingest")
        assert response.status_code == status_code


def test_list_filters_and_nested_history_are_forwarded() -> None:
    repository = FakeMlbLineupRepository(lineup_record())
    _, client = lineup_client(repository=repository)

    with client:
        response = client.get(
            f"/mlb-lineup-snapshots?event_id={EVENT_ID}&observation_phase=pregame"
            "&complete_for_pregame_model=true&limit=12&offset=3"
        )
        nested = client.get(f"/events/{EVENT_ID}/mlb-lineup-snapshots?limit=4&offset=1")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert nested.status_code == 200
    assert repository.arguments == {
        "event_id": EVENT_ID,
        "observation_phase": None,
        "complete_for_pregame_model": None,
        "limit": 4,
        "offset": 1,
    }


def test_detail_not_found_and_query_validation() -> None:
    _, client = lineup_client(repository=FakeMlbLineupRepository())

    with client:
        missing = client.get(f"/mlb-lineup-snapshots/{SNAPSHOT_ID}")
        invalid_phase = client.get("/mlb-lineup-snapshots?observation_phase=future")
        invalid_limit = client.get("/mlb-lineup-snapshots?limit=501")

    assert missing.status_code == 404
    assert invalid_phase.status_code == 422
    assert invalid_limit.status_code == 422


def test_openapi_exposes_no_batch_or_trading_controls() -> None:
    _, client = lineup_client(repository=FakeMlbLineupRepository())

    with client:
        operation = client.get("/openapi.json").json()["paths"][
            "/events/{event_id}/mlb-lineup-snapshots/ingest"
        ]["post"]

    parameter_names = {parameter["name"] for parameter in operation["parameters"]}
    assert parameter_names == {"event_id"}
    assert "requestBody" not in operation
