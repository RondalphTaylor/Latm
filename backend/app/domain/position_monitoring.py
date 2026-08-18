from __future__ import annotations

from datetime import datetime
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

Money = Annotated[Decimal, Field(ge=Decimal("0"), max_digits=18, decimal_places=2)]
SignedMoney = Annotated[Decimal, Field(max_digits=18, decimal_places=2)]
Probability = Annotated[
    Decimal,
    Field(ge=Decimal("0"), le=Decimal("1"), decimal_places=6),
]
ContractPrice = Annotated[
    Decimal,
    Field(ge=Decimal("0"), le=Decimal("1"), decimal_places=6),
]
BasisPoints = Annotated[
    Decimal,
    Field(ge=Decimal("0"), le=Decimal("10000"), decimal_places=2),
]

_CENT = Decimal("0.01")


def floor_money(value: Decimal) -> Decimal:
    """Floor a nonnegative accounting value to the portfolio's cent precision."""
    return value.quantize(_CENT, rounding=ROUND_DOWN)


def cumulative_basis_allocation(
    *, original_amount: Decimal, disposed_quantity: int, initial_quantity: int
) -> Decimal:
    """Return path-independent cumulative cent allocation for disposed contracts."""
    if initial_quantity < 1:
        raise ValueError("initial quantity must be positive")
    if disposed_quantity < 0 or disposed_quantity > initial_quantity:
        raise ValueError("disposed quantity must remain within the initial quantity")
    if disposed_quantity == 0:
        return Decimal("0.00")
    if disposed_quantity == initial_quantity:
        return original_amount
    return floor_money(original_amount * disposed_quantity / initial_quantity)


class PositionMonitoringAction(StrEnum):
    """Deterministic actions supported by the first monitoring policy."""

    HOLD = "hold"
    REDUCE = "reduce"
    CLOSE = "close"
    SETTLE = "settle"


class MonitoredPositionStatus(StrEnum):
    """Position projection states relevant to Phase 9."""

    OPEN = "open"
    CLOSED = "closed"
    SETTLED = "settled"


class PositionMonitoringPolicy(BaseModel):
    """Versioned deterministic monitoring, exit, and freshness assumptions."""

    model_config = ConfigDict(frozen=True)

    strategy_name: str = "position_monitoring"
    code_version: str = "1.0.0"
    formula_version: str = "hold_reduce_close_settle_cost_basis_v1"
    min_hold_edge: Probability = Decimal("0.030000")
    reduce_fraction: Decimal = Field(
        default=Decimal("0.500000"),
        gt=Decimal("0"),
        lt=Decimal("1"),
        decimal_places=6,
    )
    exit_slippage_bps: BasisPoints = Decimal("25.00")
    exit_fee_bps: BasisPoints = Decimal("10.00")
    max_market_price_age_seconds: int = Field(default=900, ge=1, le=86400)
    max_forecast_age_seconds: int = Field(default=86400, ge=1, le=604800)


