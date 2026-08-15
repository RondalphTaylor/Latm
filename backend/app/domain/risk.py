from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

RiskFraction = Annotated[
    Decimal,
    Field(ge=Decimal("0"), le=Decimal("1"), decimal_places=10),
]


class RiskDecisionType(StrEnum):
    """Deterministic Phase 7 risk outcomes."""

    REJECT = "reject"
    AUTO_APPROVE = "auto_approve"
    REQUIRE_HUMAN_APPROVAL = "require_human_approval"


class RiskEscalationBand(StrEnum):
    """Explain how exposure affected an otherwise valid decision."""

    HARD_REJECTION = "hard_rejection"
    AUTOMATIC = "automatic"
    MEDIUM_CONFIDENCE_UNAVAILABLE = "medium_confidence_unavailable"
    LARGE_EXPOSURE = "large_exposure"


class RiskCheckResult(BaseModel):
    """One ordered, structured risk-rule result."""

    model_config = ConfigDict(frozen=True)

    rule: str = Field(min_length=1, max_length=100)
    passed: bool
    actual: JsonValue
    expected: JsonValue
    detail: str = Field(min_length=1, max_length=300)


class RiskPolicy(BaseModel):
    """Immutable deterministic MVP risk policy."""

    model_config = ConfigDict(frozen=True)

    policy_name: str = "mvp_risk"
    code_version: str = "1.0.0"
    formula_version: str = "ordered_hard_checks_then_exposure_escalation_v1"
    auto_approve_exposure_max: RiskFraction = Decimal("0.1000000000")
    high_confidence_auto_approve_max: RiskFraction = Decimal("0.4000000000")
    min_raw_edge: RiskFraction = Decimal("0.0800000000")
    min_match_confidence: RiskFraction = Decimal("0.9000000000")
    max_market_price_age_seconds: int = Field(default=900, ge=1, le=86400)
    max_operational_forecast_age_seconds: int = Field(default=86400, ge=1, le=604800)
    authorization_ttl_seconds: int = Field(default=300, ge=1, le=3600)

    @model_validator(mode="after")
    def validate_thresholds(self) -> Self:
        if not (
            Decimal("0")
            < self.auto_approve_exposure_max
            < self.high_confidence_auto_approve_max
            <= Decimal("1")
        ):
            raise ValueError("risk exposure thresholds must increase within 100%")
        return self


class RiskEvaluationInput(BaseModel):
    """Exact proposal and authoritative mutable state observed for risk evaluation."""

    model_config = ConfigDict(frozen=True)

    proposal_id: UUID
    portfolio_id: UUID
    proposal_snapshot_id: UUID
    latest_snapshot_id: UUID
    opportunity_id: UUID
    market_id: UUID
    outcome_team_id: UUID
    direction: str = Field(pattern=r"^(yes|no)$")
    runtime_trading_mode: str
    proposal_execution_mode: str
    proposal_state: str
    confidence_basis: str
    portfolio_execution_mode: str
    portfolio_status: str
    portfolio_is_active: bool
    proposal_strategy_name: str
    proposal_strategy_version: str
    active_sizing_strategy_version: str
    proposal_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    opportunity_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposal_source_is_consistent: bool
    opportunity_is_current: bool
    opportunity_semantics_are_current: bool
    opportunity_status: str
    opportunity_trade_candidate_min_raw_edge: Decimal
    opportunity_valid_until: datetime
    snapshot_state_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_starting_bankroll: Decimal
    snapshot_current_bankroll: Decimal
    snapshot_cash_balance: Decimal
    snapshot_reserved_capital: Decimal
    snapshot_committed_capital: Decimal
    snapshot_available_bankroll: Decimal
    snapshot_realized_pnl: Decimal
    proposal_available_bankroll: Decimal
    proposed_capital: Decimal
    proposed_exposure_fraction: Decimal
    current_authorized_capital: Decimal
    duplicate_active_intent_exists: bool
    reference_price: Decimal
    model_probability: Decimal
    raw_edge: Decimal
    market_status: str
    market_close_time: datetime | None
    event_status: str
    event_postponed: bool
    event_start_time: datetime
    source_match_id: UUID
    latest_match_id: UUID
    latest_match_status: str
    latest_match_eligible: bool
    latest_match_confidence: Decimal
    source_market_price_id: UUID
    latest_market_price_id: UUID
    market_price_retrieved_at: datetime
    source_forecast_id: UUID
    latest_operational_forecast_id: UUID
    forecast_generated_at: datetime
    evaluated_at: datetime

    @field_validator(
        "opportunity_valid_until",
        "market_close_time",
        "event_start_time",
        "market_price_retrieved_at",
        "forecast_generated_at",
        "evaluated_at",
    )
    @classmethod
    def datetimes_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("risk evaluation times must be timezone-aware")
        return value


