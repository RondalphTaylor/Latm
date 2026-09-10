from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue


class NflShadowForecastResponse(BaseModel):
    """Compact prospective research record, never a trading authorization."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    match_id: UUID
    market_id: UUID
    sports_event_id: UUID
    yes_team_id: UUID
    model_version: str
    seed_fingerprint: str
    input_fingerprint: str
    generated_at: datetime
    scheduled_start_time: datetime
    target_source_last_seen_at: datetime
    expected_home_payout: Decimal
    expected_away_payout: Decimal
    expected_yes_payout: Decimal
    expected_no_payout: Decimal
    research_only: Literal[True]
    trading_enabled: Literal[False]
    model_basis: Literal["frozen_preseason_2026"] = "frozen_preseason_2026"
    warnings: tuple[str, ...] = (
        "Shadow research only; not an operational forecast or trading authorization.",
        "Expected payout is not win probability; ties have half payout.",
        "Frozen preseason ratings do not incorporate 2026 results or injuries.",
        "Historical coverage and real-time source availability are not independently verified.",
    )


class NflShadowForecastDetailResponse(NflShadowForecastResponse):
    """Exact seed, target, contract, and calculation evidence for offline audit."""

    audit: dict[str, JsonValue]


class NflShadowForecastRunResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    created: bool
    snapshot: NflShadowForecastResponse
