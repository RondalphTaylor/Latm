from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.markets import get_market_ingestion_service, get_market_repository
from app.domain.markets import MarketStatusFilter
from app.main import create_app
from app.models.markets import (
    MarketOutcomeRecord,
    MarketPriceRecord,
    PredictionMarketRecord,
)
from app.providers.prediction_markets.base import ProviderUnavailableError
from app.services.markets.ingestion import IngestionResult, MarketIngestionService
from app.services.markets.repository import MarketRepository, market_record_id

MARKET_ID = market_record_id("kalshi", "KXNBAGAME-26AUG01BOSNYK-BOS")


def market_record() -> PredictionMarketRecord:
    observed_at = datetime(2026, 8, 1, 12, tzinfo=UTC)
    record = PredictionMarketRecord(
        id=MARKET_ID,
        provider_name="kalshi",
        provider_market_id="KXNBAGAME-26AUG01BOSNYK-BOS",
        provider_event_id="KXNBAGAME-26AUG01BOSNYK",
        series_ticker="KXNBAGAME",
        category="Sports",
        market_type="binary",
        title="Boston Celtics at New York Knicks winner?",
        subtitle="Boston at New York",
        rules_primary="Resolves Yes if Boston wins.",
        rules_secondary=None,
        status="open",
        is_nba=True,
        open_time=observed_at,
        close_time=None,
        occurrence_time=None,
        provider_created_at=observed_at,
        provider_updated_at=observed_at,
        raw_data={},
        first_seen_at=observed_at,
        last_seen_at=observed_at,
    )
    record.outcomes = [
        MarketOutcomeRecord(
            id=UUID("2c5ed71f-9df6-4c73-9b0e-74123b729b01"),
            market_id=MARKET_ID,
            provider_outcome_id="yes",
            side="yes",
            label="Boston Celtics",
        ),
        MarketOutcomeRecord(
            id=UUID("e02595cf-a97d-4e21-92c0-418cbeb81737"),
            market_id=MARKET_ID,
            provider_outcome_id="no",
            side="no",
            label="New York Knicks",
        ),
    ]
    record.prices = [
        MarketPriceRecord(
            id=UUID("f9571f03-4314-4d8b-aa89-20afdf4f64ad"),
            market_id=MARKET_ID,
            yes_bid=Decimal("0.5400"),
            yes_ask=Decimal("0.5600"),
            no_bid=Decimal("0.4400"),
            no_ask=Decimal("0.4600"),
            last_price=Decimal("0.5500"),
            volume=Decimal("125.0000"),
            volume_24h=Decimal("40.0000"),
            open_interest=Decimal("80.0000"),
            liquidity=Decimal("0.0000"),
            retrieved_at=observed_at,
        )
    ]
    return record


class FakeMarketRepository(MarketRepository):
    """Deterministic market query test double."""

    def __init__(self, record: PredictionMarketRecord | None) -> None:
        self.record = record
        self.list_arguments: dict[str, object] | None = None

    async def list_markets(
        self,
        *,
        nba_only: bool,
        provider_name: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> list[PredictionMarketRecord]:
        self.list_arguments = {
            "nba_only": nba_only,
            "provider_name": provider_name,
            "status": status,
            "limit": limit,
            "offset": offset,
        }
        return [self.record] if self.record is not None else []

    async def get_market(self, market_id: UUID) -> PredictionMarketRecord | None:
        if self.record is not None and market_id == self.record.id:
            return self.record
        return None


class FakeIngestionService(MarketIngestionService):
    """Deterministic ingestion service test double."""

    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail

    async def ingest(
        self,
        *,
        nba_only: bool = True,
        status: MarketStatusFilter | None = MarketStatusFilter.OPEN,
    ) -> IngestionResult:
        if self.should_fail:
            raise ProviderUnavailableError("provider offline")
        return IngestionResult(provider="kalshi", fetched=8, nba_markets=2, persisted=2)


def market_client(
    *,
    repository: FakeMarketRepository,
    ingestion_service: FakeIngestionService | None = None,
) -> tuple[FastAPI, TestClient]:
    application = create_app()
    application.dependency_overrides[get_market_repository] = lambda: repository
    if ingestion_service is not None:
        application.dependency_overrides[get_market_ingestion_service] = lambda: ingestion_service
    return application, TestClient(application)


def test_list_markets_returns_typed_latest_snapshot_and_forwards_filters() -> None:
    repository = FakeMarketRepository(market_record())
    _, test_client = market_client(repository=repository)

    with test_client:
        response = test_client.get(
            "/markets?nba_only=true&provider=kalshi&status=open&limit=25&offset=5"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["id"] == str(MARKET_ID)
    assert payload[0]["latest_price"]["yes_bid"] == "0.5400"
    assert payload[0]["outcomes"][0]["side"] == "yes"
    assert repository.list_arguments == {
        "nba_only": True,
        "provider_name": "kalshi",
        "status": "open",
        "limit": 25,
        "offset": 5,
    }


def test_get_market_returns_404_for_unknown_id() -> None:
    repository = FakeMarketRepository(None)
    _, test_client = market_client(repository=repository)

    with test_client:
        response = test_client.get(f"/markets/{MARKET_ID}")

    assert response.status_code == 404
    assert response.json() == {"detail": "market not found"}


def test_ingestion_endpoint_reports_counts() -> None:
    repository = FakeMarketRepository(None)
    service = FakeIngestionService()
    _, test_client = market_client(repository=repository, ingestion_service=service)

    with test_client:
        response = test_client.post("/markets/ingest?nba_only=true&status=open")

    assert response.status_code == 200
    assert response.json() == {
        "provider": "kalshi",
        "fetched": 8,
        "nba_markets": 2,
        "persisted": 2,
    }


def test_ingestion_provider_failure_returns_safe_502() -> None:
    repository = FakeMarketRepository(None)
    service = FakeIngestionService(should_fail=True)
    _, test_client = market_client(repository=repository, ingestion_service=service)

    with test_client:
        response = test_client.post("/markets/ingest")

    assert response.status_code == 502
    assert response.json() == {"detail": "prediction-market provider unavailable"}
