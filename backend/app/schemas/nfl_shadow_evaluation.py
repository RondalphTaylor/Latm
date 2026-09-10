from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue


class NflShadowEvaluationResponse(BaseModel):
    """One immutable score against a validated provider final, not settlement."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    snapshot_id: UUID
    sports_event_id: UUID
    model_version: str
    seed_fingerprint: str
    evaluation_version: str
    snapshot_fingerprint: str
    result_fingerprint: str
    input_fingerprint: str
    label_time: datetime
    generated_at: datetime
    scheduled_start_time: datetime
    result_source_last_seen_at: datetime
    expected_home_payout: Decimal
    expected_yes_payout: Decimal
    actual_home_payout: Decimal
    actual_yes_payout: Decimal
    squared_home_payout_error: Decimal
    constant_half_squared_error: Decimal
    research_only: Literal[True]
    trading_enabled: Literal[False]
    settlement_performed: Literal[False] = False


class NflShadowEvaluationDetailResponse(NflShadowEvaluationResponse):
    audit: dict[str, JsonValue]


class NflShadowEvaluationRunResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    created: bool
    label: NflShadowEvaluationResponse
