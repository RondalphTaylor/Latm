from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.sports import (
    _build_balldontlie_provider,
    get_sports_data_provider,
    get_sports_ingestion_service,
    get_sports_repository,
)
from app.core.config import Settings
from app.main import create_app
from app.models.sports import SportsEventRecord, TeamRecord
from app.providers.sports.base import SportsProviderUnavailableError
from app.services.sports.ingestion import (
    EventIngestionResult,
    SportsIngestionService,
    TeamIngestionResult,
)
from app.services.sports.repository import SportsRepository

HOME_TEAM_ID = UUID("a7129d9c-0d4c-44d6-8a2d-dda4dc34cf82")
AWAY_TEAM_ID = UUID("92d9bccf-dd34-4f1f-8886-9d2e884940d1")
EVENT_ID = UUID("8701782a-4d22-4147-9d60-edbf2e243adc")


def team_record(
    *,
    team_id: UUID = HOME_TEAM_ID,
    provider_id: str = "2",
    abbreviation: str = "BOS",
    city: str = "Boston",
    name: str = "Celtics",
) -> TeamRecord:
    observed_at = datetime(2026, 8, 1, tzinfo=UTC)
    return TeamRecord(
        id=team_id,
        provider_name="balldontlie",
        provider_team_id=provider_id,
        league="nba",
        abbreviation=abbreviation,
        city=city,
        name=name,
        full_name=f"{city} {name}",
        conference="East",
        division="Atlantic",
        raw_data={},
        first_seen_at=observed_at,
        last_seen_at=observed_at,
    )


def event_record() -> SportsEventRecord:
    observed_at = datetime(2026, 8, 1, tzinfo=UTC)
    record = SportsEventRecord(
        id=EVENT_ID,
        provider_name="balldontlie",
        provider_event_id="15907925",
        league="nba",
        season=2025,
        event_date=date(2026, 8, 1),
        scheduled_start_time=datetime(2026, 8, 1, 23, tzinfo=UTC),
        status="final",
        status_detail="Final",
        period=4,
        clock="Final",
        postseason=False,
        postponed=False,
        tournament_stage=None,
        home_team_id=HOME_TEAM_ID,
        away_team_id=AWAY_TEAM_ID,
        home_score=115,
        away_score=105,
        venue=None,
        raw_data={},
        first_seen_at=observed_at,
        last_seen_at=observed_at,
    )
    record.home_team = team_record()
    record.away_team = team_record(
        team_id=AWAY_TEAM_ID,
        provider_id="20",
        abbreviation="NYK",
        city="New York",
        name="Knicks",
    )
    return record


class FakeSportsRepository(SportsRepository):
    """Deterministic sports query test double."""

    def __init__(
        self,
        *,
        team: TeamRecord | None = None,
        event: SportsEventRecord | None = None,
    ) -> None:
        self.team = team
        self.event = event
        self.event_arguments: dict[str, object] | None = None

    async def list_teams(
        self,
        *,
        provider_name: str | None,
        limit: int,
        offset: int,
    ) -> list[TeamRecord]:
        return [self.team] if self.team is not None else []

    async def get_team(self, team_id: UUID) -> TeamRecord | None:
        if self.team is not None and self.team.id == team_id:
            return self.team
        return None

    async def list_events(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
        event_status: str | None,
        team_id: UUID | None,
        provider_name: str | None,
        limit: int,
        offset: int,
    ) -> list[SportsEventRecord]:
        self.event_arguments = {
            "start_date": start_date,
            "end_date": end_date,
            "event_status": event_status,
            "team_id": team_id,
            "provider_name": provider_name,
            "limit": limit,
            "offset": offset,
        }
        return [self.event] if self.event is not None else []

    async def get_event(self, event_id: UUID) -> SportsEventRecord | None:
        if self.event is not None and self.event.id == event_id:
            return self.event
        return None


class FakeSportsIngestionService(SportsIngestionService):
    """Deterministic sports ingestion test double."""

    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail

    async def ingest_teams(self) -> TeamIngestionResult:
        if self.should_fail:
            raise SportsProviderUnavailableError("offline")
        return TeamIngestionResult(provider="balldontlie", fetched=30, persisted=30)

    async def ingest_events(
        self,
        *,
        start_date: date,
        end_date: date,
    ) -> EventIngestionResult:
        if self.should_fail:
            raise SportsProviderUnavailableError("offline")
        return EventIngestionResult(
            provider="balldontlie",
            start_date=start_date,
            end_date=end_date,
            fetched=2,
            teams_persisted=4,
            events_persisted=2,
            scheduled=1,
            in_progress=0,
            final=1,
            postponed=0,
            canceled=0,
            unknown=0,
        )


