from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

ExpectedPayout = Annotated[Decimal, Field(ge=0, le=1, decimal_places=6, allow_inf_nan=False)]


class NflPayoutForecastCandidate(BaseModel):
    """Blocked paper-integration candidate, not an operational probability forecast."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    match_id: UUID
    market_id: UUID
    event_id: UUID
    home_team_id: UUID
    away_team_id: UUID
    yes_team_id: UUID
    model_version: str
    seed_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_shadow_snapshot_id: UUID
    generated_at: AwareDatetime
    valid_until: AwareDatetime
    expected_home_payout: ExpectedPayout
    expected_away_payout: ExpectedPayout
    expected_yes_payout: ExpectedPayout
    expected_no_payout: ExpectedPayout
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    purpose: Literal["paper_candidate"] = "paper_candidate"
    metric_kind: Literal["expected_payout"] = "expected_payout"
    execution_mode: Literal["paper"] = "paper"
    operational_eligible: Literal[False] = False
    trading_enabled: Literal[False] = False
    promotion_state: Literal["blocked"] = "blocked"
    block_reasons: tuple[Literal["promotion_review_required"], ...] = ("promotion_review_required",)

    @field_validator("generated_at", "valid_until")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_candidate(self) -> Self:
        if self.home_team_id == self.away_team_id:
            raise ValueError("candidate requires distinct teams")
        if self.yes_team_id not in {self.home_team_id, self.away_team_id}:
            raise ValueError("candidate YES team must belong to the game")
        if self.valid_until <= self.generated_at:
            raise ValueError("candidate requires a strictly future expiry")
        if self.expected_home_payout + self.expected_away_payout != Decimal("1"):
            raise ValueError("candidate home/away payouts must be complementary")
        if self.expected_yes_payout + self.expected_no_payout != Decimal("1"):
            raise ValueError("candidate YES/NO payouts must be complementary")
        selected = (
            self.expected_home_payout
            if self.yes_team_id == self.home_team_id
            else self.expected_away_payout
        )
        if self.expected_yes_payout != selected:
            raise ValueError("candidate payout orientation conflicts with YES team")
        if self.block_reasons != ("promotion_review_required",):
            raise ValueError("promotion review blocker must remain present")
        return self
