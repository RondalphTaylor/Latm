from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from app.domain.markets import (
    BinaryMarketResolution,
    MarketOutcome,
    MarketStatusFilter,
    OutcomeSide,
    PredictionMarket,
)
from app.services.markets.ingestion import MarketIngestionService
from app.services.markets.repository import MarketRepository


def market(*, ticker: str, title: str, series_ticker: str, category: str) -> PredictionMarket:
    return PredictionMarket(
        provider_name="kalshi",
        provider_market_id=ticker,
        provider_event_id=ticker,
        series_ticker=series_ticker,
        category=category,
        market_type="binary",
        title=title,
        status="active",
        outcomes=(
            MarketOutcome(provider_outcome_id="yes", side=OutcomeSide.YES, label="Yes"),
            MarketOutcome(provider_outcome_id="no", side=OutcomeSide.NO, label="No"),
        ),
        raw_data={},
        retrieved_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


class StaticProvider:
    """Provider test double that records the requested event status."""

    name = "kalshi"

    def __init__(self, markets: list[PredictionMarket]) -> None:
        self.markets = markets
        self.status: MarketStatusFilter | None = None

    async def list_markets(
        self, *, status: MarketStatusFilter | None = None
    ) -> list[PredictionMarket]:
        self.status = status
        return self.markets

    async def get_market(self, provider_market_id: str) -> PredictionMarket:
        return next(
            market for market in self.markets if market.provider_market_id == provider_market_id
        )


class CapturingRepository(MarketRepository):
    """Repository test double that captures selected normalized markets."""

    def __init__(self) -> None:
        self.markets: list[PredictionMarket] = []

    async def upsert_markets(self, markets: Sequence[PredictionMarket]) -> int:
        self.markets = list(markets)
        return len(self.markets)


def test_ingestion_filters_to_nba_before_persistence() -> None:
    provider = StaticProvider(
        [
            market(
                ticker="KXNBAGAME-1",
                title="Boston Celtics at New York Knicks",
                series_ticker="KXNBAGAME",
                category="Sports",
            ),
            market(
                ticker="KXWEATHER-1",
                title="Will the high exceed 90?",
                series_ticker="KXWEATHER",
                category="Climate",
            ),
        ]
    )
    repository = CapturingRepository()
    service = MarketIngestionService(provider=provider, repository=repository)

    result = asyncio.run(service.ingest())

    assert provider.status is MarketStatusFilter.OPEN
    assert result.fetched == 2
    assert result.nba_markets == 1
    assert result.persisted == 1
    assert repository.markets[0].provider_market_id == "KXNBAGAME-1"


def test_settled_ingestion_preserves_typed_authoritative_resolution() -> None:
    retrieved_at = datetime(2026, 8, 2, 2, tzinfo=UTC)
    normalized_market = market(
        ticker="KXNBAGAME-1",
        title="Boston Celtics at New York Knicks",
        series_ticker="KXNBAGAME",
        category="Sports",
    ).model_copy(
        update={
            "status": "finalized",
            "resolution": BinaryMarketResolution(
                result=OutcomeSide.YES,
                yes_payout=Decimal("1"),
                no_payout=Decimal("0"),
                settled_at=datetime(2026, 8, 2, 1, tzinfo=UTC),
                retrieved_at=retrieved_at,
                source_snapshot={"provider_result": "yes"},
            ),
            "retrieved_at": retrieved_at,
        }
    )
    provider = StaticProvider([normalized_market])
    repository = CapturingRepository()
    service = MarketIngestionService(provider=provider, repository=repository)

    result = asyncio.run(service.ingest(status=MarketStatusFilter.SETTLED))

    assert provider.status is MarketStatusFilter.SETTLED
    assert result.persisted == 1
    assert repository.markets[0].resolution == normalized_market.resolution
