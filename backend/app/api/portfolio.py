from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.domain.opportunities import OpportunityDirection
from app.domain.portfolio import PositionSizingPolicy
from app.schemas.portfolio import (
    PortfolioCreateRequest,
    PortfolioCreateResponse,
    PortfolioResponse,
    PortfolioSnapshotResponse,
    PositionSizeProposalResponse,
    PositionSizingRunResponse,
)
from app.services.position_sizing.repository import (
    PortfolioConflictError,
    PositionSizingRepository,
)
from app.services.position_sizing.service import PaperPortfolioService, PositionSizingService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["paper portfolios", "position sizing"])


def get_position_sizing_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PositionSizingRepository:
    """Build a request-scoped paper portfolio repository."""
    return PositionSizingRepository(session)


def get_portfolio_service(
    repository: Annotated[PositionSizingRepository, Depends(get_position_sizing_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PaperPortfolioService:
    """Build the paper-only portfolio creation service."""
    return PaperPortfolioService(
        repository=repository,
        default_starting_bankroll=settings.paper_starting_bankroll,
    )


def get_position_sizing_service(
    repository: Annotated[PositionSizingRepository, Depends(get_position_sizing_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PositionSizingService:
    """Build the versioned advisory rules-v1 sizing service."""
    return PositionSizingService(
        repository=repository,
        policy=PositionSizingPolicy(
            candidate_min_raw_edge=settings.position_sizing_candidate_min_raw_edge,
            strong_min_raw_edge=settings.position_sizing_strong_min_raw_edge,
            very_strong_min_raw_edge=(settings.position_sizing_very_strong_min_raw_edge),
            candidate_exposure_fraction=(settings.position_sizing_candidate_exposure_fraction),
            strong_exposure_fraction=settings.position_sizing_strong_exposure_fraction,
            very_strong_exposure_fraction=(settings.position_sizing_very_strong_exposure_fraction),
            max_exposure_fraction=settings.position_sizing_max_exposure_fraction,
        ),
    )


@router.post("/portfolios", response_model=PortfolioCreateResponse)
async def create_portfolio(
    request: PortfolioCreateRequest,
    service: Annotated[PaperPortfolioService, Depends(get_portfolio_service)],
) -> PortfolioCreateResponse:
    """Create or idempotently return an immutable paper portfolio."""
    try:
        bundle, result = await service.create(
            idempotency_key=request.idempotency_key,
            name=request.name,
            starting_bankroll=request.starting_bankroll,
        )
    except PortfolioConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    response = PortfolioResponse.from_bundle(bundle)
    return PortfolioCreateResponse(**response.model_dump(), created=result.created)


@router.get("/portfolios", response_model=list[PortfolioResponse])
async def list_portfolios(
    repository: Annotated[PositionSizingRepository, Depends(get_position_sizing_repository)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PortfolioResponse]:
    """List paper portfolios with current balance snapshots."""
    bundles = await repository.list_portfolios(limit=limit, offset=offset)
    return [PortfolioResponse.from_bundle(bundle) for bundle in bundles]


@router.get("/portfolios/{portfolio_id}", response_model=PortfolioResponse)
async def get_portfolio(
    portfolio_id: UUID,
    repository: Annotated[PositionSizingRepository, Depends(get_position_sizing_repository)],
) -> PortfolioResponse:
    """Return one paper portfolio and its current balances."""
    bundle = await repository.get_portfolio(portfolio_id)
    if bundle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="portfolio not found")
    return PortfolioResponse.from_bundle(bundle)


@router.get(
    "/portfolios/{portfolio_id}/snapshots",
    response_model=list[PortfolioSnapshotResponse],
)
async def list_portfolio_snapshots(
    portfolio_id: UUID,
    repository: Annotated[PositionSizingRepository, Depends(get_position_sizing_repository)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PortfolioSnapshotResponse]:
    """Return immutable paper balance history."""
    if await repository.get_portfolio(portfolio_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="portfolio not found")
    records = await repository.list_portfolio_snapshots(
        portfolio_id=portfolio_id,
        limit=limit,
        offset=offset,
    )
    return [PortfolioSnapshotResponse.from_record(record) for record in records]


@router.post("/position-sizing/run", response_model=PositionSizingRunResponse)
async def run_position_sizing(
    service: Annotated[PositionSizingService, Depends(get_position_sizing_service)],
    portfolio_id: Annotated[UUID, Query()],
    opportunity_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 250,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PositionSizingRunResponse:
    """Create advisory allocations from current Phase 5 candidates only."""
    try:
        result = await service.run(
            portfolio_id=portfolio_id,
            opportunity_id=opportunity_id,
            limit=limit,
            offset=offset,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    logger.info(
        "position sizing completed: portfolio=%s strategy=%s version=%s "
        "examined=%d generated=%d persisted=%d",
        result.portfolio_id,
        result.strategy_name,
        result.strategy_version,
        result.examined,
        result.generated,
        result.persisted,
    )
    return PositionSizingRunResponse.model_validate(result.model_dump())


@router.get("/position-size-proposals", response_model=list[PositionSizeProposalResponse])
async def list_position_size_proposals(
    repository: Annotated[PositionSizingRepository, Depends(get_position_sizing_repository)],
    portfolio_id: Annotated[UUID | None, Query()] = None,
    opportunity_id: Annotated[UUID | None, Query()] = None,
    market_id: Annotated[UUID | None, Query()] = None,
    direction: Annotated[OpportunityDirection | None, Query()] = None,
    strategy_version: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PositionSizeProposalResponse]:
    """List immutable pre-risk position-size proposal history."""
    records = await repository.list_proposals(
        portfolio_id=portfolio_id,
        opportunity_id=opportunity_id,
        market_id=market_id,
        direction=direction.value if direction is not None else None,
        strategy_version=strategy_version,
        limit=limit,
        offset=offset,
    )
    return [PositionSizeProposalResponse.from_record(record) for record in records]


@router.get(
    "/position-size-proposals/{proposal_id}",
    response_model=PositionSizeProposalResponse,
)
async def get_position_size_proposal(
    proposal_id: UUID,
    repository: Annotated[PositionSizingRepository, Depends(get_position_sizing_repository)],
) -> PositionSizeProposalResponse:
    """Return one historical pre-risk allocation."""
    record = await repository.get_proposal(proposal_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="position-size proposal not found",
        )
    return PositionSizeProposalResponse.from_record(record)
