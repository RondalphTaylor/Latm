from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.matching import get_matching_repository, get_matching_service
from app.core.config import Settings, get_settings
from app.main import create_app
from app.models.matching import MarketEventMatchRecord
from app.services.matching.service import MatchingRunResult

MATCH_ID = UUID("1df52c73-2a97-41d9-8b83-c38e60c8211e")
MARKET_ID = UUID("3da220e1-b6d0-45e9-b507-7e75dc95a353")
EVENT_ID = UUID("8701782a-4d22-4147-9d60-edbf2e243adc")
BOS_ID = UUID("a7129d9c-0d4c-44d6-8a2d-dda4dc34cf82")
NYK_ID = UUID("92d9bccf-dd34-4f1f-8886-9d2e884940d1")
TIP_TIME = datetime(2026, 8, 1, 23, tzinfo=UTC)


def match_record() -> MarketEventMatchRecord:
    return MarketEventMatchRecord(
        id=MATCH_ID,
        market_id=MARKET_ID,
        sports_event_id=EVENT_ID,
        status="matched",
        confidence=Decimal("1.0000"),
        method="exact_team_pair_and_time",
        reason="unique candidate met the configured confidence and margin thresholds",
        matcher_version="deterministic-team-time-v1",
        min_confidence=Decimal("0.9000"),
        ambiguity_margin=Decimal("0.1000"),
        time_window_hours=36,
        automatic_trading_eligible=True,
        input_fingerprint="a" * 64,
        team_signals=[
            {
                "team_id": str(BOS_ID),
                "alias": "boston celtics",
                "source": "full_name",
                "quality": "1.0000",
            },
            {
                "team_id": str(NYK_ID),
                "alias": "new york knicks",
                "source": "full_name",
                "quality": "1.0000",
            },
        ],
        candidate_scores=[
            {
                "event_id": str(EVENT_ID),
                "scheduled_start_time": TIP_TIME.isoformat(),
                "home_team_id": str(BOS_ID),
                "away_team_id": str(NYK_ID),
                "team_score": "1.0000",
                "temporal_score": "1.0000",
                "confidence": "1.0000",
                "time_delta_seconds": 0,
                "within_time_window": True,
                "method": "exact_team_pair_and_time",
            }
        ],
        evidence={"reference_time_source": "occurrence_time"},
        evaluated_at=TIP_TIME,
    )


class FakeMatchingRepository:
    def __init__(self, record: MarketEventMatchRecord | None = None) -> None:
        self.record = record
        self.list_arguments: dict[str, object] | None = None

    async def list_matches(self, **kwargs: object) -> list[MarketEventMatchRecord]:
        self.list_arguments = kwargs
        return [self.record] if self.record is not None else []

    async def get_match(self, match_id: UUID) -> MarketEventMatchRecord | None:
        return self.record if self.record is not None and self.record.id == match_id else None

    async def get_latest_market_match(self, market_id: UUID) -> MarketEventMatchRecord | None:
        return (
            self.record if self.record is not None and self.record.market_id == market_id else None
        )

    async def list_markets_for_matching(self, **_: object) -> list[object]:
        return []

    async def list_teams_for_matching(self, **_: object) -> list[object]:
        return []

    async def list_events_for_matching(self, **_: object) -> list[object]:
        return []

    async def insert_decisions(self, _: object) -> int:
        return 0


class FakeMatchingService:
    async def run(
        self,
        *,
        start_date: date,
        end_date: date,
        market_id: UUID | None,
        limit: int,
        offset: int,
    ) -> MatchingRunResult:
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        return MatchingRunResult(
            matcher_version="deterministic-team-time-v1",
            start_date=start_date,
            end_date=end_date,
            examined=3,
            persisted=3,
            matched=1,
            ambiguous=1,
            unmatched=1,
        )


def matching_client(
    *,
    repository: FakeMatchingRepository,
    service: FakeMatchingService | None = None,
) -> tuple[FastAPI, TestClient]:
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: Settings(
        database_url="postgresql+asyncpg://test:test@localhost/test",
        _env_file=None,
    )
    application.dependency_overrides[get_matching_repository] = lambda: repository
    if service is not None:
        application.dependency_overrides[get_matching_service] = lambda: service
    return application, TestClient(application)


def test_run_matching_returns_audit_summary() -> None:
    _, client = matching_client(
        repository=FakeMatchingRepository(),
        service=FakeMatchingService(),
    )

    with client:
        response = client.post(
            f"/matches/run?start_date=2026-08-01&end_date=2026-08-02"
            f"&market_id={MARKET_ID}&limit=25&offset=2"
        )

    assert response.status_code == 200
    assert response.json()["matched"] == 1
    assert response.json()["ambiguous"] == 1
    assert response.json()["unmatched"] == 1


def test_run_uses_local_snapshots_without_sports_api_key() -> None:
    _, client = matching_client(repository=FakeMatchingRepository())

    with client:
        response = client.post("/matches/run?start_date=2026-08-01&end_date=2026-08-01")

    assert response.status_code == 200
    assert response.json()["examined"] == 0
    assert response.json()["persisted"] == 0


def test_list_and_detail_expose_auditable_safety_state() -> None:
    repository = FakeMatchingRepository(match_record())
    _, client = matching_client(repository=repository)

    with client:
        list_response = client.get(
            f"/matches?latest_only=true&status=matched&market_id={MARKET_ID}"
            f"&sports_event_id={EVENT_ID}&eligible=true&limit=25&offset=2"
        )
        detail_response = client.get(f"/matches/{MATCH_ID}")
        latest_response = client.get(f"/markets/{MARKET_ID}/match")

    assert list_response.status_code == 200
    assert list_response.json()[0]["automatic_trading_eligible"] is True
    assert list_response.json()[0]["candidate_scores"][0]["event_id"] == str(EVENT_ID)
    assert detail_response.status_code == 200
    assert latest_response.status_code == 200
    assert repository.list_arguments == {
        "latest_only": True,
        "match_status": "matched",
        "market_id": MARKET_ID,
        "sports_event_id": EVENT_ID,
        "automatic_trading_eligible": True,
        "limit": 25,
        "offset": 2,
    }


def test_unknown_match_and_never_evaluated_market_return_404() -> None:
    _, client = matching_client(repository=FakeMatchingRepository())

    with client:
        match_response = client.get(f"/matches/{MATCH_ID}")
        market_response = client.get(f"/markets/{MARKET_ID}/match")

    assert match_response.status_code == 404
    assert market_response.status_code == 404
    assert market_response.json() == {"detail": "market has not been evaluated"}


def test_invalid_run_range_returns_422() -> None:
    _, client = matching_client(
        repository=FakeMatchingRepository(),
        service=FakeMatchingService(),
    )

    with client:
        response = client.post("/matches/run?start_date=2026-08-02&end_date=2026-08-01")

    assert response.status_code == 422
    assert response.json() == {"detail": "start_date must not be after end_date"}
