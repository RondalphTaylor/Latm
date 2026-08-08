from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import PredictionMarketProviderName, Settings, get_settings
from app.db.session import get_session
from app.domain.markets import MarketStatusFilter
from app.providers.prediction_markets.base import (
    PredictionMarketProvider,
    PredictionMarketProviderError,
)
from app.providers.prediction_markets.kalshi import KalshiPredictionMarketProvider
from app.schemas.markets import MarketIngestionResponse, MarketResponse
from app.services.markets.ingestion import MarketIngestionService
from app.services.markets.repository import MarketRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/markets", tags=["markets"])


def get_market_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MarketRepository:
    """Build a market repository for the request-scoped database session."""
    return MarketRepository(session)


def get_prediction_market_provider(
    settings: Annotated[Settings, Depends(get_settings)],
) -> PredictionMarketProvider:
    """Build the configured read-only prediction-market adapter."""
    if settings.prediction_market_provider is PredictionMarketProviderName.KALSHI:
        return KalshiPredictionMarketProvider(
            base_url=settings.kalshi_api_base_url,
            timeout_seconds=settings.provider_request_timeout_seconds,
            max_retries=settings.provider_max_retries,
            max_pages=settings.provider_max_pages,
        )
    raise RuntimeError("unsupported prediction-market provider configuration")


def get_market_ingestion_service(
    provider: Annotated[PredictionMarketProvider, Depends(get_prediction_market_provider)],
    repository: Annotated[MarketRepository, Depends(get_market_repository)],
) -> MarketIngestionService:
    """Build the read-only market-ingestion coordinator."""
    return MarketIngestionService(provider=provider, repository=repository)


@router.post("/ingest", response_model=MarketIngestionResponse)
async def ingest_markets(
    service: Annotated[MarketIngestionService, Depends(get_market_ingestion_service)],
    nba_only: Annotated[bool, Query()] = True,
    market_status: Annotated[MarketStatusFilter | None, Query(alias="status")] = (
        MarketStatusFilter.OPEN
    ),
) -> MarketIngestionResponse:
    """Fetch public market data and persist it locally without any trading action."""
    try:
        result = await service.ingest(nba_only=nba_only, status=market_status)
    except PredictionMarketProviderError as exc:
        logger.warning("Prediction-market ingestion failed safely: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="prediction-market provider unavailable",
        ) from exc
    return MarketIngestionResponse.model_validate(result.model_dump())


@router.get("", response_model=list[MarketResponse])
async def list_markets(
    repository: Annotated[MarketRepository, Depends(get_market_repository)],
    nba_only: Annotated[bool, Query()] = False,
    provider: Annotated[str | None, Query(min_length=1, max_length=50)] = None,
    market_status: Annotated[
        str | None,
        Query(alias="status", min_length=1, max_length=50),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MarketResponse]:
    """List persisted normalized markets with their latest price."""
    records = await repository.list_markets(
        nba_only=nba_only,
        provider_name=provider,
        status=market_status,
        limit=limit,
        offset=offset,
    )
    return [MarketResponse.from_record(record) for record in records]


@router.get("/{market_id}", response_model=MarketResponse)
async def get_market(
    market_id: UUID,
    repository: Annotated[MarketRepository, Depends(get_market_repository)],
) -> MarketResponse:
    """Return one persisted normalized market by its stable internal ID."""
    record = await repository.get_market(market_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="market not found")
    return MarketResponse.from_record(record)
