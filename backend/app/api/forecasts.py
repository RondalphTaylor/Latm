from __future__ import annotations

import logging
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.domain.forecasts import ForecastPurpose
from app.schemas.forecasts import (
    BaseForecastResponse,
    ForecastRunResponse,
    ModelVersionResponse,
)
from app.services.forecasting.repository import ForecastRepository
from app.services.forecasting.service import BaseForecastService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["forecasts"])


def get_forecast_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ForecastRepository:
    """Build a request-scoped forecasting repository."""
    return ForecastRepository(session)


def get_forecast_service(
    repository: Annotated[ForecastRepository, Depends(get_forecast_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> BaseForecastService:
    """Build the local-only deterministic forecasting coordinator."""
    return BaseForecastService(
        repository=repository,
        sports_provider_name=settings.sports_data_provider.value,
    )


@router.post("/forecasts/run", response_model=ForecastRunResponse)
async def run_forecasts(
    service: Annotated[BaseForecastService, Depends(get_forecast_service)],
    purpose: Annotated[ForecastPurpose, Query()],
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    event_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 250,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ForecastRunResponse:
    """Run local Elo forecasting for eligible future or historical events."""
    try:
        result = await service.run(
            purpose=purpose,
            start_date=start_date,
            end_date=end_date,
            event_id=event_id,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    logger.info(
        "base forecast run completed: model=%s version=%s purpose=%s "
        "examined=%d generated=%d persisted=%d",
        result.model_name,
        result.model_version,
        result.purpose.value,
        result.examined,
        result.generated,
        result.persisted,
    )
    return ForecastRunResponse.model_validate(result.model_dump())


@router.get("/forecasts/model-versions", response_model=list[ModelVersionResponse])
async def list_model_versions(
    repository: Annotated[ForecastRepository, Depends(get_forecast_repository)],
) -> list[ModelVersionResponse]:
    """List immutable forecasting model configurations."""
    records = await repository.list_model_versions()
    return [ModelVersionResponse.from_record(record) for record in records]


@router.get("/forecasts", response_model=list[BaseForecastResponse])
async def list_forecasts(
    repository: Annotated[ForecastRepository, Depends(get_forecast_repository)],
    latest_only: Annotated[bool, Query()] = True,
    purpose: Annotated[ForecastPurpose | None, Query()] = None,
    sports_event_id: Annotated[UUID | None, Query()] = None,
    model_name: Annotated[str | None, Query(min_length=1, max_length=50)] = None,
    model_version: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[BaseForecastResponse]:
    """List latest or historical base forecast snapshots."""
    records = await repository.list_forecasts(
        latest_only=latest_only,
        purpose=purpose,
        sports_event_id=sports_event_id,
        model_name=model_name,
        model_version=model_version,
        limit=limit,
        offset=offset,
    )
    return [BaseForecastResponse.from_record(record) for record in records]


@router.get("/forecasts/{forecast_id}", response_model=BaseForecastResponse)
async def get_forecast(
    forecast_id: UUID,
    repository: Annotated[ForecastRepository, Depends(get_forecast_repository)],
) -> BaseForecastResponse:
    """Return one immutable forecast snapshot."""
    record = await repository.get_forecast(forecast_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="forecast not found")
    return BaseForecastResponse.from_record(record)


@router.get("/events/{event_id}/forecasts", response_model=list[BaseForecastResponse])
async def list_event_forecasts(
    event_id: UUID,
    repository: Annotated[ForecastRepository, Depends(get_forecast_repository)],
    latest_only: Annotated[bool, Query()] = False,
    purpose: Annotated[ForecastPurpose | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[BaseForecastResponse]:
    """List forecast history for one normalized sports event."""
    records = await repository.list_forecasts(
        latest_only=latest_only,
        purpose=purpose,
        sports_event_id=event_id,
        model_name=None,
        model_version=None,
        limit=limit,
        offset=offset,
    )
    return [BaseForecastResponse.from_record(record) for record in records]