class PositionAccountingState(BaseModel):
    """One exact current or resulting position projection."""

    model_config = ConfigDict(frozen=True)

    status: MonitoredPositionStatus
    initial_quantity: int = Field(ge=1)
    disposed_quantity: int = Field(ge=0)
    remaining_quantity: int = Field(ge=0)
    original_gross_cost_basis: Money
    original_entry_fees: Money
    original_total_cost_basis: Money
    remaining_gross_cost_basis: Money
    remaining_entry_fees: Money
    remaining_total_cost_basis: Money
    mark_price: Probability
    mark_basis: str = Field(min_length=1, max_length=50)
    market_value: Money
    unrealized_pnl: SignedMoney
    realized_pnl: SignedMoney

    @model_validator(mode="after")
    def validate_accounting(self) -> Self:
        if self.disposed_quantity + self.remaining_quantity != self.initial_quantity:
            raise ValueError("disposed and remaining quantities must equal initial quantity")
        if self.original_total_cost_basis != (
            self.original_gross_cost_basis + self.original_entry_fees
        ):
            raise ValueError("original total cost basis must include original entry fees")
        if self.remaining_total_cost_basis != (
            self.remaining_gross_cost_basis + self.remaining_entry_fees
        ):
            raise ValueError("remaining total cost basis must include remaining entry fees")
        expected_remaining_gross = self.original_gross_cost_basis - cumulative_basis_allocation(
            original_amount=self.original_gross_cost_basis,
            disposed_quantity=self.disposed_quantity,
            initial_quantity=self.initial_quantity,
        )
        expected_remaining_fees = self.original_entry_fees - cumulative_basis_allocation(
            original_amount=self.original_entry_fees,
            disposed_quantity=self.disposed_quantity,
            initial_quantity=self.initial_quantity,
        )
        if self.remaining_gross_cost_basis != expected_remaining_gross:
            raise ValueError("remaining gross basis must follow cumulative allocation")
        if self.remaining_entry_fees != expected_remaining_fees:
            raise ValueError("remaining entry fees must follow cumulative allocation")
        if self.status is MonitoredPositionStatus.OPEN:
            if self.remaining_quantity < 1:
                raise ValueError("open positions require remaining quantity")
            if self.mark_price >= Decimal("1"):
                raise ValueError("open-position marks must remain below one")
            if self.unrealized_pnl != self.market_value - self.remaining_total_cost_basis:
                raise ValueError("open-position unrealized P&L must reproduce from cost basis")
        elif (
            self.remaining_quantity != 0
            or self.remaining_gross_cost_basis != 0
            or self.remaining_entry_fees != 0
            or self.remaining_total_cost_basis != 0
            or self.market_value != 0
            or self.unrealized_pnl != 0
        ):
            raise ValueError("terminal positions require zero remaining financial state")
        return self


class PositionMonitoringInput(BaseModel):
    """Exact position and authoritative evidence observed for one evaluation."""

    model_config = ConfigDict(frozen=True)

    position_id: UUID
    portfolio_id: UUID
    portfolio_snapshot_id: UUID
    market_id: UUID
    outcome_team_id: UUID
    direction: str = Field(pattern=r"^(yes|no)$")
    runtime_trading_mode: str
    position_execution_mode: str
    position: PositionAccountingState
    market_event_match_id: UUID | None
    market_status: str
    event_status: str
    event_postponed: bool
    event_start_time: datetime
    event_semantics_are_current: bool
    market_price_id: UUID | None
    market_price_is_current: bool
    market_price_retrieved_at: datetime | None
    yes_bid: Decimal | None = Field(default=None, ge=Decimal("0"), lt=Decimal("1"))
    no_bid: Decimal | None = Field(default=None, ge=Decimal("0"), lt=Decimal("1"))
    forecast_id: UUID | None
    forecast_is_current: bool
    forecast_generated_at: datetime | None
    model_probability: Probability | None
    official_resolution_id: UUID | None = None
    official_resolution_is_final: bool = False
    official_held_side_payout: Probability | None = None
    evaluated_at: datetime

    @field_validator(
        "event_start_time",
        "market_price_retrieved_at",
        "forecast_generated_at",
        "evaluated_at",
    )
    @classmethod
    def times_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("position-monitoring times must be timezone-aware")
        return value


class PositionMonitoringCheck(BaseModel):
    """One ordered monitoring or accounting gate result."""

    model_config = ConfigDict(frozen=True)

    rule: str = Field(min_length=1, max_length=100)
    passed: bool
    actual: JsonValue
    expected: JsonValue
    detail: str = Field(min_length=1, max_length=300)


class PositionDispositionEconomics(BaseModel):
    """Exact sale or settlement economics for quantity leaving the position."""

    model_config = ConfigDict(frozen=True)

    disposed_quantity: int = Field(ge=1)
    reference_price: Probability
    execution_price: Probability
    reference_gross_proceeds: Money
    gross_proceeds: Money
    slippage_cost: Money
    exit_fee: Money
    net_proceeds: Money
    allocated_gross_cost_basis: Money
    allocated_entry_fees: Money
    allocated_total_cost_basis: Money
    realized_pnl_increment: SignedMoney

    @model_validator(mode="after")
    def validate_economics(self) -> Self:
        if self.reference_gross_proceeds != self.gross_proceeds + self.slippage_cost:
            raise ValueError("reference proceeds must reconcile gross proceeds and slippage")
        if self.net_proceeds != self.gross_proceeds - self.exit_fee:
            raise ValueError("net proceeds must subtract exit fees")
        if self.allocated_total_cost_basis != (
            self.allocated_gross_cost_basis + self.allocated_entry_fees
        ):
            raise ValueError("allocated total basis must include allocated entry fees")
        if self.realized_pnl_increment != (self.net_proceeds - self.allocated_total_cost_basis):
            raise ValueError("realized P&L must reproduce from net proceeds and cost basis")
        return self


