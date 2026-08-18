from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

Money = Annotated[Decimal, Field(ge=Decimal("0"), max_digits=18, decimal_places=2)]
SignedMoney = Annotated[Decimal, Field(max_digits=18, decimal_places=2)]
ContractPrice = Annotated[
    Decimal,
    Field(ge=Decimal("0"), lt=Decimal("1"), decimal_places=6),
]
BasisPoints = Annotated[
    Decimal,
    Field(ge=Decimal("0"), le=Decimal("10000"), decimal_places=2),
]


class PaperTradeStatus(StrEnum):
    """Terminal entry-attempt states supported by Phase 8."""

    FILLED = "filled"
    REJECTED = "rejected"


class PaperPositionStatus(StrEnum):
    """Current paper-position projection states."""

    OPEN = "open"
    CLOSED = "closed"
    SETTLED = "settled"


class PaperMarkBasis(StrEnum):
    """How a paper position was marked."""

    DIRECTIONAL_BID = "directional_bid"
    DIRECTIONAL_ASK_FALLBACK = "directional_ask_fallback"
    EXIT_EXECUTION = "exit_execution"
    SETTLEMENT_PAYOUT = "settlement_payout"


class PaperExecutionPolicy(BaseModel):
    """Versioned immediate-fill assumptions for paper entries."""

    model_config = ConfigDict(frozen=True)

    strategy_name: str = "paper_immediate_fill"
    code_version: str = "1.0.0"
    formula_version: str = "direct_ask_additive_slippage_integer_quantity_fee_v1"
    slippage_bps: BasisPoints = Decimal("25.00")
    fee_bps: BasisPoints = Decimal("10.00")


class PaperExecutionCheck(BaseModel):
    """One ordered, auditable execution-gate result."""

    model_config = ConfigDict(frozen=True)

    rule: str = Field(min_length=1, max_length=100)
    passed: bool
    actual: JsonValue
    expected: JsonValue
    detail: str = Field(min_length=1, max_length=300)


