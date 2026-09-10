from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, TradingMode, get_settings
from app.db.session import get_session
from app.schemas.nfl_forecasting import (
    NflPayoutForecastDetailResponse,
    NflPayoutForecastResponse,
    NflPayoutForecastRunResponse,
)
from app.services.nfl_forecasting.repository import NflPayoutForecastRepository

router = APIRouter(tags=["nfl-paper-forecast-candidates"])


def get_nfl_forecasting_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NflPayoutForecastRepository:
    return NflPayoutForecastRepository(session)


@router.post("/nfl-operational-forecasts/run", response_model=NflPayoutForecastRunResponse)
async def run_nfl_payout_forecast(
    match_id: UUID,
    idempotency_key: Annotated[str, Query(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")],
    repository: Annotated[NflPayoutForecastRepository, Depends(get_nfl_forecasting_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> NflPayoutForecastRunResponse:
    """Build an unpromoted paper candidate; never publish a trade authorization."""
    if settings.trading_mode is not TradingMode.PAPER:
        raise HTTPException(status_code=409, detail="NFL forecast candidates require paper mode")
    try:
        record, created = await repository.run(match_id, idempotency_key)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return NflPayoutForecastRunResponse(
        created=created, forecast=NflPayoutForecastResponse.model_validate(record)
    )


@router.get("/nfl-operational-forecasts", response_model=list[NflPayoutForecastResponse])
async def list_nfl_payout_forecasts(
    repository: Annotated[NflPayoutForecastRepository, Depends(get_nfl_forecasting_repository)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[NflPayoutForecastResponse]:
    """List historical candidates; expired records are retained for audit."""
    return [
        NflPayoutForecastResponse.model_validate(record)
        for record in await repository.list_forecasts(limit=limit, offset=offset)
    ]


@router.get(
    "/nfl-operational-forecasts/{forecast_id}", response_model=NflPayoutForecastDetailResponse
)
async def get_nfl_payout_forecast(
    forecast_id: UUID,
    repository: Annotated[NflPayoutForecastRepository, Depends(get_nfl_forecasting_repository)],
) -> NflPayoutForecastDetailResponse:
    record = await repository.get_forecast(forecast_id)
    if record is None:
        raise HTTPException(status_code=404, detail="NFL forecast candidate not found")
    return NflPayoutForecastDetailResponse.model_validate(record)
