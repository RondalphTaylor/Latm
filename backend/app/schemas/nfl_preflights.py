from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NflPaperPreflightResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    opportunity_id: UUID
    direction: str
    reviewed_at: datetime
    valid_until: datetime
    capital_cap: Decimal
    execution_price: Decimal | None
    quantity: int
    total_cost: Decimal
    adjusted_edge: Decimal | None
    sizing_status: str
    risk_decision: str
    execution_enabled: bool
    reason: str
    warnings: tuple[str, ...] = (
        "This is a paper-only cost review, not a position-size proposal or authorization.",
        "NFL promotion remains blocked; no execution path exists.",
    )


class NflPaperPreflightRunResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    created: bool
    preflight: NflPaperPreflightResponse
