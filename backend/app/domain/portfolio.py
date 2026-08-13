from __future__ import annotations

from datetime import datetime
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

Money = Annotated[
    Decimal,
    Field(ge=Decimal("0"), max_digits=18, decimal_places=2),
]
PositiveMoney = Annotated[
    Decimal,
    Field(gt=Decimal("0"), max_digits=18, decimal_places=2),
]
Fraction = Annotated[
    Decimal,
    Field(ge=Decimal("0"), le=Decimal("1"), decimal_places=6),
]

_CENT = Decimal("0.01")
_EXPOSURE_QUANTUM = Decimal("0.0000000001")


class PortfolioMode(StrEnum):
    """Execution modes supported by the portfolio model."""

    PAPER = "paper"


class PortfolioSnapshotReason(StrEnum):
    """Reasons supported by the initial immutable balance ledger."""

    CREATED = "created"


class PortfolioStatus(StrEnum):
    """Portfolio lifecycle states supported by Phase 6."""

    ACTIVE = "active"


class PositionSizeProposalState(StrEnum):
    """Pre-risk lifecycle states available in Phase 6."""

    AWAITING_RISK = "awaiting_risk"


class PositionSizingConfidenceBasis(StrEnum):
    """Confidence inputs supported by the sizing strategy."""

    NOT_AVAILABLE = "not_available"


class PositionSizingPolicy(BaseModel):
    """Immutable rules-v1 sizing bands and allocation fractions."""

    model_config = ConfigDict(frozen=True)

    strategy_name: str = "raw_edge_bands"
    code_version: str = "1.0.0"
    formula_version: str = "available_bankroll_raw_edge_bands_floor_cents_v1"
    candidate_min_raw_edge: Fraction = Decimal("0.080000")
    strong_min_raw_edge: Fraction = Decimal("0.120000")
    very_strong_min_raw_edge: Fraction = Decimal("0.180000")
    candidate_exposure_fraction: Fraction = Decimal("0.020000")
    strong_exposure_fraction: Fraction = Decimal("0.050000")
    very_strong_exposure_fraction: Fraction = Decimal("0.080000")
    max_exposure_fraction: Fraction = Decimal("0.080000")

    @model_validator(mode="after")
    def validate_bands_and_cap(self) -> Self:
        if not (
            self.candidate_min_raw_edge < self.strong_min_raw_edge < self.very_strong_min_raw_edge
        ):
            raise ValueError("position-sizing edge bands must be strictly increasing")
        if not (
            Decimal("0")
            < self.candidate_exposure_fraction
            < self.strong_exposure_fraction
            < self.very_strong_exposure_fraction
            <= self.max_exposure_fraction
            < Decimal("0.10")
        ):
            raise ValueError("position-sizing exposure bands must increase and remain below 10%")
        return self


