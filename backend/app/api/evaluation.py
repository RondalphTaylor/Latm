from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.domain.forecast_evaluation import ForecastEvaluationPolicy
from app.domain.forecasts import ForecastPurpose
from app.schemas.evaluation import (
    ForecastEvaluationResponse,
    ForecastEvaluationRunResponse,
    ForecastPerformanceResponse,
    PairedModelComparisonResponse,
    TradingPerformanceResponse,
)
from app.services.evaluation.repository import EvaluationRepository
from app.services.evaluation.service import (
    ForecastEvaluationService,
    TradingPerformanceService,
)

router = APIRouter(tags=["evaluation"])


def get_evaluation_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EvaluationRepository:
    return EvaluationRepository(session)


def get_forecast_evaluation_service(
    repository: Annotated[EvaluationRepository, Depends(get_evaluation_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ForecastEvaluationService:
    return ForecastEvaluationService(
        repository=repository,
        policy=ForecastEvaluationPolicy(
            calibration_bin_count=settings.evaluation_calibration_bin_count
        ),
    )


def get_trading_performance_service(
    repository: Annotated[EvaluationRepository, Depends(get_evaluation_repository)],
) -> TradingPerformanceService:
    return TradingPerformanceService(repository=repository)


@router.post("/forecast-evaluations/run", response_model=ForecastEvaluationRunResponse)
async def run_forecast_evaluations(
    service: Annotated[ForecastEvaluationService, Depends(get_forecast_evaluation_service)],
    purpose: Annotated[ForecastPurpose, Query()],
    start_date: Annotated[date, Query()],
    end_date: Annotated[date, Query()],
    event_id: Annotated[UUID | None, Query()] = None,
    model_version_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 250,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ForecastEvaluationRunResponse:
    """Freeze scores for a bounded set of current canonical completed forecasts."""
    try:
        result = await service.run(
            purpose=purpose,
            start_date=start_date,
            end_date=end_date,
            event_id=event_id,
            model_version_id=model_version_id,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return ForecastEvaluationRunResponse.from_result(result)


@router.get("/forecast-evaluations", response_model=list[ForecastEvaluationResponse])
async def list_forecast_evaluations(
    repository: Annotated[EvaluationRepository, Depends(get_evaluation_repository)],
    forecast_id: Annotated[UUID | None, Query()] = None,
    sports_event_id: Annotated[UUID | None, Query()] = None,
    purpose: Annotated[ForecastPurpose | None, Query()] = None,
    model_name: Annotated[str | None, Query(min_length=1, max_length=50)] = None,
    model_version: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    evaluator_version: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ForecastEvaluationResponse]:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="start_date must not be after end_date",
        )
    records = await repository.list_forecast_evaluations(
        forecast_id=forecast_id,
        sports_event_id=sports_event_id,
        purpose=purpose,
        model_name=model_name,
        model_version=model_version,
        start_date=start_date,
        end_date=end_date,
        evaluator_version=evaluator_version,
        limit=limit,
        offset=offset,
    )
    return [ForecastEvaluationResponse.from_record(record) for record in records]


@router.get(
    "/forecast-performance/compare",
    response_model=PairedModelComparisonResponse,
)
async def compare_forecast_models(
    service: Annotated[ForecastEvaluationService, Depends(get_forecast_evaluation_service)],
    purpose: Annotated[ForecastPurpose, Query()],
    model_a_version_id: Annotated[UUID, Query()],
    model_b_version_id: Annotated[UUID, Query()],
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
) -> PairedModelComparisonResponse:
    try:
        comparison = await service.compare(
            purpose=purpose,
            model_a_version_id=model_a_version_id,
            model_b_version_id=model_b_version_id,
            start_date=start_date,
            end_date=end_date,
        )
        warnings = (
            (
                (
                    "historical_replay is retrospective; result-availability time "
                    "is not preserved by the current sports-event schema"
                ),
            )
            if purpose is ForecastPurpose.HISTORICAL_REPLAY
            else ()
        )
        return PairedModelComparisonResponse(comparison=comparison, warnings=warnings)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.get("/forecast-performance", response_model=ForecastPerformanceResponse)
async def get_forecast_performance(
    service: Annotated[ForecastEvaluationService, Depends(get_forecast_evaluation_service)],
    purpose: Annotated[ForecastPurpose, Query()],
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    model_version_id: Annotated[list[UUID] | None, Query()] = None,
) -> ForecastPerformanceResponse:
    try:
        result = await service.performance(
            purpose=purpose,
            start_date=start_date,
            end_date=end_date,
            model_version_ids=(tuple(model_version_id) if model_version_id else None),
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return ForecastPerformanceResponse.from_result(result)


@router.get("/forecast-evaluations/{evaluation_id}", response_model=ForecastEvaluationResponse)
async def get_forecast_evaluation(
    evaluation_id: UUID,
    repository: Annotated[EvaluationRepository, Depends(get_evaluation_repository)],
) -> ForecastEvaluationResponse:
    record = await repository.get_forecast_evaluation(evaluation_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="forecast evaluation not found",
        )
    return ForecastEvaluationResponse.from_record(record)


@router.get(
    "/portfolios/{portfolio_id}/performance",
    response_model=TradingPerformanceResponse,
)
async def get_portfolio_performance(
    portfolio_id: UUID,
    service: Annotated[TradingPerformanceService, Depends(get_trading_performance_service)],
) -> TradingPerformanceResponse:
    try:
        result = await service.evaluate(portfolio_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return TradingPerformanceResponse.model_validate(result.model_dump())