def sports_client(
    *,
    repository: FakeSportsRepository,
    service: FakeSportsIngestionService | None = None,
) -> tuple[FastAPI, TestClient]:
    application = create_app()
    application.dependency_overrides[get_sports_repository] = lambda: repository
    if service is not None:
        application.dependency_overrides[get_sports_ingestion_service] = lambda: service
    return application, TestClient(application)


def test_lists_teams_and_returns_event_with_away_team() -> None:
    repository = FakeSportsRepository(team=team_record(), event=event_record())
    _, test_client = sports_client(repository=repository)

    with test_client:
        teams_response = test_client.get("/teams?provider=balldontlie")
        events_response = test_client.get(
            f"/events?start_date=2026-08-01&end_date=2026-08-02&status=final"
            f"&team_id={HOME_TEAM_ID}&provider=balldontlie&limit=25&offset=2"
        )

    assert teams_response.status_code == 200
    assert teams_response.json()[0]["abbreviation"] == "BOS"
    assert events_response.status_code == 200
    assert events_response.json()[0]["away_team"]["abbreviation"] == "NYK"
    assert events_response.json()[0]["home_score"] == 115
    assert repository.event_arguments == {
        "start_date": date(2026, 8, 1),
        "end_date": date(2026, 8, 2),
        "event_status": "final",
        "team_id": HOME_TEAM_ID,
        "provider_name": "balldontlie",
        "limit": 25,
        "offset": 2,
    }


def test_unknown_team_and_event_return_404() -> None:
    repository = FakeSportsRepository()
    _, test_client = sports_client(repository=repository)

    with test_client:
        team_response = test_client.get(f"/teams/{HOME_TEAM_ID}")
        event_response = test_client.get(f"/events/{EVENT_ID}")

    assert team_response.status_code == 404
    assert event_response.status_code == 404


def test_ingestion_endpoints_return_audit_summaries() -> None:
    service = FakeSportsIngestionService()
    _, test_client = sports_client(
        repository=FakeSportsRepository(),
        service=service,
    )

    with test_client:
        teams_response = test_client.post("/teams/ingest")
        events_response = test_client.post(
            "/events/ingest?start_date=2026-08-01&end_date=2026-08-02"
        )

    assert teams_response.status_code == 200
    assert teams_response.json() == {
        "provider": "balldontlie",
        "fetched": 30,
        "persisted": 30,
    }
    assert events_response.status_code == 200
    assert events_response.json()["events_persisted"] == 2
    assert events_response.json()["final"] == 1


def test_provider_failure_returns_safe_502() -> None:
    service = FakeSportsIngestionService(should_fail=True)
    _, test_client = sports_client(
        repository=FakeSportsRepository(),
        service=service,
    )

    with test_client:
        response = test_client.post("/teams/ingest")

    assert response.status_code == 502
    assert response.json() == {"detail": "sports-data provider unavailable"}


def test_missing_api_key_only_blocks_ingestion(client: TestClient) -> None:
    health_response = client.get("/health")
    ingestion_response = client.post("/teams/ingest")

    assert health_response.status_code == 200
    assert ingestion_response.status_code == 503
    assert ingestion_response.json() == {
        "detail": "sports-data provider credentials are not configured"
    }


def test_provider_dependency_reuses_adapter_for_cross_request_pacing() -> None:
    _build_balldontlie_provider.cache_clear()
    settings = Settings(
        database_url=SecretStr("postgresql+asyncpg://test:test@localhost/test"),
        balldontlie_api_key=SecretStr("test-key"),
    )

    first = get_sports_data_provider(settings)
    second = get_sports_data_provider(settings)

    assert first is second
    _build_balldontlie_provider.cache_clear()


def test_event_date_validation_returns_422() -> None:
    _, test_client = sports_client(
        repository=FakeSportsRepository(),
        service=FakeSportsIngestionService(),
    )

    with test_client:
        response = test_client.get("/events?start_date=2026-08-02&end_date=2026-08-01")

    assert response.status_code == 422
    assert response.json() == {"detail": "start_date must not be after end_date"}
