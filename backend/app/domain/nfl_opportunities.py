from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

ComparisonStatus = Literal["ignore", "watch", "paper_candidate", "ineligible"]


class NflPaperOpportunityPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    watch_threshold: Decimal = Field(default=Decimal("0.03"), ge=0, le=1, decimal_places=6)
    candidate_threshold: Decimal = Field(default=Decimal("0.08"), ge=0, le=1, decimal_places=6)
    max_price_age_seconds: int = Field(default=900, gt=0, le=900, strict=True)

    @model_validator(mode="after")
    def ordered_thresholds(self) -> Self:
        if self.watch_threshold >= self.candidate_threshold:
            raise ValueError("watch threshold must be below candidate threshold")
        return self


class NflPaperOpportunityComparison(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    forecast_id: UUID
    market_id: UUID
    match_id: UUID
    event_id: UUID
    price_id: UUID | None
    price_retrieved_at: AwareDatetime | None
    evaluated_at: AwareDatetime
    valid_until: AwareDatetime | None
    yes_expected_payout: Decimal = Field(ge=0, le=1, decimal_places=6, allow_inf_nan=False)
    no_expected_payout: Decimal = Field(ge=0, le=1, decimal_places=6, allow_inf_nan=False)
    yes_direct_ask: Decimal | None = Field(ge=0, le=1, allow_inf_nan=False)
    no_direct_ask: Decimal | None = Field(ge=0, le=1, allow_inf_nan=False)
    yes_raw_edge: Decimal | None = Field(ge=-1, le=1, decimal_places=6, allow_inf_nan=False)
    no_raw_edge: Decimal | None = Field(ge=-1, le=1, decimal_places=6, allow_inf_nan=False)
    yes_status: ComparisonStatus
    no_status: ComparisonStatus
    yes_reason: str
    no_reason: str
    policy_version: str
    policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_mode: Literal["paper"] = "paper"
    promotion_state: Literal["blocked"] = "blocked"
    operational_eligible: Literal[False] = False
    trading_enabled: Literal[False] = False
    costs_included: Literal[False] = False
    depth_verified: Literal[False] = False

    @model_validator(mode="after")
    def validate_comparison(self) -> Self:
        if self.yes_expected_payout + self.no_expected_payout != Decimal(1):
            raise ValueError("comparison expected payouts must complement")
        for expected, ask, edge, status in (
            (self.yes_expected_payout, self.yes_direct_ask, self.yes_raw_edge, self.yes_status),
            (self.no_expected_payout, self.no_direct_ask, self.no_raw_edge, self.no_status),
        ):
            if status == "ineligible":
                if edge is not None:
                    raise ValueError("ineligible comparison cannot expose a raw edge")
            elif (
                ask is None
                or not Decimal(0) < ask < Decimal(1)
                or edge != (expected - ask).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            ):
                raise ValueError("comparable side requires its exact direct-ask raw edge")
        comparable = self.yes_status != "ineligible" or self.no_status != "ineligible"
        if comparable:
            if (
                self.price_id is None
                or self.price_retrieved_at is None
                or self.price_retrieved_at > self.evaluated_at
                or self.valid_until is None
                or self.valid_until <= self.evaluated_at
            ):
                raise ValueError(
                    "comparable opportunity requires current quote identity and expiry"
                )
        elif self.valid_until is not None:
            raise ValueError("fully ineligible comparison must have no valid window")
        return self
