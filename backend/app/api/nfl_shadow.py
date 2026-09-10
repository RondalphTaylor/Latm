from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, TradingMode, get_settings
from app.db.session import get_session
from app.schemas.nfl_shadow import (
    NflShadowForecastDetailResponse,
    NflShadowForecastResponse,
    NflShadowForecastRunResponse,
)
from app.services.nfl_research.shadow_repository import NflShadowForecastRepository

router = APIRouter(tags=["nfl-shadow-research"])


def get_nfl_shadow_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NflShadowForecastRepository:
    return NflShadowForecastRepository(session)


@router.post("/nfl-shadow-forecasts/run", response_model=NflShadowForecastRunResponse)
async def run_nfl_shadow_forecast(
    match_id: UUID,
    repository: Annotated[NflShadowForecastRepository, Depends(get_nfl_shadow_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> NflShadowForecastRunResponse:
    """Freeze one pregame research estimate using local data; never execute an order."""
    if settings.trading_mode is not TradingMode.PAPER:
        raise HTTPException(status_code=409, detail="NFL shadow runs require paper mode")
    try:
        record, created = await repository.run(match_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return NflShadowForecastRunResponse(
        created=created, snapshot=NflShadowForecastResponse.model_validate(record)
    )


@router.get("/nfl-shadow-forecasts", response_model=list[NflShadowForecastResponse])
async def list_nfl_shadow_forecasts(
    repository: Annotated[NflShadowForecastRepository, Depends(get_nfl_shadow_repository)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[NflShadowForecastResponse]:
    records = await repository.list_snapshots(limit=limit, offset=offset)
    return [NflShadowForecastResponse.model_validate(record) for record in records]


@router.get("/nfl-shadow-forecasts/{snapshot_id}", response_model=NflShadowForecastDetailResponse)
async def get_nfl_shadow_forecast(
    snapshot_id: UUID,
    repository: Annotated[NflShadowForecastRepository, Depends(get_nfl_shadow_repository)],
) -> NflShadowForecastDetailResponse:
    record = await repository.get_snapshot(snapshot_id)
    if record is None:
        raise HTTPException(status_code=404, detail="NFL shadow snapshot not found")
    return NflShadowForecastDetailResponse.model_validate(record)
