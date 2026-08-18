from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.domain.position_monitoring import PositionMonitoringAction, PositionMonitoringPolicy
from app.schemas.execution import PaperPositionResponse
from app.schemas.portfolio import PortfolioSnapshotResponse
from app.schemas.position_monitoring import (
    PositionEventResponse,
    PositionMonitoringItemResponse,
    PositionMonitoringRunResponse,
)
from app.services.position_monitoring.repository import PositionMonitoringRepository
from app.services.position_monitoring.service import (
    PositionMonitoringConflictError,
    PositionMonitoringResult,
    PositionMonitoringService,
)

router = APIRouter(tags=["paper position monitoring"])


def get_position_monitoring_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PositionMonitoringRepository:
    return PositionMonitoringRepository(session)


def get_position_monitoring_service(
    repository: Annotated[
        PositionMonitoringRepository,
        Depends(get_position_monitoring_repository),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PositionMonitoringService:
    return PositionMonitoringService(
        repository=repository,
        policy=PositionMonitoringPolicy(
            min_hold_edge=settings.position_monitor_min_hold_edge,
            reduce_fraction=settings.position_monitor_reduce_fraction,
            exit_slippage_bps=settings.paper_exit_slippage_bps,
            exit_fee_bps=settings.paper_exit_fee_bps,
            max_market_price_age_seconds=(settings.position_monitor_max_market_price_age_seconds),
            max_forecast_age_seconds=(
                settings.position_monitor_max_operational_forecast_age_seconds
            ),
        ),
        runtime_trading_mode=settings.trading_mode.value,
    )


def _item_response(result: PositionMonitoringResult) -> PositionMonitoringItemResponse:
    return PositionMonitoringItemResponse(
        created=result.created,
        event=PositionEventResponse.from_record(result.event),
        position=PaperPositionResponse.from_record(result.position),
        portfolio_snapshot=(
            PortfolioSnapshotResponse.from_record(result.snapshot)
            if result.snapshot is not None
            else None
        ),
    )


@router.post("/position-monitoring/run", response_model=PositionMonitoringRunResponse)
async def run_position_monitoring(
    service: Annotated[PositionMonitoringService, Depends(get_position_monitoring_service)],
    position_id: Annotated[UUID | None, Query()] = None,
    portfolio_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PositionMonitoringRunResponse:
    """Evaluate one position or a bounded set for an external recurring scheduler."""
    try:
        result = await service.run(
            position_id=position_id,
            portfolio_id=portfolio_id,
            limit=limit,
            offset=offset,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PositionMonitoringConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return PositionMonitoringRunResponse(
        examined=result.examined,
        created=result.created,
        replayed=result.replayed,
        snapshots_appended=result.snapshots_appended,
        decision_counts=result.decision_counts,
        reason_counts=result.reason_counts,
        results=[_item_response(item) for item in result.results],
    )


@router.get("/position-events", response_model=list[PositionEventResponse])
async def list_position_events(
    repository: Annotated[
        PositionMonitoringRepository,
        Depends(get_position_monitoring_repository),
    ],
    position_id: Annotated[UUID | None, Query()] = None,
    portfolio_id: Annotated[UUID | None, Query()] = None,
    market_id: Annotated[UUID | None, Query()] = None,
    decision: Annotated[PositionMonitoringAction | None, Query()] = None,
    reason_code: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    policy_version: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PositionEventResponse]:
    records = await repository.list_events(
        position_id=position_id,
        portfolio_id=portfolio_id,
        market_id=market_id,
        decision=decision.value if decision is not None else None,
        reason_code=reason_code,
        policy_version=policy_version,
        limit=limit,
        offset=offset,
    )
    return [PositionEventResponse.from_record(record) for record in records]


@router.get("/position-events/{event_id}", response_model=PositionEventResponse)
async def get_position_event(
    event_id: UUID,
    repository: Annotated[
        PositionMonitoringRepository,
        Depends(get_position_monitoring_repository),
    ],
) -> PositionEventResponse:
    record = await repository.get_event(event_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="position event not found"
        )
    return PositionEventResponse.from_record(record)


@router.get("/positions/{position_id}/events", response_model=list[PositionEventResponse])
async def list_position_history(
    position_id: UUID,
    repository: Annotated[
        PositionMonitoringRepository,
        Depends(get_position_monitoring_repository),
    ],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PositionEventResponse]:
    if await repository.get_position(position_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="position not found")
    records = await repository.list_events(
        position_id=position_id,
        portfolio_id=None,
        market_id=None,
        decision=None,
        reason_code=None,
        policy_version=None,
        limit=limit,
        offset=offset,
    )
    return [PositionEventResponse.from_record(record) for record in records]
