from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, TradingMode, get_settings
from app.db.session import get_session
from app.services.nfl_pilot.service import NflPilotScenarioService

router = APIRouter(tags=["nfl-paper-pilot"])


class NflPilotScenarioResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)
    id: UUID
    portfolio_id: UUID
    profile: str
    starting_bankroll: Decimal
    per_entry_exposure: Decimal
    aggregate_exposure: Decimal
    live_trading_enabled: bool


@router.post("/nfl-pilot-scenarios/register", response_model=NflPilotScenarioResponse)
async def register_nfl_pilot_scenario(
    portfolio_id: UUID,
    profile: Annotated[Literal["conservative", "baseline", "assertive"], Query()],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> NflPilotScenarioResponse:
    if settings.trading_mode is not TradingMode.PAPER:
        raise HTTPException(status_code=409, detail="NFL pilot scenarios require paper mode")
    try:
        record, _ = await NflPilotScenarioService(session).register(portfolio_id, profile)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return NflPilotScenarioResponse.model_validate(record)
