from __future__ import annotations

import logging
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.domain.matching import MarketEventMatchStatus, MatchingPolicy
from app.schemas.matching import MarketEventMatchResponse, MatchingRunResponse
from app.services.matching.matcher import MATCHER_VERSION, MarketEventMatcher
from app.services.matching.repository import MatchingRepository
from app.services.matching.service import MarketEventMatchingService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["matching"])


def get_matching_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MatchingRepository:
    """Build a request-scoped matching repository."""
    return MatchingRepository(session)


def get_matching_policy(
    settings: Annotated[Settings, Depends(get_settings)],
) -> MatchingPolicy:
    """Build the recorded deterministic policy from validated settings."""
    return MatchingPolicy(
        matcher_version=MATCHER_VERSION,
        min_confidence=settings.matching_min_confidence,
        ambiguity_margin=settings.matching_ambiguity_margin,
        time_window_hours=settings.matching_time_window_hours,
    )


def get_matching_service(
    repository: Annotated[MatchingRepository, Depends(get_matching_repository)],
    policy: Annotated[MatchingPolicy, Depends(get_matching_policy)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MarketEventMatchingService:
    """Build the local-only deterministic matching coordinator."""
    return MarketEventMatchingService(
        repository=repository,
        matcher=MarketEventMatcher(policy),
        policy=policy,
        sports_provider_name=settings.sports_data_provider.value,
    )


@router.post("/matches/run", response_model=MatchingRunResponse)
async def run_matching(
    service: Annotated[MarketEventMatchingService, Depends(get_matching_service)],
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    market_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 250,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MatchingRunResponse:
    """Run a bounded deterministic match batch against local snapshots."""
    try:
        result = await service.run(
            start_date=start_date,
            end_date=end_date,
            market_id=market_id,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    logger.info(
        "market-to-event matching completed: version=%s examined=%d matched=%d "
        "ambiguous=%d unmatched=%d persisted=%d",
        result.matcher_version,
        result.examined,
        result.matched,
        result.ambiguous,
        result.unmatched,
        result.persisted,
    )
    return MatchingRunResponse.model_validate(result.model_dump())


@router.get("/matches", response_model=list[MarketEventMatchResponse])
async def list_matches(
    repository: Annotated[MatchingRepository, Depends(get_matching_repository)],
    latest_only: Annotated[bool, Query()] = True,
    match_status: Annotated[
        MarketEventMatchStatus | None,
        Query(alias="status"),
    ] = None,
    market_id: Annotated[UUID | None, Query()] = None,
    sports_event_id: Annotated[UUID | None, Query()] = None,
    eligible: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MarketEventMatchResponse]:
    """List latest or historical auditable matching attempts."""
    records = await repository.list_matches(
        latest_only=latest_only,
        match_status=match_status.value if match_status is not None else None,
        market_id=market_id,
        sports_event_id=sports_event_id,
        automatic_trading_eligible=eligible,
        limit=limit,
        offset=offset,
    )
    return [MarketEventMatchResponse.from_record(record) for record in records]


@router.get("/matches/{match_id}", response_model=MarketEventMatchResponse)
async def get_match(
    match_id: UUID,
    repository: Annotated[MatchingRepository, Depends(get_matching_repository)],
) -> MarketEventMatchResponse:
    """Return one historical matching attempt."""
    record = await repository.get_match(match_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="match not found")
    return MarketEventMatchResponse.from_record(record)


@router.get("/markets/{market_id}/match", response_model=MarketEventMatchResponse)
async def get_latest_market_match(
    market_id: UUID,
    repository: Annotated[MatchingRepository, Depends(get_matching_repository)],
) -> MarketEventMatchResponse:
    """Return the latest attempt for a market, including an unmatched result."""
    record = await repository.get_latest_market_match(market_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="market has not been evaluated",
        )
    return MarketEventMatchResponse.from_record(record)
