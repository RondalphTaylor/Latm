from __future__ import annotations

import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.mlb_lineups import get_mlb_lineup_provider, get_mlb_lineup_service
from app.api.mlb_modeling import get_mlb_game_feature_service
from app.api.mlb_statcast import get_mlb_statcast_service
from app.api.sports import get_sports_repository
from app.db.session import get_session
from app.domain.mlb_modeling import approved_mlb_historical_backfill_policy
from app.providers.sports.base import SportsDataProviderError
from app.providers.sports.mlb import MlbStatsSportsDataProvider
from app.schemas.mlb_collection import (
    MlbBackfillBatchResponse,
    MlbBackfillCheckpointResponse,
    MlbBackfillRunResponse,
    MlbBackfillWorkflowRunResponse,
    MlbCollectionRunResponse,
)
from app.services.mlb_backfill_workflow import (
    MlbBackfillWorkflowRepository,
    MlbBackfillWorkflowRetryableError,
    MlbHistoricalBackfillWorkflowService,
    mlb_historical_backfill_policy_fingerprint,
)
from app.services.mlb_collection import (
    MlbProspectiveCollectionService,
    MlbRetrospectiveBackfillService,
)
from app.services.mlb_lineups.service import MlbLineupService
from app.services.mlb_modeling.service import MlbGameFeatureService
from app.services.mlb_statcast.service import MlbStatcastService
from app.services.sports.ingestion import SportsIngestionService
from app.services.sports.repository import SportsRepository

logger = logging.getLogger(__name__)
router = APIRouter(tags=["mlb-collection"])


def get_mlb_collection_service(
    provider: Annotated[MlbStatsSportsDataProvider, Depends(get_mlb_lineup_provider)],
    sports_repository: Annotated[SportsRepository, Depends(get_sports_repository)],
    lineup_service: Annotated[MlbLineupService, Depends(get_mlb_lineup_service)],
    statcast_service: Annotated[MlbStatcastService, Depends(get_mlb_statcast_service)],
    feature_service: Annotated[MlbGameFeatureService, Depends(get_mlb_game_feature_service)],
) -> MlbProspectiveCollectionService:
    return MlbProspectiveCollectionService(
        sports_ingestion=SportsIngestionService(
            provider=provider,
            repository=sports_repository,
        ),
        sports_repository=sports_repository,
        lineup_service=lineup_service,
        statcast_service=statcast_service,
        feature_service=feature_service,
    )


def get_mlb_backfill_service(
    provider: Annotated[MlbStatsSportsDataProvider, Depends(get_mlb_lineup_provider)],
    sports_repository: Annotated[SportsRepository, Depends(get_sports_repository)],
    lineup_service: Annotated[MlbLineupService, Depends(get_mlb_lineup_service)],
    statcast_service: Annotated[MlbStatcastService, Depends(get_mlb_statcast_service)],
    feature_service: Annotated[MlbGameFeatureService, Depends(get_mlb_game_feature_service)],
) -> MlbRetrospectiveBackfillService:
    return MlbRetrospectiveBackfillService(
        sports_ingestion=SportsIngestionService(
            provider=provider,
            repository=sports_repository,
        ),
        sports_repository=sports_repository,
        lineup_service=lineup_service,
        statcast_service=statcast_service,
        feature_service=feature_service,
    )


def get_mlb_backfill_workflow_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MlbBackfillWorkflowRepository:
    return MlbBackfillWorkflowRepository(session)


def get_mlb_backfill_workflow_service(
    repository: Annotated[
        MlbBackfillWorkflowRepository,
        Depends(get_mlb_backfill_workflow_repository),
    ],
    backfill_service: Annotated[
        MlbRetrospectiveBackfillService,
        Depends(get_mlb_backfill_service),
    ],
    feature_service: Annotated[MlbGameFeatureService, Depends(get_mlb_game_feature_service)],
) -> MlbHistoricalBackfillWorkflowService:
    return MlbHistoricalBackfillWorkflowService(
        repository=repository,
        backfill_service=backfill_service,
        feature_service=feature_service,
        policy=approved_mlb_historical_backfill_policy(),
    )


@router.post("/mlb-research-collection/run", response_model=MlbCollectionRunResponse)
async def run_mlb_research_collection(
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    service: Annotated[MlbProspectiveCollectionService, Depends(get_mlb_collection_service)],
    limit: Annotated[int, Query(ge=1, le=25)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MlbCollectionRunResponse:
    """Refresh a bounded window and advance eligible games through research features."""
    try:
        result = await service.run(
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except SportsDataProviderError as exc:
        logger.warning("MLB prospective collection refresh failed safely: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="official MLB schedule source unavailable",
        ) from exc
    return MlbCollectionRunResponse.from_result(result)


@router.post("/mlb-research-backfill/run", response_model=MlbBackfillRunResponse)
async def run_mlb_research_backfill(
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    service: Annotated[MlbRetrospectiveBackfillService, Depends(get_mlb_backfill_service)],
    limit: Annotated[int, Query(ge=1, le=10)] = 5,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MlbBackfillRunResponse:
    """Build labeled research examples from a bounded official completed-game window."""
    try:
        result = await service.run(
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except SportsDataProviderError as exc:
        logger.warning("MLB retrospective schedule refresh failed safely: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="official MLB schedule source unavailable",
        ) from exc
    return MlbBackfillRunResponse.from_result(result)


@router.post(
    "/mlb-research-backfill-workflow/run",
    response_model=MlbBackfillWorkflowRunResponse,
)
async def run_mlb_research_backfill_workflow(
    service: Annotated[
        MlbHistoricalBackfillWorkflowService,
        Depends(get_mlb_backfill_workflow_service),
    ],
) -> MlbBackfillWorkflowRunResponse:
    """Advance one approved regular-season batch and its durable cursor."""
    try:
        result = await service.run_once()
    except (SportsDataProviderError, MlbBackfillWorkflowRetryableError) as exc:
        logger.warning("MLB historical backfill workflow retained its cursor: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="official MLB research source unavailable; cursor retained",
        ) from exc
    return MlbBackfillWorkflowRunResponse.from_result(result)


@router.get(
    "/mlb-research-backfill-workflow",
    response_model=MlbBackfillCheckpointResponse,
)
async def get_mlb_research_backfill_workflow(
    repository: Annotated[
        MlbBackfillWorkflowRepository,
        Depends(get_mlb_backfill_workflow_repository),
    ],
) -> MlbBackfillCheckpointResponse:
    policy = approved_mlb_historical_backfill_policy()
    checkpoint = await repository.get_for_policy(
        mlb_historical_backfill_policy_fingerprint(policy)
    )
    if checkpoint is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="MLB historical backfill workflow has not started",
        )
    return MlbBackfillCheckpointResponse.from_record(checkpoint)


@router.get(
    "/mlb-research-backfill-workflow/batches",
    response_model=list[MlbBackfillBatchResponse],
)
async def list_mlb_research_backfill_batches(
    repository: Annotated[
        MlbBackfillWorkflowRepository,
        Depends(get_mlb_backfill_workflow_repository),
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MlbBackfillBatchResponse]:
    policy = approved_mlb_historical_backfill_policy()
    checkpoint = await repository.get_for_policy(
        mlb_historical_backfill_policy_fingerprint(policy)
    )
    if checkpoint is None:
        return []
    records = await repository.list_batches(
        checkpoint_id=checkpoint.id,
        limit=limit,
        offset=offset,
    )
    return [MlbBackfillBatchResponse.from_record(record) for record in records]
