from __future__ import annotations

import logging
from datetime import date
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, SportsDataProviderName, get_settings
from app.db.session import get_session
from app.domain.sports import SportsEventStatus, SportsLeague
from app.providers.sports.balldontlie import BallDontLieSportsDataProvider
from app.providers.sports.base import (
    SportsDataProvider,
    SportsDataProviderError,
    SportsProviderAuthenticationError,
)
from app.providers.sports.mlb import MlbStatsSportsDataProvider
from app.providers.sports.nfl import BallDontLieNflSportsDataProvider
from app.schemas.sports import (
    EventIngestionResponse,
    SportsEventResponse,
    TeamIngestionResponse,
    TeamResponse,
)
from app.services.sports.ingestion import SportsIngestionService
from app.services.sports.repository import SportsRepository

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sports"])


def get_sports_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SportsRepository:
    """Build a sports repository for the request-scoped database session."""
    return SportsRepository(session)


@lru_cache(maxsize=4)
def _build_balldontlie_provider(
    api_key: SecretStr,
    base_url: str,
    timeout_seconds: float,
    max_retries: int,
    max_pages: int,
    request_interval_seconds: float,
) -> BallDontLieSportsDataProvider:
    """Reuse an adapter so pacing also covers separate ingestion requests."""
    return BallDontLieSportsDataProvider(
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        max_pages=max_pages,
        request_interval_seconds=request_interval_seconds,
    )


@lru_cache(maxsize=4)
def _build_nfl_provider(
    api_key: SecretStr,
    base_url: str,
    timeout_seconds: float,
    max_retries: int,
    max_pages: int,
    request_interval_seconds: float,
) -> BallDontLieNflSportsDataProvider:
    """Reuse the read-only NFL adapter across requests for request pacing."""
    return BallDontLieNflSportsDataProvider(
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        max_pages=max_pages,
        request_interval_seconds=request_interval_seconds,
    )


@lru_cache(maxsize=4)
def _build_mlb_provider(
    base_url: str,
    timeout_seconds: float,
    max_retries: int,
    request_interval_seconds: float,
) -> MlbStatsSportsDataProvider:
    """Reuse the public MLB adapter so pacing spans ingestion requests."""
    return MlbStatsSportsDataProvider(
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        request_interval_seconds=request_interval_seconds,
    )


def get_sports_data_provider(
    settings: Annotated[Settings, Depends(get_settings)],
    provider: Annotated[SportsDataProviderName | None, Query()] = None,
) -> SportsDataProvider:
    """Build a selected read-only sports adapter without trading capability."""
    provider_name = provider or settings.sports_data_provider
    if provider_name in {
        SportsDataProviderName.BALLDONTLIE,
        SportsDataProviderName.BALLDONTLIE_NFL,
    }:
        if (
            settings.balldontlie_api_key is None
            or not settings.balldontlie_api_key.get_secret_value().strip()
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="sports-data provider credentials are not configured",
            )
        if provider_name is SportsDataProviderName.BALLDONTLIE_NFL:
            return _build_nfl_provider(
                settings.balldontlie_api_key,
                settings.balldontlie_nfl_api_base_url,
                settings.provider_request_timeout_seconds,
                settings.provider_max_retries,
                settings.sports_provider_max_pages,
                settings.sports_provider_request_interval_seconds,
            )
        return _build_balldontlie_provider(
            settings.balldontlie_api_key,
            settings.balldontlie_api_base_url,
            settings.provider_request_timeout_seconds,
            settings.provider_max_retries,
            settings.sports_provider_max_pages,
            settings.sports_provider_request_interval_seconds,
        )
    if provider_name is SportsDataProviderName.MLB:
        return _build_mlb_provider(
            settings.mlb_api_base_url,
            settings.provider_request_timeout_seconds,
            settings.provider_max_retries,
            settings.mlb_provider_request_interval_seconds,
        )
    raise RuntimeError("unsupported sports-data provider configuration")


