from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, TradingMode, get_settings
from app.db.session import get_session
from app.services.nfl_pilot.entries import NflPilotEntryService
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


class NflPilotEntryResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)
    id: UUID
    scenario_id: UUID
    preflight_id: UUID
    entered_at: datetime
    status: str
    direction: str
    quantity: int
    total_cost: Decimal
    adjusted_edge: Decimal
    entry_cap: Decimal
    aggregate_cap: Decimal
    execution_mode: str
    live_trading_enabled: bool
    warnings: tuple[str, ...] = (
        "This is a simulated NFL paper entry, not a provider order or live position.",
        "NFL promotion to live trading remains blocked.",
    )


class NflPilotEntryRunResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    created: bool
    entry: NflPilotEntryResponse


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


@router.post("/nfl-pilot-entries/run", response_model=NflPilotEntryRunResponse)
async def run_nfl_pilot_entry(
    scenario_id: UUID,
    preflight_id: UUID,
    idempotency_key: Annotated[str, Query(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> NflPilotEntryRunResponse:
    """Create one independently auditable simulated NFL entry from a fresh preflight."""
    if settings.trading_mode is not TradingMode.PAPER:
        raise HTTPException(status_code=409, detail="NFL pilot entries require paper mode")
    try:
        record, created = await NflPilotEntryService(session).run(
            scenario_id, preflight_id, idempotency_key
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return NflPilotEntryRunResponse(
        created=created, entry=NflPilotEntryResponse.model_validate(record)
    )
