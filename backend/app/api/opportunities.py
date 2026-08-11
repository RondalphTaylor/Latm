from __future__ import annotations

import logging
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.domain.opportunities import OpportunityDirection, OpportunityPolicy, OpportunityStatus
from app.schemas.opportunities import OpportunityResponse, OpportunityRunResponse
from app.services.opportunities.repository import OpportunityRepository
from app.services.opportunities.service import OpportunityDetectionService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["opportunities"])


def get_opportunity_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OpportunityRepository:
    """Build a request-scoped opportunity repository."""
    return OpportunityRepository(session)


def get_opportunity_service(
    repository: Annotated[OpportunityRepository, Depends(get_opportunity_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> OpportunityDetectionService:
    """Build the local-only research opportunity coordinator."""
    return OpportunityDetectionService(
        repository=repository,
        policy=OpportunityPolicy(
            watch_min_raw_edge=settings.opportunity_watch_min_raw_edge,
            trade_candidate_min_raw_edge=(settings.opportunity_trade_candidate_min_raw_edge),
            max_market_price_age_seconds=(settings.opportunity_max_market_price_age_seconds),
            max_operational_forecast_age_seconds=(
                settings.opportunity_max_operational_forecast_age_seconds
            ),
        ),
    )


@router.post("/opportunities/run", response_model=OpportunityRunResponse)
async def run_opportunities(
    service: Annotated[OpportunityDetectionService, Depends(get_opportunity_service)],
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    market_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 250,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OpportunityRunResponse:
    """Generate research-only comparisons from bounded local snapshots."""
    try:
        result = await service.run(
            start_date=start_date,
            end_date=end_date,
            market_id=market_id,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    logger.info(
        "opportunity run completed: strategy=%s version=%s examined=%d generated=%d persisted=%d",
        result.strategy_name,
        result.strategy_version,
        result.examined,
        result.generated,
        result.persisted,
    )
    return OpportunityRunResponse.model_validate(result.model_dump())


@router.get("/opportunities", response_model=list[OpportunityResponse])
async def list_opportunities(
    repository: Annotated[OpportunityRepository, Depends(get_opportunity_repository)],
    latest_only: Annotated[bool, Query()] = True,
    current_only: Annotated[bool, Query()] = True,
    opportunity_status: Annotated[OpportunityStatus | None, Query(alias="status")] = None,
    direction: Annotated[OpportunityDirection | None, Query()] = None,
    market_id: Annotated[UUID | None, Query()] = None,
    sports_event_id: Annotated[UUID | None, Query()] = None,
    model_name: Annotated[str | None, Query(min_length=1, max_length=50)] = None,
    model_version: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[OpportunityResponse]:
    """List current latest classifications by default, or inspect history."""
    records = await repository.list_opportunities(
        latest_only=latest_only,
        current_only=current_only,
        status=opportunity_status,
        direction=direction,
        market_id=market_id,
        sports_event_id=sports_event_id,
        model_name=model_name,
        model_version=model_version,
        limit=limit,
        offset=offset,
    )
    return [OpportunityResponse.from_record(record) for record in records]


@router.get("/opportunities/{opportunity_id}", response_model=OpportunityResponse)
async def get_opportunity(
    opportunity_id: UUID,
    repository: Annotated[OpportunityRepository, Depends(get_opportunity_repository)],
) -> OpportunityResponse:
    """Return one immutable directional classification."""
    record = await repository.get_opportunity(opportunity_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="opportunity not found")
    return OpportunityResponse.from_record(record)


@router.get("/markets/{market_id}/opportunities", response_model=list[OpportunityResponse])
async def list_market_opportunities(
    market_id: UUID,
    repository: Annotated[OpportunityRepository, Depends(get_opportunity_repository)],
    latest_only: Annotated[bool, Query()] = False,
    current_only: Annotated[bool, Query()] = False,
    opportunity_status: Annotated[OpportunityStatus | None, Query(alias="status")] = None,
    direction: Annotated[OpportunityDirection | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[OpportunityResponse]:
    """List directional opportunity history for one market."""
    records = await repository.list_opportunities(
        latest_only=latest_only,
        current_only=current_only,
        status=opportunity_status,
        direction=direction,
        market_id=market_id,
        sports_event_id=None,
        model_name=None,
        model_version=None,
        limit=limit,
        offset=offset,
    )
    return [OpportunityResponse.from_record(record) for record in records]