class PortfolioDefinition(BaseModel):
    """Immutable paper-portfolio identity and starting capital."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    idempotency_key: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    mode: PortfolioMode = PortfolioMode.PAPER
    currency: str = Field(default="USD", pattern=r"^USD$")
    starting_bankroll: PositiveMoney
    status: PortfolioStatus = PortfolioStatus.ACTIVE
    creation_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def created_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("portfolio creation time must be timezone-aware")
        return value


class PortfolioSnapshot(BaseModel):
    """Immutable accounting state used by a sizing decision."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    portfolio_id: UUID
    sequence: int = Field(ge=0)
    mode: PortfolioMode = PortfolioMode.PAPER
    currency: str = Field(default="USD", pattern=r"^USD$")
    starting_bankroll: PositiveMoney
    current_bankroll: Money
    cash_balance: Money
    reserved_capital: Money
    committed_capital: Money
    available_bankroll: Money
    realized_pnl: Decimal = Field(max_digits=18, decimal_places=2)
    reason: PortfolioSnapshotReason
    state_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    captured_at: datetime

    @field_validator("captured_at")
    @classmethod
    def captured_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("portfolio snapshot time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_accounting_equations(self) -> Self:
        if self.current_bankroll != self.starting_bankroll + self.realized_pnl:
            raise ValueError("current bankroll must equal starting bankroll plus realized P&L")
        if self.cash_balance != self.current_bankroll - self.committed_capital:
            raise ValueError("cash balance must equal bankroll minus committed capital")
        if self.available_bankroll != self.cash_balance - self.reserved_capital:
            raise ValueError("available bankroll must equal cash minus reserved capital")
        if self.committed_capital + self.reserved_capital > self.current_bankroll:
            raise ValueError("committed and reserved capital cannot exceed bankroll")
        if self.reason is PortfolioSnapshotReason.CREATED and (
            self.sequence != 0
            or self.current_bankroll != self.starting_bankroll
            or self.cash_balance != self.starting_bankroll
            or self.available_bankroll != self.starting_bankroll
            or self.committed_capital != 0
            or self.reserved_capital != 0
            or self.realized_pnl != 0
        ):
            raise ValueError("created portfolio snapshot must contain an untouched bankroll")
        return self


class PositionSizingInput(BaseModel):
    """Exact current opportunity and paper-balance snapshot to size."""

    model_config = ConfigDict(frozen=True)

    portfolio_snapshot_id: UUID
    portfolio: PortfolioSnapshot
    opportunity_id: UUID
    market_id: UUID
    outcome_team_id: UUID
    direction: str = Field(pattern=r"^(yes|no)$")
    reference_price: Decimal = Field(gt=Decimal("0"), lt=Decimal("1"), decimal_places=6)
    model_probability: Decimal = Field(ge=Decimal("0"), le=Decimal("1"), decimal_places=6)
    raw_edge: Decimal = Field(ge=Decimal("-1"), le=Decimal("1"), decimal_places=6)
    opportunity_status: str
    opportunity_strategy_name: str
    opportunity_strategy_version: str
    opportunity_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    opportunity_evaluated_at: datetime
    opportunity_valid_until: datetime
    proposed_at: datetime
    source_snapshot: dict[str, JsonValue]

    @field_validator("opportunity_evaluated_at", "opportunity_valid_until", "proposed_at")
    @classmethod
    def datetimes_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("position-sizing times must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_input_integrity(self) -> Self:
        if self.portfolio_snapshot_id != self.portfolio.id:
            raise ValueError("portfolio snapshot ID must match the embedded snapshot")
        if self.raw_edge != self.model_probability - self.reference_price:
            raise ValueError("raw edge must match the opportunity probabilities")
        if self.proposed_at > self.opportunity_valid_until:
            raise ValueError("position sizing cannot use an expired opportunity")
        if self.opportunity_evaluated_at > self.proposed_at:
            raise ValueError("opportunity cannot be evaluated after sizing")
        return self


class PositionSizeProposal(BaseModel):
    """Advisory position-size output that still requires deterministic risk review."""

    model_config = ConfigDict(frozen=True)

    portfolio_id: UUID
    portfolio_snapshot_id: UUID
    opportunity_id: UUID
    market_id: UUID
    outcome_team_id: UUID
    mode: PortfolioMode
    direction: str = Field(pattern=r"^(yes|no)$")
    state: PositionSizeProposalState = PositionSizeProposalState.AWAITING_RISK
    confidence_basis: PositionSizingConfidenceBasis = PositionSizingConfidenceBasis.NOT_AVAILABLE
    reference_price: Decimal = Field(gt=Decimal("0"), lt=Decimal("1"), decimal_places=6)
    model_probability: Decimal = Field(ge=Decimal("0"), le=Decimal("1"), decimal_places=6)
    raw_edge: Decimal = Field(ge=Decimal("0"), le=Decimal("1"), decimal_places=6)
    available_bankroll: PositiveMoney
    target_exposure_fraction: Fraction
    proposed_exposure_fraction: Decimal = Field(
        gt=Decimal("0"), lt=Decimal("0.10"), decimal_places=10
    )
    proposed_capital: PositiveMoney
    strategy_name: str = Field(min_length=1, max_length=50)
    strategy_version: str = Field(min_length=1, max_length=100)
    candidate_min_raw_edge: Fraction
    strong_min_raw_edge: Fraction
    very_strong_min_raw_edge: Fraction
    candidate_exposure_fraction: Fraction
    strong_exposure_fraction: Fraction
    very_strong_exposure_fraction: Fraction
    max_exposure_fraction: Fraction
    policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    opportunity_strategy_name: str
    opportunity_strategy_version: str
    opportunity_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    opportunity_evaluated_at: datetime
    opportunity_valid_until: datetime
    proposed_at: datetime
    reason: str = Field(min_length=1, max_length=200)
    audit_snapshot: dict[str, JsonValue]

    @field_validator("opportunity_evaluated_at", "opportunity_valid_until", "proposed_at")
    @classmethod
    def datetimes_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("position-size proposal times must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_sizing_arithmetic(self) -> Self:
        if self.proposed_capital > self.available_bankroll:
            raise ValueError("proposed capital cannot exceed available bankroll")
        expected_exposure = (self.proposed_capital / self.available_bankroll).quantize(
            _EXPOSURE_QUANTUM,
            rounding=ROUND_DOWN,
        )
        if self.proposed_exposure_fraction != expected_exposure:
            raise ValueError("proposed exposure must reflect cent-rounded capital")
        if self.proposed_exposure_fraction > self.target_exposure_fraction:
            raise ValueError("actual exposure cannot exceed its target")
        if self.proposed_at > self.opportunity_valid_until:
            raise ValueError("position-size proposal cannot outlive its opportunity")
        return self


def floor_money(value: Decimal) -> Decimal:
    """Round a nonnegative capital proposal down to whole cents."""
    return value.quantize(_CENT, rounding=ROUND_DOWN)


def exposure_fraction(capital: Decimal, available_bankroll: Decimal) -> Decimal:
    """Return actual exposure after conservative money rounding."""
    return (capital / available_bankroll).quantize(_EXPOSURE_QUANTUM, rounding=ROUND_DOWN)
