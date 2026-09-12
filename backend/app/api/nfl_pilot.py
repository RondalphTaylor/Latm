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
from app.services.nfl_pilot.lifecycle import NflPilotLifecycleService
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


class NflPilotPositionEventResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)
    id: UUID
    position_id: UUID
    event_type: str
    mark_price: Decimal | None
    market_value: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    recorded_at: datetime
    execution_mode: str
    live_trading_enabled: bool
    warnings: tuple[str, ...] = (
        "This is an NFL paper-ledger event, not a provider order or live position.",
    )


class NflPilotPositionEventRunResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    created: bool
    event: NflPilotPositionEventResponse


class NflPilotLedgerResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    open_positions: int
    settled_positions: int
    committed_capital: Decimal
    realized_pnl: Decimal
    current_bankroll: Decimal
    available_bankroll: Decimal


class NflPilotMonitorResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    examined: int
    quote_checks_created: int
    fresh: int
    stale: int
    unusable: int
    missing: int
    marks_created: int
    skipped: int
    holds: int
    reduces: int
    closes: int
    attention_required: int


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


@router.post("/nfl-pilot-positions/mark", response_model=NflPilotPositionEventRunResponse)
async def mark_nfl_pilot_position(
    entry_id: UUID,
    idempotency_key: Annotated[str, Query(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> NflPilotPositionEventRunResponse:
    if settings.trading_mode is not TradingMode.PAPER:
        raise HTTPException(status_code=409, detail="NFL pilot position marks require paper mode")
    try:
        record, created = await NflPilotLifecycleService(session).mark(entry_id, idempotency_key)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return NflPilotPositionEventRunResponse(
        created=created, event=NflPilotPositionEventResponse.model_validate(record)
    )


@router.post("/nfl-pilot-positions/settle", response_model=NflPilotPositionEventRunResponse)
async def settle_nfl_pilot_position(
    entry_id: UUID,
    idempotency_key: Annotated[str, Query(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> NflPilotPositionEventRunResponse:
    if settings.trading_mode is not TradingMode.PAPER:
        raise HTTPException(status_code=409, detail="NFL pilot settlement requires paper mode")
    try:
        record, created = await NflPilotLifecycleService(session).settle(entry_id, idempotency_key)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return NflPilotPositionEventRunResponse(
        created=created, event=NflPilotPositionEventResponse.model_validate(record)
    )


@router.get("/nfl-pilot-scenarios/{scenario_id}/ledger", response_model=NflPilotLedgerResponse)
async def get_nfl_pilot_ledger(
    scenario_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NflPilotLedgerResponse:
    try:
        result = await NflPilotLifecycleService(session).summary(scenario_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return NflPilotLedgerResponse.model_validate(result)


@router.post("/nfl-pilot-monitor/run", response_model=NflPilotMonitorResponse)
async def run_nfl_pilot_monitor(
    scenario_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> NflPilotMonitorResponse:
    if settings.trading_mode is not TradingMode.PAPER:
        raise HTTPException(status_code=409, detail="NFL pilot monitoring requires paper mode")
    try:
        (
            examined,
            quote_checks_created,
            fresh,
            stale,
            unusable,
            missing,
            marks_created,
            skipped,
            holds,
            reduces,
            closes,
            attention_required,
        ) = await NflPilotLifecycleService(session).monitor(scenario_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return NflPilotMonitorResponse(
        examined=examined,
        quote_checks_created=quote_checks_created,
        fresh=fresh,
        stale=stale,
        unusable=unusable,
        missing=missing,
        marks_created=marks_created,
        skipped=skipped,
        holds=holds,
        reduces=reduces,
        closes=closes,
        attention_required=attention_required,
    )
