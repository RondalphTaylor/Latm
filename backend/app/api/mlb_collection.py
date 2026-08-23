from __future__ import annotations

import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.mlb_lineups import get_mlb_lineup_provider, get_mlb_lineup_service
from app.api.mlb_modeling import get_mlb_game_feature_service
from app.api.mlb_statcast import get_mlb_statcast_service
from app.api.sports import get_sports_repository
from app.providers.sports.base import SportsDataProviderError
from app.providers.sports.mlb import MlbStatsSportsDataProvider
from app.schemas.mlb_collection import MlbCollectionRunResponse
from app.services.mlb_collection import MlbProspectiveCollectionService
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
