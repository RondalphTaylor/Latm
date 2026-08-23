from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.domain.mlb_modeling import (
    MlbChronologicalDatasetPolicy,
    MlbDatasetSplit,
    MlbFeatureSelectionPolicy,
)
from app.domain.mlb_statcast import MlbStatcastObservationBasis
from app.schemas.mlb_modeling import (
    MlbApprovedDatasetReadinessResponse,
    MlbCanonicalDatasetResponse,
    MlbDatasetInventoryResponse,
    MlbDatasetLabelResponse,
    MlbGameFeatureBuildResponse,
    MlbGameFeatureVectorResponse,
    MlbLabeledFeatureExampleResponse,
    MlbLogisticFittingDesignResponse,
    MlbModelDesignResponse,
    MlbResearchModelFitPreviewResponse,
)
from app.services.mlb_modeling.engine import DeterministicMlbGameFeatureEngine
from app.services.mlb_modeling.repository import (
    MlbGameFeatureConflictError,
    MlbGameFeatureRepository,
)
from app.services.mlb_modeling.service import (
    MlbGameFeatureService,
    MlbModelFittingBlockedError,
)

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


@router.get("/mlb-logistic-fitting-design", response_model=MlbLogisticFittingDesignResponse)
async def get_mlb_logistic_fitting_design() -> MlbLogisticFittingDesignResponse:
    """Expose the frozen research fitter without fitting or publishing a model."""
    return MlbLogisticFittingDesignResponse.current()


@router.post(
    "/mlb-research-model-fit/preview",
    response_model=MlbResearchModelFitPreviewResponse,
)
async def preview_mlb_research_model_fit(
    service: Annotated[MlbGameFeatureService, Depends(get_mlb_game_feature_service)],
) -> MlbResearchModelFitPreviewResponse:
    """Fit nothing until approved exploratory sample gates pass; never persist or publish."""
    try:
        model = await service.fit_research_preview()
    except MlbModelFittingBlockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(exc),
                "shortfall_by_split": {
                    split.value: count for split, count in exc.assessment.shortfall_by_split.items()
                },
                "blockers": exc.assessment.blockers,
            },
        ) from exc
    return MlbResearchModelFitPreviewResponse(
        persisted=False,
        model=model,
        operational_probability_enabled=False,
        automatic_trading_enabled=False,
    )


@router.post("/mlb-dataset-examples/run", response_model=MlbDatasetLabelResponse)
async def label_mlb_dataset_example(
    game_feature_vector_id: Annotated[UUID, Query()],
    validation_start: Annotated[datetime, Query()],
    test_start: Annotated[datetime, Query()],
    prospective_holdout_start: Annotated[datetime, Query()],
    service: Annotated[MlbGameFeatureService, Depends(get_mlb_game_feature_service)],
) -> MlbDatasetLabelResponse:
    """Freeze one official final result; this does not fit or run a model."""
    try:
        result = await service.label(
            vector_id=game_feature_vector_id,
            split_policy=MlbChronologicalDatasetPolicy(
                validation_start=validation_start,
                test_start=test_start,
                prospective_holdout_start=prospective_holdout_start,
            ),
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ValueError, MlbGameFeatureConflictError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return MlbDatasetLabelResponse(
        created=result.created,
        example=MlbLabeledFeatureExampleResponse.from_record(result.example),
    )


@router.get(
    "/mlb-dataset-examples",
    response_model=list[MlbLabeledFeatureExampleResponse],
)
async def list_mlb_dataset_examples(
    repository: Annotated[MlbGameFeatureRepository, Depends(get_mlb_game_feature_repository)],
    sports_event_id: Annotated[UUID | None, Query()] = None,
    game_feature_vector_id: Annotated[UUID | None, Query()] = None,
    split_policy_fingerprint: Annotated[str | None, Query(pattern=r"^[0-9a-f]{64}$")] = None,
    availability_basis: Annotated[MlbStatcastObservationBasis | None, Query()] = None,
    split: Annotated[MlbDatasetSplit | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MlbLabeledFeatureExampleResponse]:
    records = await repository.list_labeled_examples(
        sports_event_id=sports_event_id,
        game_feature_vector_id=game_feature_vector_id,
        split_policy_fingerprint=split_policy_fingerprint,
        availability_basis=(availability_basis.value if availability_basis is not None else None),
        split=(split.value if split is not None else None),
        limit=limit,
        offset=offset,
    )
    return [MlbLabeledFeatureExampleResponse.from_record(record) for record in records]


@router.get("/mlb-dataset-readiness", response_model=MlbDatasetInventoryResponse)
async def get_mlb_dataset_readiness(
    split_policy_fingerprint: Annotated[str, Query(pattern=r"^[0-9a-f]{64}$")],
    service: Annotated[MlbGameFeatureService, Depends(get_mlb_game_feature_service)],
) -> MlbDatasetInventoryResponse:
    inventory = await service.inventory(split_policy_fingerprint)
    return MlbDatasetInventoryResponse.from_inventory(inventory)


@router.get("/mlb-canonical-dataset", response_model=MlbCanonicalDatasetResponse)
async def get_mlb_canonical_dataset(
    split_policy_fingerprint: Annotated[str, Query(pattern=r"^[0-9a-f]{64}$")],
    service: Annotated[MlbGameFeatureService, Depends(get_mlb_game_feature_service)],
    include_retrospective_research: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MlbCanonicalDatasetResponse:
    selection = await service.canonical_dataset(
        split_policy_fingerprint=split_policy_fingerprint,
        include_retrospective_research=include_retrospective_research,
        limit=limit,
        offset=offset,
    )
    return MlbCanonicalDatasetResponse.from_selection(selection)


@router.get(
    "/mlb-approved-dataset-readiness",
    response_model=MlbApprovedDatasetReadinessResponse,
)
async def get_mlb_approved_dataset_readiness(
    service: Annotated[MlbGameFeatureService, Depends(get_mlb_game_feature_service)],
) -> MlbApprovedDatasetReadinessResponse:
    assessment = await service.approved_dataset_readiness()
    return MlbApprovedDatasetReadinessResponse.from_assessment(assessment)


@router.get(
    "/mlb-dataset-examples/{example_id}",
    response_model=MlbLabeledFeatureExampleResponse,
)
async def get_mlb_dataset_example(
    example_id: UUID,
    repository: Annotated[MlbGameFeatureRepository, Depends(get_mlb_game_feature_repository)],
) -> MlbLabeledFeatureExampleResponse:
    record = await repository.get_labeled_example(example_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="example not found")
    return MlbLabeledFeatureExampleResponse.from_record(record)
