from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from app.domain.portfolio import (
    PortfolioMode,
    PortfolioSnapshotReason,
    PortfolioStatus,
    PositionSizeProposalState,
    PositionSizingConfidenceBasis,
)
from app.models.portfolio import (
    PortfolioSnapshotRecord,
    PositionSizeProposalRecord,
)
from app.services.position_sizing.repository import PortfolioBundle

_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JsonValue])


class PortfolioCreateRequest(BaseModel):
    """Idempotent paper-portfolio definition; no live mode is accepted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    idempotency_key: str = Field(
        default="primary-paper-portfolio",
        min_length=1,
        max_length=100,
    )
    name: str = Field(default="Primary Paper Portfolio", min_length=1, max_length=100)
    starting_bankroll: Decimal | None = Field(
        default=None,
        gt=Decimal("0"),
        max_digits=18,
        decimal_places=2,
    )


class PortfolioSnapshotResponse(BaseModel):
    """One immutable paper accounting snapshot."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    portfolio_id: UUID
    sequence: int
    execution_mode: PortfolioMode
    currency: str
    starting_bankroll: Decimal
    current_bankroll: Decimal
    cash_balance: Decimal
    reserved_capital: Decimal
    committed_capital: Decimal
    available_bankroll: Decimal
    realized_pnl: Decimal
    open_position_value: Decimal
    unrealized_pnl: Decimal
    total_portfolio_value: Decimal
    previous_snapshot_id: UUID | None
    reason: PortfolioSnapshotReason
    state_fingerprint: str
    captured_at: datetime

    @classmethod
    def from_record(cls, record: PortfolioSnapshotRecord) -> PortfolioSnapshotResponse:
        return cls(
            id=record.id,
            portfolio_id=record.portfolio_id,
            sequence=record.sequence,
            execution_mode=PortfolioMode(record.execution_mode),
            currency=record.currency,
            starting_bankroll=record.starting_bankroll,
            current_bankroll=record.current_bankroll,
            cash_balance=record.cash_balance,
            reserved_capital=record.reserved_capital,
            committed_capital=record.committed_capital,
            available_bankroll=record.available_bankroll,
            realized_pnl=record.realized_pnl,
            open_position_value=record.open_position_value,
            unrealized_pnl=record.unrealized_pnl,
            total_portfolio_value=record.total_portfolio_value,
            previous_snapshot_id=record.previous_snapshot_id,
            reason=PortfolioSnapshotReason(record.reason),
            state_fingerprint=record.state_fingerprint,
            captured_at=record.captured_at,
        )


class PortfolioResponse(BaseModel):
    """Paper portfolio identity and current authoritative balances."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    idempotency_key: str
    name: str
    execution_mode: PortfolioMode
    currency: str
    starting_bankroll: Decimal
    status: PortfolioStatus
    is_active: bool
    creation_fingerprint: str
    created_at: datetime
    latest_snapshot: PortfolioSnapshotResponse

    @classmethod
    def from_bundle(cls, bundle: PortfolioBundle) -> PortfolioResponse:
        record = bundle.portfolio
        return cls(
            id=record.id,
            idempotency_key=record.idempotency_key,
            name=record.name,
            execution_mode=PortfolioMode(record.execution_mode),
            currency=record.currency,
            starting_bankroll=record.starting_bankroll,
            status=PortfolioStatus(record.status),
            is_active=record.is_active,
            creation_fingerprint=record.creation_fingerprint,
            created_at=record.created_at,
            latest_snapshot=PortfolioSnapshotResponse.from_record(bundle.snapshot),
        )


class PortfolioCreateResponse(PortfolioResponse):
    """Portfolio plus whether this request created the immutable definition."""

    created: bool


class PositionSizingRunResponse(BaseModel):
    """Counts returned by one bounded current-candidate sizing run."""

    model_config = ConfigDict(frozen=True)

    portfolio_id: UUID
    portfolio_snapshot_id: UUID
    strategy_name: str
    strategy_version: str
    examined: int
    generated: int
    persisted: int
    invalidated_before_persist: int
    band_counts: dict[str, int]
    skip_counts: dict[str, int]


class PositionSizeProposalResponse(BaseModel):
    """Immutable advisory capital allocation awaiting future risk evaluation."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    portfolio_id: UUID
    portfolio_snapshot_id: UUID
    opportunity_id: UUID
    market_id: UUID
    outcome_team_id: UUID
    execution_mode: PortfolioMode
    direction: str
    state: PositionSizeProposalState
    confidence_basis: PositionSizingConfidenceBasis
    reference_price: Decimal
    model_probability: Decimal
    raw_edge: Decimal
    available_bankroll: Decimal
    target_exposure_fraction: Decimal
    proposed_exposure_fraction: Decimal
    proposed_capital: Decimal
    strategy_name: str
    strategy_version: str
    candidate_min_raw_edge: Decimal
    strong_min_raw_edge: Decimal
    very_strong_min_raw_edge: Decimal
    candidate_exposure_fraction: Decimal
    strong_exposure_fraction: Decimal
    very_strong_exposure_fraction: Decimal
    max_exposure_fraction: Decimal
    policy_fingerprint: str
    input_fingerprint: str
    opportunity_strategy_name: str
    opportunity_strategy_version: str
    opportunity_input_fingerprint: str
    opportunity_evaluated_at: datetime
    opportunity_valid_until: datetime
    proposed_at: datetime
    reason: str
    audit_snapshot: dict[str, JsonValue]

    @classmethod
    def from_record(cls, record: PositionSizeProposalRecord) -> PositionSizeProposalResponse:
        return cls(
            id=record.id,
            portfolio_id=record.portfolio_id,
            portfolio_snapshot_id=record.portfolio_snapshot_id,
            opportunity_id=record.opportunity_id,
            market_id=record.market_id,
            outcome_team_id=record.outcome_team_id,
            execution_mode=PortfolioMode(record.execution_mode),
            direction=record.direction,
            state=PositionSizeProposalState(record.state),
            confidence_basis=PositionSizingConfidenceBasis(record.confidence_basis),
            reference_price=record.reference_price,
            model_probability=record.model_probability,
            raw_edge=record.raw_edge,
            available_bankroll=record.available_bankroll,
            target_exposure_fraction=record.target_exposure_fraction,
            proposed_exposure_fraction=record.proposed_exposure_fraction,
            proposed_capital=record.proposed_capital,
            strategy_name=record.strategy_name,
            strategy_version=record.strategy_version,
            candidate_min_raw_edge=record.candidate_min_raw_edge,
            strong_min_raw_edge=record.strong_min_raw_edge,
            very_strong_min_raw_edge=record.very_strong_min_raw_edge,
            candidate_exposure_fraction=record.candidate_exposure_fraction,
            strong_exposure_fraction=record.strong_exposure_fraction,
            very_strong_exposure_fraction=record.very_strong_exposure_fraction,
            max_exposure_fraction=record.max_exposure_fraction,
            policy_fingerprint=record.policy_fingerprint,
            input_fingerprint=record.input_fingerprint,
            opportunity_strategy_name=record.opportunity_strategy_name,
            opportunity_strategy_version=record.opportunity_strategy_version,
            opportunity_input_fingerprint=record.opportunity_input_fingerprint,
            opportunity_evaluated_at=record.opportunity_evaluated_at,
            opportunity_valid_until=record.opportunity_valid_until,
            proposed_at=record.proposed_at,
            reason=record.reason,
            audit_snapshot=_JSON_OBJECT_ADAPTER.validate_python(record.audit_snapshot),
        )
