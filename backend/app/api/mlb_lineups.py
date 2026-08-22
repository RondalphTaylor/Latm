from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sports import _build_mlb_provider
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.domain.mlb_lineups import MlbObservationPhase
from app.providers.sports.base import SportsDataProviderError
from app.providers.sports.mlb import MlbStatsSportsDataProvider
from app.schemas.mlb_lineups import MlbLineupIngestionResponse, MlbLineupSnapshotResponse
from app.services.mlb_lineups.repository import (
    MlbLineupRepository,
    MlbLineupSourceConflictError,
)
from app.services.mlb_lineups.service import MlbLineupService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["mlb-lineups"])


def get_mlb_lineup_provider(
    settings: Annotated[Settings, Depends(get_settings)],
) -> MlbStatsSportsDataProvider:
    """Build the official read-only MLB adapter without a provider selector."""
    return _build_mlb_provider(
        settings.mlb_api_base_url,
        settings.provider_request_timeout_seconds,
        settings.provider_max_retries,
        settings.mlb_provider_request_interval_seconds,
    )


def get_mlb_lineup_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MlbLineupRepository:
    """Build the request-scoped append-only snapshot repository."""
    return MlbLineupRepository(session)


def get_mlb_lineup_service(
    provider: Annotated[MlbStatsSportsDataProvider, Depends(get_mlb_lineup_provider)],
    repository: Annotated[MlbLineupRepository, Depends(get_mlb_lineup_repository)],
) -> MlbLineupService:
    """Build the official one-event snapshot coordinator."""
    return MlbLineupService(provider=provider, repository=repository)


@router.post(
    "/events/{event_id}/mlb-lineup-snapshots/ingest",
    response_model=MlbLineupIngestionResponse,
)
async def ingest_mlb_lineup_snapshot(
    event_id: UUID,
    service: Annotated[MlbLineupService, Depends(get_mlb_lineup_service)],
) -> MlbLineupIngestionResponse:
    """Observe probable pitchers and posted batting orders for one official MLB event."""
    try:
        result = await service.ingest(event_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ValueError, MlbLineupSourceConflictError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except SportsDataProviderError as exc:
        logger.warning("MLB lineup ingestion failed safely: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="official MLB lineup source unavailable",
        ) from exc
    return MlbLineupIngestionResponse(
        created=result.created,
        snapshot=MlbLineupSnapshotResponse.from_record(result.snapshot),
    )


@router.get("/mlb-lineup-snapshots", response_model=list[MlbLineupSnapshotResponse])
async def list_mlb_lineup_snapshots(
    repository: Annotated[MlbLineupRepository, Depends(get_mlb_lineup_repository)],
    event_id: Annotated[UUID | None, Query()] = None,
    observation_phase: Annotated[MlbObservationPhase | None, Query()] = None,
    complete_for_pregame_model: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MlbLineupSnapshotResponse]:
    """List immutable official observations newest first."""
    records = await repository.list_snapshots(
        event_id=event_id,
        observation_phase=(observation_phase.value if observation_phase is not None else None),
        complete_for_pregame_model=complete_for_pregame_model,
        limit=limit,
        offset=offset,
    )
    return [MlbLineupSnapshotResponse.from_record(record) for record in records]


@router.get(
    "/events/{event_id}/mlb-lineup-snapshots",
    response_model=list[MlbLineupSnapshotResponse],
)
async def list_event_mlb_lineup_snapshots(
    event_id: UUID,
    repository: Annotated[MlbLineupRepository, Depends(get_mlb_lineup_repository)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MlbLineupSnapshotResponse]:
    """List one MLB event's immutable observation history."""
    records = await repository.list_snapshots(
        event_id=event_id,
        observation_phase=None,
        complete_for_pregame_model=None,
        limit=limit,
        offset=offset,
    )
    return [MlbLineupSnapshotResponse.from_record(record) for record in records]


@router.get(
    "/mlb-lineup-snapshots/{snapshot_id}",
    response_model=MlbLineupSnapshotResponse,
)
async def get_mlb_lineup_snapshot(
    snapshot_id: UUID,
    repository: Annotated[MlbLineupRepository, Depends(get_mlb_lineup_repository)],
) -> MlbLineupSnapshotResponse:
    """Return one immutable official observation."""
    record = await repository.get_snapshot(snapshot_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="snapshot not found")
    return MlbLineupSnapshotResponse.from_record(record)
