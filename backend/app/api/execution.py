from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.domain.execution import PaperExecutionPolicy, PaperPositionStatus, PaperTradeStatus
from app.domain.portfolio import PositionSizingPolicy
from app.domain.risk import RiskPolicy
from app.schemas.execution import (
    PaperExecutionResponse,
    PaperPositionResponse,
    PaperTradeResponse,
)
from app.services.execution.repository import PaperExecutionRepository
from app.services.execution.service import PaperExecutionConflictError, PaperExecutionService
from app.services.position_sizing.engine import RulesPositionSizer

router = APIRouter(tags=["paper execution", "paper positions"])


def get_paper_execution_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PaperExecutionRepository:
    return PaperExecutionRepository(session)


def _risk_policy(settings: Settings) -> RiskPolicy:
    return RiskPolicy(
        auto_approve_exposure_max=settings.risk_auto_approve_exposure_max,
        high_confidence_auto_approve_max=settings.risk_high_confidence_auto_approve_max,
        min_raw_edge=settings.risk_min_raw_edge,
        min_match_confidence=settings.risk_min_match_confidence,
        max_market_price_age_seconds=settings.risk_max_market_price_age_seconds,
        max_operational_forecast_age_seconds=settings.risk_max_operational_forecast_age_seconds,
        authorization_ttl_seconds=settings.risk_authorization_ttl_seconds,
    )


def _active_sizing_version(settings: Settings) -> str:
    policy = PositionSizingPolicy(
        candidate_min_raw_edge=settings.position_sizing_candidate_min_raw_edge,
        strong_min_raw_edge=settings.position_sizing_strong_min_raw_edge,
        very_strong_min_raw_edge=settings.position_sizing_very_strong_min_raw_edge,
        candidate_exposure_fraction=settings.position_sizing_candidate_exposure_fraction,
        strong_exposure_fraction=settings.position_sizing_strong_exposure_fraction,
        very_strong_exposure_fraction=settings.position_sizing_very_strong_exposure_fraction,
        max_exposure_fraction=settings.position_sizing_max_exposure_fraction,
    )
    return RulesPositionSizer(policy).strategy_version


def get_paper_execution_service(
    repository: Annotated[PaperExecutionRepository, Depends(get_paper_execution_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PaperExecutionService:
    return PaperExecutionService(
        repository=repository,
        risk_policy=_risk_policy(settings),
        execution_policy=PaperExecutionPolicy(
            slippage_bps=settings.paper_slippage_bps,
            fee_bps=settings.paper_fee_bps,
        ),
        runtime_trading_mode=settings.trading_mode.value,
        active_sizing_strategy_version=_active_sizing_version(settings),
    )


@router.post("/paper-execution/run", response_model=PaperExecutionResponse)
async def run_paper_execution(
    risk_decision_id: Annotated[UUID, Query()],
    service: Annotated[PaperExecutionService, Depends(get_paper_execution_service)],
) -> PaperExecutionResponse:
    """Consume one explicit automatic authorization as a paper entry attempt."""
    try:
        result = await service.execute(risk_decision_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PaperExecutionConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return PaperExecutionResponse.from_result(result)


@router.get("/trades", response_model=list[PaperTradeResponse])
async def list_paper_trades(
    repository: Annotated[PaperExecutionRepository, Depends(get_paper_execution_repository)],
    portfolio_id: Annotated[UUID | None, Query()] = None,
    market_id: Annotated[UUID | None, Query()] = None,
    risk_decision_id: Annotated[UUID | None, Query()] = None,
    trade_status: Annotated[PaperTradeStatus | None, Query(alias="status")] = None,
    direction: Annotated[str | None, Query(pattern=r"^(yes|no)$")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PaperTradeResponse]:
    records = await repository.list_trades(
        portfolio_id=portfolio_id,
        market_id=market_id,
        risk_decision_id=risk_decision_id,
        status=trade_status.value if trade_status is not None else None,
        direction=direction,
        limit=limit,
        offset=offset,
    )
    return [PaperTradeResponse.from_record(record) for record in records]


@router.get("/trades/{trade_id}", response_model=PaperTradeResponse)
async def get_paper_trade(
    trade_id: UUID,
    repository: Annotated[PaperExecutionRepository, Depends(get_paper_execution_repository)],
) -> PaperTradeResponse:
    record = await repository.get_trade(trade_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="trade not found")
    return PaperTradeResponse.from_record(record)


@router.get("/positions", response_model=list[PaperPositionResponse])
async def list_paper_positions(
    repository: Annotated[PaperExecutionRepository, Depends(get_paper_execution_repository)],
    portfolio_id: Annotated[UUID | None, Query()] = None,
    market_id: Annotated[UUID | None, Query()] = None,
    position_status: Annotated[PaperPositionStatus | None, Query(alias="status")] = None,
    direction: Annotated[str | None, Query(pattern=r"^(yes|no)$")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PaperPositionResponse]:
    records = await repository.list_positions(
        portfolio_id=portfolio_id,
        market_id=market_id,
        status=position_status.value if position_status is not None else None,
        direction=direction,
        limit=limit,
        offset=offset,
    )
    return [PaperPositionResponse.from_record(record) for record in records]


@router.get("/positions/{position_id}", response_model=PaperPositionResponse)
async def get_paper_position(
    position_id: UUID,
    repository: Annotated[PaperExecutionRepository, Depends(get_paper_execution_repository)],
) -> PaperPositionResponse:
    record = await repository.get_position(position_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="position not found")
    return PaperPositionResponse.from_record(record)
