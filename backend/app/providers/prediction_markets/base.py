from __future__ import annotations

from typing import Protocol

from app.domain.markets import MarketStatusFilter, PredictionMarket


class PredictionMarketProviderError(RuntimeError):
    """Base error raised when a provider cannot return valid market data."""


class ProviderUnavailableError(PredictionMarketProviderError):
    """The provider could not be reached or remained temporarily unavailable."""


class ProviderResponseError(PredictionMarketProviderError):
    """The provider returned an unsuccessful or invalid response."""


class PredictionMarketProvider(Protocol):
    """Read-only provider boundary used by market-ingestion business logic."""

    name: str

    async def list_markets(
        self,
        *,
        status: MarketStatusFilter | None = None,
    ) -> list[PredictionMarket]: ...

    async def get_market(self, provider_market_id: str) -> PredictionMarket: ...
