from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.domain.markets import MarketStatusFilter
from app.providers.prediction_markets.base import PredictionMarketProvider
from app.services.markets.filtering import is_likely_nba_market
from app.services.markets.repository import MarketRepository


class IngestionResult(BaseModel):
    """Auditable summary of one provider ingestion run."""

    model_config = ConfigDict(frozen=True)

    provider: str
    fetched: int
    nba_markets: int
    persisted: int


class MarketIngestionService:
    """Coordinate provider retrieval, filtering, and persistence."""

    def __init__(
        self,
        *,
        provider: PredictionMarketProvider,
        repository: MarketRepository,
    ) -> None:
        self._provider = provider
        self._repository = repository

    async def ingest(
        self,
        *,
        nba_only: bool = True,
        status: MarketStatusFilter | None = MarketStatusFilter.OPEN,
    ) -> IngestionResult:
        """Fetch and persist current market data without placing any orders."""
        fetched_markets = await self._provider.list_markets(status=status)
        nba_markets = [market for market in fetched_markets if is_likely_nba_market(market)]
        selected_markets = nba_markets if nba_only else fetched_markets
        persisted = await self._repository.upsert_markets(selected_markets)
        return IngestionResult(
            provider=self._provider.name,
            fetched=len(fetched_markets),
            nba_markets=len(nba_markets),
            persisted=persisted,
        )
