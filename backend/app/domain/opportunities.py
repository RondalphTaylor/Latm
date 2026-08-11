from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

Probability = Annotated[
    Decimal,
    Field(ge=Decimal("0"), le=Decimal("1"), decimal_places=6),
]
SignedEdge = Annotated[
    Decimal,
    Field(ge=Decimal("-1"), le=Decimal("1"), decimal_places=6),
]


class OpportunityDirection(StrEnum):
    """Purchasable sides of a normalized binary contract."""

    YES = "yes"
    NO = "no"


class OpportunityStatus(StrEnum):
    """Research classifications that confer no trading authority."""

    IGNORE = "ignore"
    WATCH = "watch"
    TRADE_CANDIDATE = "trade_candidate"


class OpportunityPriceSource(StrEnum):
    """Normalized executable price fields supported by V1."""

    DIRECT_YES_ASK = "direct_yes_ask"
    DIRECT_NO_ASK = "direct_no_ask"


class OpportunityPolicy(BaseModel):
    """Immutable, fully recorded V1 raw-edge classification policy."""

    model_config = ConfigDict(frozen=True)

    strategy_name: str = "raw_edge"
    code_version: str = "1.0.0"
    formula_version: str = "side_ask_minus_independent_base_v1"
    forecast_model_name: str = "nba_elo"
    watch_min_raw_edge: Probability = Decimal("0.030000")
    trade_candidate_min_raw_edge: Probability = Decimal("0.080000")
    max_market_price_age_seconds: int = Field(default=900, ge=1, le=86400)
    max_operational_forecast_age_seconds: int = Field(
        default=86400,
        ge=1,
        le=604800,
    )

    @model_validator(mode="after")
    def validate_threshold_order(self) -> Self:
        if self.watch_min_raw_edge >= self.trade_candidate_min_raw_edge:
            raise ValueError("watch threshold must be below trade-candidate threshold")
        return self


class OpportunityTeamInput(BaseModel):
    """Provider-neutral team labels used to orient contract outcomes."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    abbreviation: str = Field(min_length=2, max_length=10)
    city: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    full_name: str = Field(min_length=1, max_length=200)


class OpportunityOutcomeInput(BaseModel):
    """One normalized market outcome label."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    side: OpportunityDirection
    label: str = Field(min_length=1, max_length=500)


class OutcomeOrientation(BaseModel):
    """Unambiguous mapping from contract sides to the matched event teams."""

    model_config = ConfigDict(frozen=True)

    yes_team_id: UUID
    no_team_id: UUID
    mapping_method: str = Field(min_length=1, max_length=100)
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_distinct_teams(self) -> Self:
        if self.yes_team_id == self.no_team_id:
            raise ValueError("opportunity outcome teams must be distinct")
        return self


class OpportunityEvaluationInput(BaseModel):
    """Exact persisted snapshots used for one directional edge comparison."""

    model_config = ConfigDict(frozen=True)

    market_id: UUID
    market_price_id: UUID
    market_event_match_id: UUID
    sports_event_id: UUID
    base_forecast_id: UUID
    model_version_id: UUID
    outcome_team_id: UUID
    yes_team_id: UUID
    no_team_id: UUID
    direction: OpportunityDirection
    price_source: OpportunityPriceSource
    mapping_method: str = Field(min_length=1, max_length=100)
    orientation_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    match_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    forecast_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    market_probability: Probability
    model_probability: Probability
    price_retrieved_at: datetime
    forecast_generated_at: datetime
    valid_until: datetime
    evaluated_at: datetime
    source_snapshot: dict[str, JsonValue]

    @field_validator(
        "price_retrieved_at",
        "forecast_generated_at",
        "valid_until",
        "evaluated_at",
    )
    @classmethod
    def datetimes_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("opportunity datetimes must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_source_times(self) -> Self:
        if self.price_retrieved_at > self.evaluated_at:
            raise ValueError("market price timestamp cannot be after evaluation")
        if self.forecast_generated_at > self.evaluated_at:
            raise ValueError("forecast timestamp cannot be after evaluation")
        if self.evaluated_at > self.valid_until:
            raise ValueError("opportunity inputs are no longer fresh")
        if self.yes_team_id == self.no_team_id:
            raise ValueError("YES and NO teams must be distinct")
        expected_team_id = (
            self.yes_team_id if self.direction is OpportunityDirection.YES else self.no_team_id
        )
        if self.outcome_team_id != expected_team_id:
            raise ValueError("direction outcome team does not match orientation")
        return self


class OpportunityDecision(BaseModel):
    """Append-only research classification for one directional contract side."""

    model_config = ConfigDict(frozen=True)

    market_id: UUID
    market_price_id: UUID
    market_event_match_id: UUID
    sports_event_id: UUID
    base_forecast_id: UUID
    model_version_id: UUID
    outcome_team_id: UUID
    yes_team_id: UUID
    no_team_id: UUID
    direction: OpportunityDirection
    price_source: OpportunityPriceSource
    mapping_method: str = Field(min_length=1, max_length=100)
    orientation_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    market_probability: Probability
    model_probability: Probability
    raw_edge: SignedEdge
    status: OpportunityStatus
    status_reason: str = Field(min_length=1, max_length=200)
    strategy_name: str = Field(min_length=1, max_length=50)
    strategy_version: str = Field(min_length=1, max_length=100)
    watch_min_raw_edge: Probability
    trade_candidate_min_raw_edge: Probability
    max_market_price_age_seconds: int = Field(ge=1)
    max_operational_forecast_age_seconds: int = Field(ge=1)
    policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    price_retrieved_at: datetime
    forecast_generated_at: datetime
    price_age_seconds: int = Field(ge=0)
    forecast_age_seconds: int = Field(ge=0)
    valid_until: datetime
    evaluated_at: datetime
    source_snapshot: dict[str, JsonValue]

    @field_validator(
        "price_retrieved_at",
        "forecast_generated_at",
        "valid_until",
        "evaluated_at",
    )
    @classmethod
    def datetimes_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("opportunity datetimes must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_calculation_and_status(self) -> Self:
        if self.raw_edge != self.model_probability - self.market_probability:
            raise ValueError("raw edge must equal model probability minus market probability")
        if self.watch_min_raw_edge >= self.trade_candidate_min_raw_edge:
            raise ValueError("opportunity thresholds are not ordered")
        if self.yes_team_id == self.no_team_id:
            raise ValueError("YES and NO teams must be distinct")
        expected_team_id = (
            self.yes_team_id if self.direction is OpportunityDirection.YES else self.no_team_id
        )
        if self.outcome_team_id != expected_team_id:
            raise ValueError("direction outcome team does not match orientation")
        if self.price_retrieved_at > self.evaluated_at:
            raise ValueError("market price timestamp cannot be after evaluation")
        if self.forecast_generated_at > self.evaluated_at:
            raise ValueError("forecast timestamp cannot be after evaluation")
        if self.evaluated_at > self.valid_until:
            raise ValueError("opportunity decision cannot outlive its inputs")
        expected_status = (
            OpportunityStatus.IGNORE
            if self.raw_edge < self.watch_min_raw_edge
            else OpportunityStatus.WATCH
            if self.raw_edge < self.trade_candidate_min_raw_edge
            else OpportunityStatus.TRADE_CANDIDATE
        )
        if self.status is not expected_status:
            raise ValueError("opportunity status does not match its raw edge")
        return self
