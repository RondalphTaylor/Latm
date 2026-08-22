from __future__ import annotations

import logging
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.domain.mlb_statcast import MlbStatcastFeaturePolicy
from app.providers.sports.base import SportsDataProviderError
from app.providers.sports.savant import BaseballSavantStatcastProvider
from app.schemas.mlb_statcast import MlbStatcastIngestionResponse, MlbStatcastSnapshotResponse
from app.services.mlb_statcast.engine import DeterministicMlbStatcastFeatureEngine
from app.services.mlb_statcast.repository import (
    MlbStatcastRepository,
    MlbStatcastSourceConflictError,
)
from app.services.mlb_statcast.service import MlbStatcastService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["mlb-statcast"])


@lru_cache(maxsize=4)
def _build_baseball_savant_provider(
    base_url: str,
    timeout_seconds: float,
    max_retries: int,
    request_interval_seconds: float,
    max_response_bytes: int,
    max_rows: int,
) -> BaseballSavantStatcastProvider:
    """Reuse the official adapter so pacing spans separate API requests."""
    return BaseballSavantStatcastProvider(
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        request_interval_seconds=request_interval_seconds,
        max_response_bytes=max_response_bytes,
        max_rows=max_rows,
    )


def get_baseball_savant_provider(
    settings: Annotated[Settings, Depends(get_settings)],
) -> BaseballSavantStatcastProvider:
    """Build the credential-free, read-only official Statcast adapter."""
    return _build_baseball_savant_provider(
        settings.baseball_savant_base_url,
        settings.baseball_savant_request_timeout_seconds,
        settings.provider_max_retries,
        settings.baseball_savant_request_interval_seconds,
        settings.baseball_savant_max_response_bytes,
        settings.baseball_savant_max_rows,
    )


def get_mlb_statcast_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MlbStatcastRepository:
    """Build the request-scoped append-only quantitative repository."""
    return MlbStatcastRepository(session)


def get_mlb_statcast_service(
    settings: Annotated[Settings, Depends(get_settings)],
    provider: Annotated[BaseballSavantStatcastProvider, Depends(get_baseball_savant_provider)],
    repository: Annotated[MlbStatcastRepository, Depends(get_mlb_statcast_repository)],
) -> MlbStatcastService:
    """Build deterministic aggregation around one configured rolling window."""
    return MlbStatcastService(
        provider=provider,
        repository=repository,
        engine=DeterministicMlbStatcastFeatureEngine(),
        policy=MlbStatcastFeaturePolicy(lookback_days=settings.baseball_savant_lookback_days),
    )


@router.post(
    "/events/{event_id}/mlb-statcast-snapshots/ingest",
    response_model=MlbStatcastIngestionResponse,
)
async def ingest_mlb_statcast_snapshot(
    event_id: UUID,
    lineup_snapshot_id: Annotated[UUID, Query()],
    service: Annotated[MlbStatcastService, Depends(get_mlb_statcast_service)],
) -> MlbStatcastIngestionResponse:
    """Aggregate one exact posted lineup's bounded official pregame history."""
    try:
        result = await service.ingest(
            event_id=event_id,
            lineup_snapshot_id=lineup_snapshot_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ValueError, MlbStatcastSourceConflictError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except SportsDataProviderError as exc:
        logger.warning("MLB Statcast ingestion failed safely: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="official Baseball Savant source unavailable",
        ) from exc
    return MlbStatcastIngestionResponse(
        created=result.created,
        snapshot=MlbStatcastSnapshotResponse.from_record(result.snapshot),
    )


@router.get("/mlb-statcast-snapshots", response_model=list[MlbStatcastSnapshotResponse])
async def list_mlb_statcast_snapshots(
    repository: Annotated[MlbStatcastRepository, Depends(get_mlb_statcast_repository)],
    event_id: Annotated[UUID | None, Query()] = None,
    lineup_snapshot_id: Annotated[UUID | None, Query()] = None,
    operational_pregame_eligible: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MlbStatcastSnapshotResponse]:
    """List bounded quantitative snapshots newest first."""
    records = await repository.list_snapshots(
        event_id=event_id,
        lineup_snapshot_id=lineup_snapshot_id,
        operational_pregame_eligible=operational_pregame_eligible,
        limit=limit,
        offset=offset,
    )
    return [MlbStatcastSnapshotResponse.from_record(record) for record in records]


@router.get(
    "/events/{event_id}/mlb-statcast-snapshots",
    response_model=list[MlbStatcastSnapshotResponse],
)
async def list_event_mlb_statcast_snapshots(
    event_id: UUID,
    repository: Annotated[MlbStatcastRepository, Depends(get_mlb_statcast_repository)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MlbStatcastSnapshotResponse]:
    """List one event's immutable quantitative history."""
    records = await repository.list_snapshots(
        event_id=event_id,
        lineup_snapshot_id=None,
        operational_pregame_eligible=None,
        limit=limit,
        offset=offset,
    )
    return [MlbStatcastSnapshotResponse.from_record(record) for record in records]


@router.get(
    "/mlb-statcast-snapshots/{snapshot_id}",
    response_model=MlbStatcastSnapshotResponse,
)
async def get_mlb_statcast_snapshot(
    snapshot_id: UUID,
    repository: Annotated[MlbStatcastRepository, Depends(get_mlb_statcast_repository)],
) -> MlbStatcastSnapshotResponse:
    """Return one bounded quantitative snapshot by stable ID."""
    record = await repository.get_snapshot(snapshot_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="snapshot not found")
    return MlbStatcastSnapshotResponse.from_record(record)
