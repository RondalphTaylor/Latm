from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, TradingMode, get_settings
from app.db.session import get_session
from app.schemas.nfl_opportunities import (
    NflPaperOpportunityDetailResponse,
    NflPaperOpportunityResponse,
    NflPaperOpportunityRunResponse,
)
from app.services.nfl_opportunities.repository import NflPaperOpportunityRepository

router = APIRouter(tags=["nfl-paper-opportunities"])


def get_nfl_opportunity_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NflPaperOpportunityRepository:
    return NflPaperOpportunityRepository(session)


@router.post("/nfl-paper-opportunities/run", response_model=NflPaperOpportunityRunResponse)
async def run_nfl_paper_opportunity(
    forecast_id: UUID,
    idempotency_key: Annotated[str, Query(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")],
    repository: Annotated[NflPaperOpportunityRepository, Depends(get_nfl_opportunity_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> NflPaperOpportunityRunResponse:
    """Compare both direct asks locally, without granting risk or trading authority."""
    if settings.trading_mode is not TradingMode.PAPER:
        raise HTTPException(status_code=409, detail="NFL paper opportunities require paper mode")
    try:
        record, created = await repository.run(forecast_id, idempotency_key)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return NflPaperOpportunityRunResponse(
        created=created, opportunity=NflPaperOpportunityResponse.model_validate(record)
    )


@router.get("/nfl-paper-opportunities", response_model=list[NflPaperOpportunityResponse])
async def list_nfl_paper_opportunities(
    repository: Annotated[NflPaperOpportunityRepository, Depends(get_nfl_opportunity_repository)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[NflPaperOpportunityResponse]:
    """List comparison history; not a current executable signal feed."""
    records = await repository.list_opportunities(limit=limit, offset=offset)
    return [NflPaperOpportunityResponse.model_validate(record) for record in records]


@router.get(
    "/nfl-paper-opportunities/{opportunity_id}", response_model=NflPaperOpportunityDetailResponse
)
async def get_nfl_paper_opportunity(
    opportunity_id: UUID,
    repository: Annotated[NflPaperOpportunityRepository, Depends(get_nfl_opportunity_repository)],
) -> NflPaperOpportunityDetailResponse:
    record = await repository.get_opportunity(opportunity_id)
    if record is None:
        raise HTTPException(status_code=404, detail="NFL paper opportunity not found")
    return NflPaperOpportunityDetailResponse.model_validate(record)