class PaperExecutionInput(BaseModel):
    """Exact authorization, current state, and prices observed at entry time."""

    model_config = ConfigDict(frozen=True)

    risk_decision_id: UUID
    position_size_proposal_id: UUID
    portfolio_id: UUID
    portfolio_snapshot_id: UUID
    opportunity_id: UUID
    market_id: UUID
    outcome_team_id: UUID
    market_event_match_id: UUID
    market_price_id: UUID
    base_forecast_id: UUID
    direction: str = Field(pattern=r"^(yes|no)$")
    runtime_trading_mode: str
    risk_execution_mode: str
    risk_decision: str
    risk_all_required_checks_passed: bool
    risk_is_latest: bool
    risk_policy_is_active: bool
    risk_revalidation_decision: str
    risk_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    revalidated_risk_input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    authorization_valid_until: datetime | None
    no_prior_execution: bool
    no_open_market_position: bool
    latest_snapshot_id: UUID
    current_available_bankroll: Money
    proposed_capital: Money
    reference_price: ContractPrice
    current_directional_ask: Decimal | None
    current_directional_bid: Decimal | None
    model_probability: Decimal = Field(ge=Decimal("0"), le=Decimal("1"), decimal_places=6)
    raw_edge: Decimal = Field(ge=Decimal("-1"), le=Decimal("1"), decimal_places=6)
    minimum_adjusted_edge: Decimal = Field(ge=Decimal("0"), le=Decimal("1"), decimal_places=6)
    attempted_at: datetime

    @field_validator("authorization_valid_until", "attempted_at")
    @classmethod
    def times_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("paper execution times must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_probability_arithmetic(self) -> Self:
        if self.raw_edge != self.model_probability - self.reference_price:
            raise ValueError("paper execution raw edge must reproduce from proposal prices")
        return self


class PaperExecutionDecision(BaseModel):
    """Terminal simulated entry decision; only FILLED carries financial effects."""

    model_config = ConfigDict(frozen=True)

    status: PaperTradeStatus
    reason_code: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=500)
    checks: tuple[PaperExecutionCheck, ...] = Field(min_length=1)
    failed_rules: tuple[str, ...]
    requested_capital: Money
    reference_price: ContractPrice
    execution_price: Decimal | None = Field(default=None, ge=Decimal("0"), lt=Decimal("1"))
    slippage_amount_per_contract: Decimal | None = Field(default=None, ge=Decimal("0"))
    requested_quantity: int | None = Field(default=None, ge=1)
    executed_quantity: int | None = Field(default=None, ge=1)
    reference_gross_cost: Money | None = None
    gross_cost: Money | None = None
    slippage_cost: Money | None = None
    fee_amount: Money | None = None
    total_cost: Money | None = None
    unused_capital: Money | None = None
    effective_unit_cost: Decimal | None = Field(default=None, ge=Decimal("0"))
    adjusted_edge: Decimal | None = None
    mark_price: Decimal | None = Field(default=None, ge=Decimal("0"), lt=Decimal("1"))
    mark_basis: PaperMarkBasis | None = None
    market_value: Money | None = None
    unrealized_pnl: SignedMoney | None = None
    execution_policy_name: str
    execution_policy_version: str
    execution_policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    attempted_at: datetime
    audit_snapshot: dict[str, JsonValue]

    @field_validator("attempted_at")
    @classmethod
    def attempted_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("paper execution attempt time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_terminal_state(self) -> Self:
        economics = (
            self.execution_price,
            self.slippage_amount_per_contract,
            self.requested_quantity,
            self.executed_quantity,
            self.reference_gross_cost,
            self.gross_cost,
            self.slippage_cost,
            self.fee_amount,
            self.total_cost,
            self.unused_capital,
            self.effective_unit_cost,
            self.adjusted_edge,
            self.mark_price,
            self.mark_basis,
            self.market_value,
            self.unrealized_pnl,
        )
        if self.status is PaperTradeStatus.FILLED:
            if self.failed_rules or any(value is None for value in economics):
                raise ValueError(
                    "filled paper execution requires complete economics and no failures"
                )
            if self.total_cost is not None and self.total_cost > self.requested_capital:
                raise ValueError("paper execution total cost cannot exceed authorized capital")
        elif not self.failed_rules or any(value is not None for value in economics):
            raise ValueError("rejected paper execution requires failures and no fill economics")
        return self


class PaperTrade(BaseModel):
    """Immutable persisted paper entry attempt."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    risk_decision_id: UUID
    position_size_proposal_id: UUID
    portfolio_id: UUID
    portfolio_snapshot_before_id: UUID
    portfolio_snapshot_after_id: UUID | None
    opportunity_id: UUID
    market_id: UUID
    outcome_team_id: UUID
    market_event_match_id: UUID
    market_price_id: UUID
    base_forecast_id: UUID
    execution_mode: str = Field(pattern=r"^paper$")
    action: str = Field(default="buy", pattern=r"^buy$")
    direction: str = Field(pattern=r"^(yes|no)$")
    status: PaperTradeStatus
    reason_code: str
    reason: str
    failed_rules: tuple[str, ...]
    checks: tuple[PaperExecutionCheck, ...]
    proposed_capital: Money
    reference_price: ContractPrice
    execution_price: Decimal | None
    slippage_bps: BasisPoints
    slippage_amount_per_contract: Decimal | None
    requested_quantity: int | None
    executed_quantity: int | None
    reference_gross_cost: Money | None
    gross_cost: Money | None
    slippage_cost: Money | None
    fee_bps: BasisPoints
    fee_amount: Money | None
    total_cost: Money | None
    unused_capital: Money | None
    effective_unit_cost: Decimal | None
    model_probability: Decimal
    raw_edge: Decimal
    adjusted_edge: Decimal | None
    mark_price: Decimal | None
    mark_basis: PaperMarkBasis | None
    market_value: Money | None
    unrealized_pnl: SignedMoney | None
    sizing_strategy_version: str
    risk_policy_version: str
    execution_policy_name: str
    execution_policy_version: str
    execution_policy_fingerprint: str
    risk_input_fingerprint: str
    input_fingerprint: str
    attempted_at: datetime
    executed_at: datetime | None
    audit_snapshot: dict[str, JsonValue]

    @field_validator("attempted_at", "executed_at")
    @classmethod
    def trade_times_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("paper trade times must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_persisted_terminal_state(self) -> Self:
        economics = (
            self.execution_price,
            self.slippage_amount_per_contract,
            self.requested_quantity,
            self.executed_quantity,
            self.reference_gross_cost,
            self.gross_cost,
            self.slippage_cost,
            self.fee_amount,
            self.total_cost,
            self.unused_capital,
            self.effective_unit_cost,
            self.adjusted_edge,
            self.mark_price,
            self.mark_basis,
            self.market_value,
            self.unrealized_pnl,
        )
        if self.status is PaperTradeStatus.FILLED:
            if (
                self.portfolio_snapshot_after_id is None
                or self.executed_at is None
                or self.failed_rules
                or any(value is None for value in economics)
            ):
                raise ValueError("filled trade requires complete financial effects")
            if (
                self.gross_cost is not None
                and self.fee_amount is not None
                and self.total_cost != self.gross_cost + self.fee_amount
            ):
                raise ValueError("trade total cost must equal gross cost plus fee")
            if self.total_cost is not None and self.total_cost > self.proposed_capital:
                raise ValueError("trade total cost cannot exceed proposed capital")
        elif (
            self.portfolio_snapshot_after_id is not None
            or self.executed_at is not None
            or not self.failed_rules
            or any(value is not None for value in economics)
        ):
            raise ValueError("rejected trade cannot contain financial effects")
        return self


class PaperPosition(BaseModel):
    """Current projection reproducible from an opening trade and immutable events."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    opening_trade_id: UUID
    portfolio_id: UUID
    market_id: UUID
    outcome_team_id: UUID
    market_price_id: UUID
    execution_mode: str = Field(pattern=r"^paper$")
    direction: str = Field(pattern=r"^(yes|no)$")
    status: PaperPositionStatus = PaperPositionStatus.OPEN
    initial_quantity: int | None = Field(default=None, ge=1)
    disposed_quantity: int = Field(default=0, ge=0)
    version: int = Field(default=0, ge=0)
    quantity: int = Field(ge=0)
    average_entry_price: Decimal = Field(gt=Decimal("0"), lt=Decimal("1"))
    gross_cost_basis: Money
    entry_fees: Money
    total_cost_basis: Money
    mark_price: ContractPrice
    mark_basis: PaperMarkBasis
    market_value: Money
    unrealized_pnl: SignedMoney
    realized_pnl: SignedMoney = Decimal("0.00")
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    projection_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    latest_base_forecast_id: UUID | None = None
    market_resolution_id: UUID | None = None
    opened_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None
    settled_at: datetime | None = None

    @field_validator("opened_at", "updated_at", "closed_at", "settled_at")
    @classmethod
    def position_times_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("paper position times must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_position_accounting(self) -> Self:
        initial_quantity = self.initial_quantity or self.quantity
        if initial_quantity != self.quantity + self.disposed_quantity:
            raise ValueError("initial quantity must equal remaining plus disposed quantity")
        if self.total_cost_basis != self.gross_cost_basis + self.entry_fees:
            raise ValueError("position cost basis must include entry fees")
        if self.unrealized_pnl != self.market_value - self.total_cost_basis:
            raise ValueError("position unrealized P&L must reproduce from mark and cost basis")
        if self.status is PaperPositionStatus.OPEN:
            if self.quantity < 1 or self.closed_at is not None or self.settled_at is not None:
                raise ValueError("open positions require remaining quantity and no terminal time")
        elif (
            self.quantity != 0
            or self.gross_cost_basis != 0
            or self.entry_fees != 0
            or self.total_cost_basis != 0
            or self.market_value != 0
            or self.unrealized_pnl != 0
        ):
            raise ValueError("terminal positions cannot retain quantity, basis, or open value")
        if self.status is PaperPositionStatus.CLOSED and (
            self.closed_at is None or self.settled_at is not None
        ):
            raise ValueError("closed positions require only a close time")
        if self.status is PaperPositionStatus.SETTLED and (
            self.settled_at is None or self.market_resolution_id is None
        ):
            raise ValueError("settled positions require official resolution provenance")
        if self.updated_at < self.opened_at:
            raise ValueError("position update time cannot precede its opening time")
        return self
