from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import Settings, get_settings
from app.db.session import check_database_connection
from app.schemas.health import HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    """Report process liveness and the enforced trading mode."""
    return HealthResponse(status="ok", trading_mode=settings.trading_mode)


@router.get("/health/ready", response_model=ReadinessResponse)
def readiness(
    database_ready: Annotated[bool, Depends(check_database_connection)],
) -> ReadinessResponse:
    """Report readiness after verifying the PostgreSQL connection."""
    if not database_ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database unavailable",
        )
    return ReadinessResponse(status="ready")