class PositionPortfolioDelta(BaseModel):
    """Accounting deltas an application service applies to the locked portfolio."""

    model_config = ConfigDict(frozen=True)

    current_bankroll: SignedMoney
    cash_balance: SignedMoney
    reserved_capital: SignedMoney
    committed_capital: SignedMoney
    available_bankroll: SignedMoney
    realized_pnl: SignedMoney
    open_position_value: SignedMoney
    unrealized_pnl: SignedMoney
    total_portfolio_value: SignedMoney

    @model_validator(mode="after")
    def validate_delta_equations(self) -> Self:
        if self.current_bankroll != self.realized_pnl:
            raise ValueError("current-bankroll delta must equal realized-P&L delta")
        if self.available_bankroll != self.cash_balance - self.reserved_capital:
            raise ValueError("available-bankroll delta must follow cash and reservation deltas")
        if self.open_position_value != self.committed_capital + self.unrealized_pnl:
            raise ValueError("open-value delta must follow committed and unrealized deltas")
        if self.total_portfolio_value != self.cash_balance + self.open_position_value:
            raise ValueError("total-value delta must follow cash and open-value deltas")
        return self


class PositionMonitoringDecision(BaseModel):
    """Pure deterministic monitoring output ready for atomic application."""

    model_config = ConfigDict(frozen=True)

    position_id: UUID
    portfolio_id: UUID
    portfolio_snapshot_id: UUID
    market_id: UUID
    outcome_team_id: UUID
    market_event_match_id: UUID | None
    market_price_id: UUID | None
    forecast_id: UUID | None
    official_resolution_id: UUID | None
    direction: str = Field(pattern=r"^(yes|no)$")
    action: PositionMonitoringAction
    reason_code: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=500)
    checks: tuple[PositionMonitoringCheck, ...] = Field(min_length=1)
    hold_edge: Decimal | None = Field(default=None, ge=Decimal("-1"), le=Decimal("1"))
    before: PositionAccountingState
    after: PositionAccountingState
    economics: PositionDispositionEconomics | None
    portfolio_delta: PositionPortfolioDelta
    policy_name: str
    policy_version: str
    policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluated_at: datetime
    audit_snapshot: dict[str, JsonValue]

    @field_validator("evaluated_at")
    @classmethod
    def evaluated_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("position-monitoring decision time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_action_state(self) -> Self:
        if self.before.status is not MonitoredPositionStatus.OPEN:
            raise ValueError("monitoring decisions require an open before-state")
        if self.action is PositionMonitoringAction.HOLD:
            if self.economics is not None:
                raise ValueError("hold decisions cannot contain disposition economics")
            if (
                self.after.status is not MonitoredPositionStatus.OPEN
                or self.after.remaining_quantity != self.before.remaining_quantity
                or self.after.remaining_total_cost_basis != self.before.remaining_total_cost_basis
                or self.after.realized_pnl != self.before.realized_pnl
            ):
                raise ValueError("hold decisions cannot dispose quantity or cost basis")
        else:
            if self.economics is None:
                raise ValueError("disposition decisions require execution economics")
            if self.action is PositionMonitoringAction.REDUCE:
                if (
                    self.after.status is not MonitoredPositionStatus.OPEN
                    or self.after.remaining_quantity >= self.before.remaining_quantity
                ):
                    raise ValueError("reductions must leave a smaller open position")
            elif self.action is PositionMonitoringAction.CLOSE:
                if self.after.status is not MonitoredPositionStatus.CLOSED:
                    raise ValueError("close decisions require a closed after-state")
            elif self.after.status is not MonitoredPositionStatus.SETTLED:
                raise ValueError("settlement decisions require a settled after-state")
        return self
