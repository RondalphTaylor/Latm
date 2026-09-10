from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, TradingMode, get_settings
from app.db.session import get_session
from app.schemas.nfl_shadow_evaluation import (
    NflShadowEvaluationDetailResponse,
    NflShadowEvaluationResponse,
    NflShadowEvaluationRunResponse,
)
from app.services.nfl_research.shadow_evaluation_repository import (
    NflShadowCanonicalPerformance,
    NflShadowEvaluationRepository,
)

router = APIRouter(tags=["nfl-shadow-evaluation"])


def get_nfl_shadow_evaluation_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NflShadowEvaluationRepository:
    return NflShadowEvaluationRepository(session)


@router.post("/nfl-shadow-labels/run", response_model=NflShadowEvaluationRunResponse)
async def run_nfl_shadow_label(
    snapshot_id: UUID,
    repository: Annotated[
        NflShadowEvaluationRepository, Depends(get_nfl_shadow_evaluation_repository)
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> NflShadowEvaluationRunResponse:
    """Label one prospective snapshot from local finals without settling a contract."""
    if settings.trading_mode is not TradingMode.PAPER:
        raise HTTPException(status_code=409, detail="NFL shadow labeling requires paper mode")
    try:
        record, created = await repository.run(snapshot_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return NflShadowEvaluationRunResponse(
        created=created, label=NflShadowEvaluationResponse.model_validate(record)
    )


@router.get("/nfl-shadow-labels", response_model=list[NflShadowEvaluationResponse])
async def list_nfl_shadow_labels(
    repository: Annotated[
        NflShadowEvaluationRepository, Depends(get_nfl_shadow_evaluation_repository)
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[NflShadowEvaluationResponse]:
    records = await repository.list_labels(limit=limit, offset=offset)
    return [NflShadowEvaluationResponse.model_validate(record) for record in records]


@router.get("/nfl-shadow-labels/{label_id}", response_model=NflShadowEvaluationDetailResponse)
async def get_nfl_shadow_label(
    label_id: UUID,
    repository: Annotated[
        NflShadowEvaluationRepository, Depends(get_nfl_shadow_evaluation_repository)
    ],
) -> NflShadowEvaluationDetailResponse:
    record = await repository.get_label(label_id)
    if record is None:
        raise HTTPException(status_code=404, detail="NFL shadow label not found")
    return NflShadowEvaluationDetailResponse.model_validate(record)


@router.get("/nfl-shadow-performance", response_model=NflShadowCanonicalPerformance)
async def get_nfl_shadow_performance(
    repository: Annotated[
        NflShadowEvaluationRepository, Depends(get_nfl_shadow_evaluation_repository)
    ],
) -> NflShadowCanonicalPerformance:
    """Score one canonical snapshot per event/model/seed; no provider or trading call."""
    try:
        return await repository.performance()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
