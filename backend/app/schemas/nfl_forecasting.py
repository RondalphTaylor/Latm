from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue


class NflPayoutForecastResponse(BaseModel):
    """Immutable paper candidate, not a currently authorized forecast feed."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    idempotency_key: str
    match_id: UUID
    market_id: UUID
    event_id: UUID
    source_shadow_snapshot_id: UUID
    home_team_id: UUID
    away_team_id: UUID
    yes_team_id: UUID
    model_version: str
    seed_fingerprint: str
    generated_at: datetime
    valid_until: datetime
    expected_home_payout: Decimal
    expected_away_payout: Decimal
    expected_yes_payout: Decimal
    expected_no_payout: Decimal
    purpose: Literal["paper_candidate"]
    metric_kind: Literal["expected_payout"]
    execution_mode: Literal["paper"]
    promotion_state: Literal["blocked"]
    operational_eligible: Literal[False]
    trading_enabled: Literal[False]
    input_fingerprint: str
    block_reasons: tuple[str, ...] = ("promotion_review_required",)
    warnings: tuple[str, ...] = (
        "Unpromoted candidate: cannot authorize opportunities, sizing, risk or execution.",
        "Expected payout is not a Bernoulli win probability or official settlement.",
        "Frozen ratings omit 2026 results and injuries; a fresh capture does not update the model.",
        "Historical reads and retries do not renew expiry or assert current source eligibility.",
    )


class NflPayoutForecastDetailResponse(NflPayoutForecastResponse):
    audit: dict[str, JsonValue]


class NflPayoutForecastRunResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    created: bool
    forecast: NflPayoutForecastResponse
