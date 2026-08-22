from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.mlb_statcast import get_mlb_statcast_repository, get_mlb_statcast_service
from app.core.config import Settings, get_settings
from app.main import create_app
from app.models.mlb import MlbStatcastFeatureSnapshotRecord
from app.providers.sports.base import SportsProviderUnavailableError
from app.services.mlb_statcast.repository import MlbStatcastSourceConflictError
from app.services.mlb_statcast.service import MlbStatcastIngestionResult

EVENT_ID = UUID("2d79504d-e791-5dc8-af53-ee31d1c1ece3")
LINEUP_ID = UUID("9e248fe9-9e77-4e25-8347-ff5a39b5798c")
SNAPSHOT_ID = UUID("1cbf49fb-bdf1-4d2e-86a5-20fe8b489e40")


def player_profile(
    player_id: str,
    *,
    role: str,
    full_name: str,
) -> dict[str, object]:
    return {
        "role": role,
        "provider_player_id": player_id,
        "full_name": full_name,
        "pitch_count": 0,
        "plate_appearance_count": 0,
        "batted_ball_event_count": 0,
        "source_game_count": 0,
        "first_game_date": None,
        "last_game_date": None,
        "release_speed_sample_size": 0,
        "average_release_speed_mph": None,
        "spin_rate_sample_size": 0,
        "average_release_spin_rate_rpm": None,
        "exit_velocity_sample_size": 0,
        "average_exit_velocity_mph": None,
        "hard_hit_count": 0,
        "hard_hit_rate": None,
        "launch_quality_sample_size": 0,
        "barrel_count": 0,
        "barrel_rate": None,
        "estimated_woba_contact_sample_size": 0,
        "average_estimated_woba_on_contact": None,
        "complete_woba_sample_size": 0,
        "incomplete_woba_sample_size": 0,
        "woba_numerator": "0.000000",
        "woba_denominator": "0.000000",
        "observed_woba": None,
    }


def statcast_record() -> MlbStatcastFeatureSnapshotRecord:
    return MlbStatcastFeatureSnapshotRecord(
        id=SNAPSHOT_ID,
        sports_event_id=EVENT_ID,
        lineup_snapshot_id=LINEUP_ID,
        provider_name="baseball_savant",
        provider_event_id="823509",
        target_event_date=date(2026, 8, 22),
        scheduled_start_time=datetime(2026, 8, 22, 17, 35, tzinfo=UTC),
        window_start_date=date(2026, 7, 23),
        window_end_date=date(2026, 8, 21),
        lookback_days=30,
        source_retrieved_at=datetime(2026, 8, 22, 16, tzinfo=UTC),
        observation_basis="operational_pregame",
        operational_pregame_eligible=True,
        policy_name="mlb_statcast_pregame_features",
        policy_version="v1",
        policy_fingerprint="a" * 64,
        home_starting_pitcher=player_profile("677960", role="pitcher", full_name="Ryan Weathers"),
        away_starting_pitcher=player_profile("656302", role="pitcher", full_name="Dylan Cease"),
        home_batters=[
            player_profile(str(1000 + order), role="batter", full_name=f"Home {order}")
            for order in range(1, 10)
        ],
        away_batters=[
            player_profile(str(2000 + order), role="batter", full_name=f"Away {order}")
            for order in range(1, 10)
        ],
        source_fingerprint="b" * 64,
        input_fingerprint="c" * 64,
        source_manifest={
            "source": "official_baseball_savant_statcast_search_csv",
            "pitcher_row_count": 0,
            "batter_row_count": 0,
        },
        source_rows=[],
    )


class FakeStatcastRepository:
    def __init__(self, record: MlbStatcastFeatureSnapshotRecord | None = None) -> None:
        self.record = record
        self.arguments: dict[str, object] | None = None

    async def list_snapshots(self, **kwargs: object) -> list[MlbStatcastFeatureSnapshotRecord]:
        self.arguments = kwargs
        return [self.record] if self.record is not None else []

    async def get_snapshot(self, snapshot_id: UUID) -> MlbStatcastFeatureSnapshotRecord | None:
        return self.record if self.record is not None and self.record.id == snapshot_id else None


