from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.domain.mlb_modeling import MlbFeatureSelectionPolicy
from app.schemas.mlb_modeling import (
    MlbGameFeatureBuildResponse,
    MlbGameFeatureVectorResponse,
    MlbModelDesignResponse,
)
from app.services.mlb_modeling.engine import DeterministicMlbGameFeatureEngine
from app.services.mlb_modeling.repository import (
    MlbGameFeatureConflictError,
    MlbGameFeatureRepository,
)
from app.services.mlb_modeling.service import MlbGameFeatureService

router = APIRouter(tags=["mlb-modeling"])


def get_mlb_game_feature_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MlbGameFeatureRepository:
    return MlbGameFeatureRepository(session)


def get_mlb_game_feature_service(
    repository: Annotated[MlbGameFeatureRepository, Depends(get_mlb_game_feature_repository)],
) -> MlbGameFeatureService:
    return MlbGameFeatureService(
        repository=repository,
        engine=DeterministicMlbGameFeatureEngine(),
        policy=MlbFeatureSelectionPolicy(),
    )


@router.post("/mlb-game-features/run", response_model=MlbGameFeatureBuildResponse)
async def build_mlb_game_feature_vector(
    statcast_snapshot_id: Annotated[UUID, Query()],
    service: Annotated[MlbGameFeatureService, Depends(get_mlb_game_feature_service)],
) -> MlbGameFeatureBuildResponse:
    """Derive one research-only vector from an exact immutable Statcast snapshot."""
    try:
        result = await service.build(statcast_snapshot_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ValueError, MlbGameFeatureConflictError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return MlbGameFeatureBuildResponse(
        created=result.created,
        vector=MlbGameFeatureVectorResponse.from_record(result.vector),
    )


@router.get("/mlb-game-features", response_model=list[MlbGameFeatureVectorResponse])
async def list_mlb_game_feature_vectors(
    repository: Annotated[MlbGameFeatureRepository, Depends(get_mlb_game_feature_repository)],
    event_id: Annotated[UUID | None, Query()] = None,
    statcast_snapshot_id: Annotated[UUID | None, Query()] = None,
    operational_model_input_eligible: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MlbGameFeatureVectorResponse]:
    records = await repository.list_vectors(
        event_id=event_id,
        statcast_snapshot_id=statcast_snapshot_id,
        operational_model_input_eligible=operational_model_input_eligible,
        limit=limit,
        offset=offset,
    )
    return [MlbGameFeatureVectorResponse.from_record(record) for record in records]


@router.get(
    "/events/{event_id}/mlb-game-features",
    response_model=list[MlbGameFeatureVectorResponse],
)
async def list_event_mlb_game_feature_vectors(
    event_id: UUID,
    repository: Annotated[MlbGameFeatureRepository, Depends(get_mlb_game_feature_repository)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MlbGameFeatureVectorResponse]:
    records = await repository.list_vectors(
        event_id=event_id,
        statcast_snapshot_id=None,
        operational_model_input_eligible=None,
        limit=limit,
        offset=offset,
    )
    return [MlbGameFeatureVectorResponse.from_record(record) for record in records]


@router.get("/mlb-game-features/{vector_id}", response_model=MlbGameFeatureVectorResponse)
async def get_mlb_game_feature_vector(
    vector_id: UUID,
    repository: Annotated[MlbGameFeatureRepository, Depends(get_mlb_game_feature_repository)],
) -> MlbGameFeatureVectorResponse:
    record = await repository.get_vector(vector_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="vector not found")
    return MlbGameFeatureVectorResponse.from_record(record)


@router.get("/mlb-model-design", response_model=MlbModelDesignResponse)
async def get_mlb_model_design() -> MlbModelDesignResponse:
    """Expose the frozen candidate contract and explicit disabled capabilities."""
    return MlbModelDesignResponse.current()