class RiskDecision(BaseModel):
    """Immutable risk authorization evidence; never an execution instruction."""

    model_config = ConfigDict(frozen=True)

    position_size_proposal_id: UUID
    portfolio_id: UUID
    portfolio_snapshot_id: UUID
    opportunity_id: UUID
    market_id: UUID
    outcome_team_id: UUID
    direction: str = Field(pattern=r"^(yes|no)$")
    execution_mode: str = Field(pattern=r"^paper$")
    decision: RiskDecisionType
    escalation_band: RiskEscalationBand
    primary_reason_code: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=500)
    all_required_checks_passed: bool
    hard_failure_count: int = Field(ge=0)
    failed_rules: tuple[str, ...]
    check_results: tuple[RiskCheckResult, ...] = Field(min_length=1)
    proposed_capital: Decimal
    proposal_available_bankroll: Decimal
    current_available_bankroll: Decimal
    current_authorized_capital: Decimal
    remaining_authorizable_bankroll: Decimal
    proposed_exposure_fraction: Decimal
    recomputed_exposure_fraction: Decimal
    reference_price: Decimal
    model_probability: Decimal
    raw_edge: Decimal
    edge_basis: str = Field(default="raw_edge", pattern=r"^raw_edge$")
    adjusted_edge_basis: str = Field(default="not_available", pattern=r"^not_available$")
    confidence_basis: str = Field(default="not_available", pattern=r"^not_available$")
    liquidity_basis: str = Field(default="not_evaluated_phase7", pattern=r"^not_evaluated_phase7$")
    match_confidence: Decimal
    market_price_age_seconds: int
    forecast_age_seconds: int
    risk_policy_name: str
    risk_policy_version: str
    risk_policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    auto_approve_exposure_max: Decimal
    high_confidence_auto_approve_max: Decimal
    min_raw_edge: Decimal
    min_match_confidence: Decimal
    max_market_price_age_seconds: int
    max_operational_forecast_age_seconds: int
    authorization_ttl_seconds: int
    proposal_strategy_name: str
    proposal_strategy_version: str
    proposal_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    opportunity_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluated_at: datetime
    authorization_valid_until: datetime | None
    audit_snapshot: dict[str, JsonValue]

    @field_validator("evaluated_at", "authorization_valid_until")
    @classmethod
    def decision_times_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("risk decision times must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_decision_state(self) -> Self:
        if self.all_required_checks_passed != (self.hard_failure_count == 0):
            raise ValueError("risk pass flag must agree with the hard-failure count")
        if self.hard_failure_count != len(self.failed_rules):
            raise ValueError("risk hard-failure count must match failed rules")
        if self.decision is RiskDecisionType.REJECT:
            if self.hard_failure_count == 0 or self.authorization_valid_until is not None:
                raise ValueError("rejected risk decisions require failures and no authorization")
        elif self.authorization_valid_until is None:
            raise ValueError("non-rejected risk decisions require an authorization expiry")
        if (
            self.decision is RiskDecisionType.AUTO_APPROVE
            and self.proposed_exposure_fraction >= self.auto_approve_exposure_max
        ):
            raise ValueError("automatic approval must remain below its exposure boundary")
        if (
            self.decision is RiskDecisionType.REQUIRE_HUMAN_APPROVAL
            and self.proposed_exposure_fraction < self.auto_approve_exposure_max
        ):
            raise ValueError("human escalation must begin at the automatic boundary")
        return self
