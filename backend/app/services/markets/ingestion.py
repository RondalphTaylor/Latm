from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.domain.markets import MarketStatusFilter
from app.domain.sports import SportsLeague
from app.providers.prediction_markets.base import PredictionMarketProvider
from app.services.markets.filtering import (
    classify_sports_market,
    is_likely_nba_market,
    supported_series_ticker,
)
from app.services.markets.repository import MarketRepository


class IngestionResult(BaseModel):
    """Auditable summary of one provider ingestion run."""

    model_config = ConfigDict(frozen=True)

    provider: str
    fetched: int
    nba_markets: int
    mlb_markets: int
    selected_league: SportsLeague | None
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
        league: SportsLeague | None = None,
        status: MarketStatusFilter | None = MarketStatusFilter.OPEN,
    ) -> IngestionResult:
        """Fetch and persist current market data without placing any orders."""
        series_ticker = supported_series_ticker(league) if league is not None else None
        fetched_markets = await self._provider.list_markets(
            status=status,
            series_ticker=series_ticker,
        )
        nba_markets = [market for market in fetched_markets if is_likely_nba_market(market)]
        classified_markets = [
            (market, classify_sports_market(market)) for market in fetched_markets
        ]
        mlb_markets = [
            market
            for market, classification in classified_markets
            if classification is not None and classification.league is SportsLeague.MLB
        ]
        classified_nba_count = sum(
            classification is not None and classification.league is SportsLeague.NBA
            for _, classification in classified_markets
        )
        if league is not None:
            selected_markets = [
                market
                for market, classification in classified_markets
                if classification is not None and classification.league is league
            ]
        else:
            selected_markets = nba_markets if nba_only else fetched_markets
        persisted = await self._repository.upsert_markets(selected_markets)
        return IngestionResult(
            provider=self._provider.name,
            fetched=len(fetched_markets),
            nba_markets=(classified_nba_count if league is not None else len(nba_markets)),
            mlb_markets=len(mlb_markets),
            selected_league=league,
            persisted=persisted,
        )
