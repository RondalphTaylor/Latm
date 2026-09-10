from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue

from app.domain.nfl_opportunities import NflPaperOpportunityComparison


class NflPaperOpportunityResponse(NflPaperOpportunityComparison):
    """Immutable comparison history, never a current trading authorization."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    idempotency_key: str
    warnings: tuple[str, ...] = (
        "Pre-cost expected payout minus direct ask; fees and slippage are not included.",
        "Displayed asks do not establish available depth or guarantee a fill.",
        "Promotion is blocked; paper_candidate status does not authorize trading.",
        "History and retries do not revalidate current prices or extend expiry.",
    )


class NflPaperOpportunityDetailResponse(NflPaperOpportunityResponse):
    audit: dict[str, JsonValue]


class NflPaperOpportunityRunResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    created: bool
    opportunity: NflPaperOpportunityResponse
