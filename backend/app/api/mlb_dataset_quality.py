from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.mlb_dataset_quality import (
    MlbDatasetQualityAuditResponse,
    MlbDatasetQualityAuditRunResponse,
)
from app.services.mlb_modeling.quality_repository import MlbDatasetQualityRepository
from app.services.mlb_modeling.quality_service import MlbDatasetQualityService
from app.services.mlb_modeling.repository import MlbGameFeatureRepository

router = APIRouter(tags=["mlb-dataset-quality"])


def get_mlb_dataset_quality_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MlbDatasetQualityRepository:
    return MlbDatasetQualityRepository(session)


def get_mlb_dataset_quality_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    quality_repository: Annotated[
        MlbDatasetQualityRepository, Depends(get_mlb_dataset_quality_repository)
    ],
) -> MlbDatasetQualityService:
    return MlbDatasetQualityService(
        feature_repository=MlbGameFeatureRepository(session),
        quality_repository=quality_repository,
    )


@router.post(
    "/mlb-dataset-quality-audits/run",
    response_model=MlbDatasetQualityAuditRunResponse,
)
async def run_mlb_dataset_quality_audit(
    service: Annotated[MlbDatasetQualityService, Depends(get_mlb_dataset_quality_service)],
) -> MlbDatasetQualityAuditRunResponse:
    """Audit and freeze the approved canonical dataset without fitting or forecasting."""
    try:
        result = await service.run()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return MlbDatasetQualityAuditRunResponse(
        created=result.created,
        audit=MlbDatasetQualityAuditResponse.from_record(result.audit),
    )


@router.get(
    "/mlb-dataset-quality-audits",
    response_model=list[MlbDatasetQualityAuditResponse],
)
async def list_mlb_dataset_quality_audits(
    repository: Annotated[MlbDatasetQualityRepository, Depends(get_mlb_dataset_quality_repository)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MlbDatasetQualityAuditResponse]:
    records = await repository.list_audits(limit=limit, offset=offset)
    return [MlbDatasetQualityAuditResponse.from_record(record) for record in records]


@router.get(
    "/mlb-dataset-quality-audits/{audit_id}",
    response_model=MlbDatasetQualityAuditResponse,
)
async def get_mlb_dataset_quality_audit(
    audit_id: UUID,
    repository: Annotated[MlbDatasetQualityRepository, Depends(get_mlb_dataset_quality_repository)],
) -> MlbDatasetQualityAuditResponse:
    record = await repository.get_audit(audit_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="quality audit not found")
    return MlbDatasetQualityAuditResponse.from_record(record)