def get_sports_ingestion_service(
    provider: Annotated[SportsDataProvider, Depends(get_sports_data_provider)],
    repository: Annotated[SportsRepository, Depends(get_sports_repository)],
) -> SportsIngestionService:
    """Build the provider-neutral sports-ingestion coordinator."""
    return SportsIngestionService(provider=provider, repository=repository)


def _provider_failure(exc: SportsDataProviderError) -> HTTPException:
    if isinstance(exc, SportsProviderAuthenticationError):
        detail = "sports-data provider authentication failed"
    else:
        detail = "sports-data provider unavailable"
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)


@router.post("/teams/ingest", response_model=TeamIngestionResponse)
async def ingest_teams(
    service: Annotated[SportsIngestionService, Depends(get_sports_ingestion_service)],
) -> TeamIngestionResponse:
    """Fetch selected-provider team data and persist normalized records."""
    try:
        result = await service.ingest_teams()
    except SportsDataProviderError as exc:
        logger.warning("Sports team ingestion failed safely: %s", exc)
        raise _provider_failure(exc) from exc
    return TeamIngestionResponse.model_validate(result.model_dump())


@router.get("/teams", response_model=list[TeamResponse])
async def list_teams(
    repository: Annotated[SportsRepository, Depends(get_sports_repository)],
    league: Annotated[SportsLeague | None, Query()] = None,
    provider: Annotated[str | None, Query(min_length=1, max_length=50)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamResponse]:
    """List persisted normalized sports teams."""
    records = await repository.list_teams(
        league=league.value if league is not None else None,
        provider_name=provider,
        limit=limit,
        offset=offset,
    )
    return [TeamResponse.from_record(record) for record in records]


@router.get("/teams/{team_id}", response_model=TeamResponse)
async def get_team(
    team_id: UUID,
    repository: Annotated[SportsRepository, Depends(get_sports_repository)],
) -> TeamResponse:
    """Return one persisted NBA team by stable internal ID."""
    record = await repository.get_team(team_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="team not found")
    return TeamResponse.from_record(record)


@router.post("/events/ingest", response_model=EventIngestionResponse)
async def ingest_events(
    service: Annotated[SportsIngestionService, Depends(get_sports_ingestion_service)],
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
) -> EventIngestionResponse:
    """Fetch and persist selected-provider games in a bounded date range."""
    try:
        result = await service.ingest_events(start_date=start_date, end_date=end_date)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except SportsDataProviderError as exc:
        logger.warning("Sports event ingestion failed safely: %s", exc)
        raise _provider_failure(exc) from exc
    return EventIngestionResponse.model_validate(result.model_dump())


@router.get("/events", response_model=list[SportsEventResponse])
async def list_events(
    repository: Annotated[SportsRepository, Depends(get_sports_repository)],
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    league: Annotated[SportsLeague | None, Query()] = None,
    event_status: Annotated[SportsEventStatus | None, Query(alias="status")] = None,
    team_id: Annotated[UUID | None, Query()] = None,
    provider: Annotated[str | None, Query(min_length=1, max_length=50)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SportsEventResponse]:
    """List persisted sports events using provider-neutral filters."""
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="start_date must not be after end_date",
        )
    records = await repository.list_events(
        start_date=start_date,
        end_date=end_date,
        league=league.value if league is not None else None,
        event_status=event_status.value if event_status is not None else None,
        team_id=team_id,
        provider_name=provider,
        limit=limit,
        offset=offset,
    )
    return [SportsEventResponse.from_record(record) for record in records]


@router.get("/events/{event_id}", response_model=SportsEventResponse)
async def get_event(
    event_id: UUID,
    repository: Annotated[SportsRepository, Depends(get_sports_repository)],
) -> SportsEventResponse:
    """Return one persisted sports event by stable internal ID."""
    record = await repository.get_event(event_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="event not found")
    return SportsEventResponse.from_record(record)