class FakeStatcastService:
    def __init__(self, outcome: str = "success") -> None:
        self.outcome = outcome
        self.arguments: tuple[UUID, UUID] | None = None

    async def ingest(
        self,
        *,
        event_id: UUID,
        lineup_snapshot_id: UUID,
    ) -> MlbStatcastIngestionResult:
        self.arguments = (event_id, lineup_snapshot_id)
        if self.outcome == "missing":
            raise LookupError("MLB lineup snapshot not found")
        if self.outcome == "conflict":
            raise MlbStatcastSourceConflictError("official MLB scheduled start changed")
        if self.outcome == "incomplete":
            raise ValueError("Statcast ingestion requires a complete pregame lineup snapshot")
        if self.outcome == "offline":
            raise SportsProviderUnavailableError("offline")
        return MlbStatcastIngestionResult(created=True, snapshot=statcast_record())


def statcast_client(
    *,
    repository: FakeStatcastRepository,
    service: FakeStatcastService | None = None,
) -> tuple[FastAPI, TestClient]:
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: Settings(
        database_url="postgresql+asyncpg://test:test@localhost/test",
        _env_file=None,
    )
    application.dependency_overrides[get_mlb_statcast_repository] = lambda: repository
    if service is not None:
        application.dependency_overrides[get_mlb_statcast_service] = lambda: service
    return application, TestClient(application)


def test_explicit_ingestion_returns_bounded_quantitative_snapshot() -> None:
    service = FakeStatcastService()
    _, client = statcast_client(repository=FakeStatcastRepository(), service=service)

    with client:
        response = client.post(
            f"/events/{EVENT_ID}/mlb-statcast-snapshots/ingest?lineup_snapshot_id={LINEUP_ID}"
        )

    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    assert body["snapshot"]["source_row_count"] == 0
    assert body["snapshot"]["operational_pregame_eligible"] is True
    assert len(body["snapshot"]["home_batters"]) == 9
    assert "source_rows" not in body["snapshot"]
    assert service.arguments == (EVENT_ID, LINEUP_ID)


def test_ingestion_failures_are_safe_and_specific() -> None:
    expected = {"missing": 404, "conflict": 409, "incomplete": 409, "offline": 502}
    for outcome, status_code in expected.items():
        _, client = statcast_client(
            repository=FakeStatcastRepository(),
            service=FakeStatcastService(outcome),
        )
        with client:
            response = client.post(
                f"/events/{EVENT_ID}/mlb-statcast-snapshots/ingest?lineup_snapshot_id={LINEUP_ID}"
            )
        assert response.status_code == status_code


def test_list_filters_and_nested_history_are_forwarded() -> None:
    repository = FakeStatcastRepository(statcast_record())
    _, client = statcast_client(repository=repository)

    with client:
        response = client.get(
            f"/mlb-statcast-snapshots?event_id={EVENT_ID}&lineup_snapshot_id={LINEUP_ID}"
            "&operational_pregame_eligible=true&limit=12&offset=3"
        )
        nested = client.get(f"/events/{EVENT_ID}/mlb-statcast-snapshots?limit=4&offset=1")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert nested.status_code == 200
    assert repository.arguments == {
        "event_id": EVENT_ID,
        "lineup_snapshot_id": None,
        "operational_pregame_eligible": None,
        "limit": 4,
        "offset": 1,
    }


def test_detail_not_found_and_query_validation() -> None:
    _, client = statcast_client(repository=FakeStatcastRepository())

    with client:
        missing = client.get(f"/mlb-statcast-snapshots/{SNAPSHOT_ID}")
        invalid_limit = client.get("/mlb-statcast-snapshots?limit=101")
        missing_lineup = client.post(f"/events/{EVENT_ID}/mlb-statcast-snapshots/ingest")

    assert missing.status_code == 404
    assert invalid_limit.status_code == 422
    assert missing_lineup.status_code == 422


def test_openapi_has_one_lineup_input_and_no_trading_controls() -> None:
    _, client = statcast_client(repository=FakeStatcastRepository())

    with client:
        operation = client.get("/openapi.json").json()["paths"][
            "/events/{event_id}/mlb-statcast-snapshots/ingest"
        ]["post"]

    parameter_names = {parameter["name"] for parameter in operation["parameters"]}
    assert parameter_names == {"event_id", "lineup_snapshot_id"}
    assert "requestBody" not in operation
