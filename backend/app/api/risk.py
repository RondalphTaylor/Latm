from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.domain.portfolio import PositionSizingPolicy
from app.domain.risk import RiskDecisionType, RiskPolicy
from app.schemas.risk import RiskDecisionResponse, RiskRunResponse
from app.services.position_sizing.engine import RulesPositionSizer
from app.services.risk.repository import RiskRepository
from app.services.risk.service import RiskService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["risk decisions"])


def get_risk_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RiskRepository:
    """Build a request-scoped risk repository."""
    return RiskRepository(session)


def _sizing_policy(settings: Settings) -> PositionSizingPolicy:
    return PositionSizingPolicy(
        candidate_min_raw_edge=settings.position_sizing_candidate_min_raw_edge,
        strong_min_raw_edge=settings.position_sizing_strong_min_raw_edge,
        very_strong_min_raw_edge=settings.position_sizing_very_strong_min_raw_edge,
        candidate_exposure_fraction=settings.position_sizing_candidate_exposure_fraction,
        strong_exposure_fraction=settings.position_sizing_strong_exposure_fraction,
        very_strong_exposure_fraction=settings.position_sizing_very_strong_exposure_fraction,
        max_exposure_fraction=settings.position_sizing_max_exposure_fraction,
    )


def get_risk_service(
    repository: Annotated[RiskRepository, Depends(get_risk_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RiskService:
    """Build the paper-only deterministic MVP risk service."""
    policy = RiskPolicy(
        auto_approve_exposure_max=settings.risk_auto_approve_exposure_max,
        high_confidence_auto_approve_max=(settings.risk_high_confidence_auto_approve_max),
        min_raw_edge=settings.risk_min_raw_edge,
        min_match_confidence=settings.risk_min_match_confidence,
        max_market_price_age_seconds=settings.risk_max_market_price_age_seconds,
        max_operational_forecast_age_seconds=(settings.risk_max_operational_forecast_age_seconds),
        authorization_ttl_seconds=settings.risk_authorization_ttl_seconds,
    )
    active_sizing_version = RulesPositionSizer(_sizing_policy(settings)).strategy_version
    return RiskService(
        repository=repository,
        policy=policy,
        runtime_trading_mode=settings.trading_mode.value,
        active_sizing_strategy_version=active_sizing_version,
    )


@router.post("/risk-decisions/run", response_model=RiskRunResponse)
async def run_risk_decisions(
    service: Annotated[RiskService, Depends(get_risk_service)],
    proposal_id: Annotated[UUID | None, Query()] = None,
    portfolio_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 250,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RiskRunResponse:
    """Revalidate and risk-evaluate a bounded local proposal set."""
    try:
        result = await service.run(
            proposal_id=proposal_id,
            portfolio_id=portfolio_id,
            limit=limit,
            offset=offset,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    logger.info(
        "risk evaluation completed: policy=%s version=%s examined=%d persisted=%d",
        result.risk_policy_name,
        result.risk_policy_version,
        result.examined,
        result.persisted,
    )
    return RiskRunResponse.model_validate(result.model_dump())


@router.get("/risk-decisions", response_model=list[RiskDecisionResponse])
async def list_risk_decisions(
    repository: Annotated[RiskRepository, Depends(get_risk_repository)],
    latest_only: bool = True,
    unexpired_only: bool = False,
    proposal_id: Annotated[UUID | None, Query()] = None,
    portfolio_id: Annotated[UUID | None, Query()] = None,
    market_id: Annotated[UUID | None, Query()] = None,
    decision: Annotated[RiskDecisionType | None, Query()] = None,
    risk_policy_version: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RiskDecisionResponse]:
    """List latest/unexpired risk views or explicit immutable history."""
    records = await repository.list_decisions(
        latest_only=latest_only,
        unexpired_only=unexpired_only,
        current_at=datetime.now(UTC),
        proposal_id=proposal_id,
        portfolio_id=portfolio_id,
        market_id=market_id,
        decision=decision,
        risk_policy_version=risk_policy_version,
        limit=limit,
        offset=offset,
    )
    return [RiskDecisionResponse.from_record(record) for record in records]


@router.get("/risk-decisions/{decision_id}", response_model=RiskDecisionResponse)
async def get_risk_decision(
    decision_id: UUID,
    repository: Annotated[RiskRepository, Depends(get_risk_repository)],
) -> RiskDecisionResponse:
    """Return one historical risk decision without claiming current authority."""
    record = await repository.get_decision(decision_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="risk decision not found")
    return RiskDecisionResponse.from_record(record)


@router.get(
    "/position-size-proposals/{proposal_id}/risk-decisions",
    response_model=list[RiskDecisionResponse],
)
async def list_proposal_risk_decisions(
    proposal_id: UUID,
    repository: Annotated[RiskRepository, Depends(get_risk_repository)],
    latest_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RiskDecisionResponse]:
    """Return risk history for one position-size proposal."""
    records = await repository.list_decisions(
        latest_only=latest_only,
        unexpired_only=False,
        current_at=datetime.now(UTC),
        proposal_id=proposal_id,
        portfolio_id=None,
        market_id=None,
        decision=None,
        risk_policy_version=None,
        limit=limit,
        offset=offset,
    )
    if not records and proposal_id not in await repository.list_proposal_ids(
        proposal_id=proposal_id,
        portfolio_id=None,
        limit=1,
        offset=0,
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="position-size proposal not found",
        )
    return [RiskDecisionResponse.from_record(record) for record in records]
