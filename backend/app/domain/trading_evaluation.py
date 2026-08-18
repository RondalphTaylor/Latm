from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Money = Annotated[Decimal, Field(ge=Decimal("0"), max_digits=18, decimal_places=2)]
PositiveMoney = Annotated[Decimal, Field(gt=Decimal("0"), max_digits=18, decimal_places=2)]
SignedMoney = Annotated[Decimal, Field(max_digits=18, decimal_places=2)]
SignedEdge = Annotated[
    Decimal,
    Field(ge=Decimal("-1"), le=Decimal("1"), max_digits=12, decimal_places=10),
]
Fingerprint = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class TradingPositionStatus(StrEnum):
    """Position states used by paper-trading performance evaluation."""

    OPEN = "open"
    CLOSED = "closed"
    SETTLED = "settled"


class TradingEvaluationPolicy(BaseModel):
    """Immutable formula and precision identity for pure performance evaluation."""

    model_config = ConfigDict(frozen=True)

    evaluation_name: str = Field(default="paper_trading_performance", min_length=1, max_length=50)
    code_version: str = Field(default="1.0.0", min_length=1, max_length=50)
    formula_version: str = Field(
        default="snapshot_equity_completed_position_v1",
        pattern=r"^snapshot_equity_completed_position_v1$",
    )
    ratio_decimal_places: int = Field(default=10, ge=6, le=18)


class EntryLineage(BaseModel):
    """Exact immutable model and entry-strategy lineage for one filled position."""

    model_config = ConfigDict(frozen=True)

    model_version_id: UUID
    model_name: str = Field(min_length=1, max_length=50)
    model_version: str = Field(min_length=1, max_length=100)
    model_configuration_fingerprint: Fingerprint
    opportunity_strategy_name: str = Field(min_length=1, max_length=50)
    opportunity_strategy_version: str = Field(min_length=1, max_length=100)
    opportunity_policy_fingerprint: Fingerprint
    sizing_strategy_name: str = Field(min_length=1, max_length=50)
    sizing_strategy_version: str = Field(min_length=1, max_length=100)
    sizing_policy_fingerprint: Fingerprint
    risk_policy_name: str = Field(min_length=1, max_length=50)
    risk_policy_version: str = Field(min_length=1, max_length=100)
    risk_policy_fingerprint: Fingerprint
    execution_policy_name: str = Field(min_length=1, max_length=50)
    execution_policy_version: str = Field(min_length=1, max_length=100)
    execution_policy_fingerprint: Fingerprint
    market_type: str = Field(min_length=1, max_length=50)


