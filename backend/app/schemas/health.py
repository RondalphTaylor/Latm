from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.core.config import TradingMode


class HealthResponse(BaseModel):
    """Process liveness response."""

    status: Literal["ok"]
    trading_mode: TradingMode


class ReadinessResponse(BaseModel):
    """Database readiness response."""

    status: Literal["ready"]