class TradingEvaluationSnapshot(BaseModel):
    """One authoritative immutable portfolio-equity observation."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    portfolio_id: UUID
    sequence: int = Field(ge=0)
    previous_snapshot_id: UUID | None
    execution_mode: Literal["paper"] = "paper"
    currency: Literal["USD"] = "USD"
    starting_bankroll: PositiveMoney
    realized_pnl: SignedMoney
    unrealized_pnl: SignedMoney
    total_portfolio_value: Money
    state_fingerprint: Fingerprint
    captured_at: datetime
    includes_non_executable_mark: bool = False

    @field_validator("captured_at")
    @classmethod
    def captured_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluation snapshot time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_equity_identity(self) -> Self:
        if self.total_portfolio_value != (
            self.starting_bankroll + self.realized_pnl + self.unrealized_pnl
        ):
            raise ValueError(
                "snapshot total value must equal starting bankroll plus realized and unrealized P&L"
            )
        return self


class PositionPerformanceFact(BaseModel):
    """One filled entry and its current or terminal position-level accounting result."""

    model_config = ConfigDict(frozen=True)

    position_id: UUID
    opening_trade_id: UUID
    portfolio_id: UUID
    status: TradingPositionStatus
    original_total_cost_basis: PositiveMoney
    realized_pnl: SignedMoney
    unrealized_pnl: SignedMoney
    raw_entry_edge: SignedEdge
    adjusted_entry_edge: SignedEdge
    executed_at: datetime
    terminal_at: datetime | None = None
    lineage: EntryLineage

    @field_validator("executed_at", "terminal_at")
    @classmethod
    def times_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("position performance times must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        if self.status is TradingPositionStatus.OPEN:
            if self.terminal_at is not None:
                raise ValueError("open performance facts cannot have a terminal time")
        else:
            if self.terminal_at is None:
                raise ValueError("completed performance facts require a terminal time")
            if self.terminal_at < self.executed_at:
                raise ValueError("position terminal time cannot precede execution")
            if self.unrealized_pnl != 0:
                raise ValueError("completed performance facts cannot retain unrealized P&L")
        return self


class TradingEvaluationInput(BaseModel):
    """Complete reconciled paper ledger inputs for one pure evaluation."""

    model_config = ConfigDict(frozen=True)

    portfolio_id: UUID
    execution_mode: Literal["paper"] = "paper"
    currency: Literal["USD"] = "USD"
    snapshots: tuple[TradingEvaluationSnapshot, ...] = Field(min_length=1)
    positions: tuple[PositionPerformanceFact, ...] = ()
    evaluated_at: datetime

    @field_validator("evaluated_at")
    @classmethod
    def evaluated_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("trading evaluation time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_complete_reconciled_source(self) -> Self:
        ordered = sorted(self.snapshots, key=lambda item: item.sequence)
        if len({item.id for item in ordered}) != len(ordered):
            raise ValueError("evaluation snapshot IDs must be unique")
        starting_bankroll = ordered[0].starting_bankroll
        previous: TradingEvaluationSnapshot | None = None
        for expected_sequence, snapshot in enumerate(ordered):
            if snapshot.portfolio_id != self.portfolio_id:
                raise ValueError("evaluation snapshots must belong to the requested portfolio")
            if snapshot.sequence != expected_sequence:
                raise ValueError("evaluation snapshots must form a contiguous sequence from zero")
            if snapshot.starting_bankroll != starting_bankroll:
                raise ValueError("starting bankroll cannot change across the snapshot chain")
            if snapshot.captured_at > self.evaluated_at:
                raise ValueError("evaluation snapshots cannot postdate evaluation")
            if previous is None:
                if snapshot.previous_snapshot_id is not None:
                    raise ValueError("sequence-zero snapshot cannot have a predecessor")
            else:
                if snapshot.previous_snapshot_id != previous.id:
                    raise ValueError("evaluation snapshot predecessor chain is broken")
                if snapshot.captured_at < previous.captured_at:
                    raise ValueError("snapshot capture times cannot decrease with sequence")
            previous = snapshot

        position_ids: set[UUID] = set()
        opening_trade_ids: set[UUID] = set()
        for position in self.positions:
            if position.portfolio_id != self.portfolio_id:
                raise ValueError("position facts must belong to the requested portfolio")
            if (
                position.position_id in position_ids
                or position.opening_trade_id in opening_trade_ids
            ):
                raise ValueError("each filled position and opening trade may appear only once")
            if position.executed_at > self.evaluated_at:
                raise ValueError("position entries cannot postdate evaluation")
            if position.terminal_at is not None and position.terminal_at > self.evaluated_at:
                raise ValueError("position terminal times cannot postdate evaluation")
            position_ids.add(position.position_id)
            opening_trade_ids.add(position.opening_trade_id)

        head = ordered[-1]
        if head.realized_pnl != sum(
            (item.realized_pnl for item in self.positions),
            start=Decimal("0.00"),
        ):
            raise ValueError("position realized P&L does not reconcile to the ledger head")
        if head.unrealized_pnl != sum(
            (item.unrealized_pnl for item in self.positions),
            start=Decimal("0.00"),
        ):
            raise ValueError("position unrealized P&L does not reconcile to the ledger head")
        return self


class SnapshotDrawdown(BaseModel):
    """Largest sequence-observed peak-to-trough decline in portfolio equity."""

    model_config = ConfigDict(frozen=True)

    amount: Money
    fraction: Decimal
    peak_snapshot_id: UUID
    trough_snapshot_id: UUID
    peak_value: Money
    trough_value: Money
    peak_at: datetime
    trough_at: datetime


class EntryLineagePerformance(BaseModel):
    """Metrics for positions assigned exactly once to one opening lineage."""

    model_config = ConfigDict(frozen=True)

    lineage: EntryLineage
    position_count: int = Field(ge=0)
    open_position_count: int = Field(ge=0)
    completed_position_count: int = Field(ge=0)
    winning_position_count: int = Field(ge=0)
    losing_position_count: int = Field(ge=0)
    breakeven_position_count: int = Field(ge=0)
    net_pnl: SignedMoney
    realized_pnl: SignedMoney
    unrealized_pnl: SignedMoney
    profitable: bool
    win_rate: Decimal | None
    average_raw_entry_edge: Decimal | None
    average_adjusted_entry_edge: Decimal | None
    average_terminal_return: Decimal | None
    aggregate_return_on_cost: Decimal | None
    completed_cost_basis: Money


class TradingPerformanceEvaluation(BaseModel):
    """Pure deterministic paper-trading performance result."""

    model_config = ConfigDict(frozen=True)

    portfolio_id: UUID
    execution_mode: Literal["paper"] = "paper"
    currency: Literal["USD"] = "USD"
    as_of_snapshot_id: UUID
    as_of_sequence: int = Field(ge=0)
    as_of: datetime
    calculated_at: datetime
    pnl_basis: Literal["snapshot_marked_equity"] = "snapshot_marked_equity"
    drawdown_basis: Literal["snapshot_sequence"] = "snapshot_sequence"
    starting_bankroll: PositiveMoney
    net_total_pnl: SignedMoney
    realized_pnl: SignedMoney
    unrealized_pnl: SignedMoney
    return_on_starting_bankroll: Decimal
    realized_return_on_starting_bankroll: Decimal
    unrealized_return_on_starting_bankroll: Decimal
    profitable: bool
    position_count: int = Field(ge=0)
    open_position_count: int = Field(ge=0)
    completed_position_count: int = Field(ge=0)
    winning_position_count: int = Field(ge=0)
    losing_position_count: int = Field(ge=0)
    breakeven_position_count: int = Field(ge=0)
    win_rate: Decimal | None
    average_raw_entry_edge: Decimal | None
    average_adjusted_entry_edge: Decimal | None
    average_terminal_return: Decimal | None
    aggregate_return_on_cost: Decimal | None
    completed_cost_basis: Money
    maximum_drawdown: SnapshotDrawdown
    entry_lineage_groups: tuple[EntryLineagePerformance, ...]
    evaluation_policy_name: str
    evaluation_policy_version: str
    evaluation_policy_fingerprint: Fingerprint
    input_fingerprint: Fingerprint
    warnings: tuple[str, ...]

    @field_validator("as_of", "calculated_at")
    @classmethod
    def result_times_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("trading performance result times must be timezone-aware")
        return value
