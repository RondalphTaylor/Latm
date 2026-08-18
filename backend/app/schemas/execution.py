from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter

from app.domain.execution import (
    PaperExecutionCheck,
    PaperMarkBasis,
    PaperPositionStatus,
    PaperTradeStatus,
)
from app.models.execution import PaperPositionRecord, PaperTradeRecord
from app.schemas.portfolio import PortfolioSnapshotResponse
from app.services.execution.service import PaperExecutionResult

_CHECKS_ADAPTER = TypeAdapter(list[PaperExecutionCheck])
_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JsonValue])


class PaperTradeResponse(BaseModel):
    """Complete immutable paper entry attempt and its execution assumptions."""

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
    execution_mode: str
    action: str
    direction: str
    status: PaperTradeStatus
    reason_code: str
    reason: str
    failed_rules: list[str]
    checks: list[PaperExecutionCheck]
    proposed_capital: Decimal
    reference_price: Decimal
    execution_price: Decimal | None
    slippage_bps: Decimal
    slippage_amount_per_contract: Decimal | None
    requested_quantity: int | None
    executed_quantity: int | None
    reference_gross_cost: Decimal | None
    gross_cost: Decimal | None
    slippage_cost: Decimal | None
    fee_bps: Decimal
    fee_amount: Decimal | None
    total_cost: Decimal | None
    unused_capital: Decimal | None
    effective_unit_cost: Decimal | None
    model_probability: Decimal
    raw_edge: Decimal
    adjusted_edge: Decimal | None
    mark_price: Decimal | None
    mark_basis: PaperMarkBasis | None
    market_value: Decimal | None
    unrealized_pnl: Decimal | None
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

    @classmethod
    def from_record(cls, record: PaperTradeRecord) -> PaperTradeResponse:
        return cls(
            id=record.id,
            risk_decision_id=record.risk_decision_id,
            position_size_proposal_id=record.position_size_proposal_id,
            portfolio_id=record.portfolio_id,
            portfolio_snapshot_before_id=record.portfolio_snapshot_before_id,
            portfolio_snapshot_after_id=record.portfolio_snapshot_after_id,
            opportunity_id=record.opportunity_id,
            market_id=record.market_id,
            outcome_team_id=record.outcome_team_id,
            market_event_match_id=record.market_event_match_id,
            market_price_id=record.market_price_id,
            base_forecast_id=record.base_forecast_id,
            execution_mode=record.execution_mode,
            action=record.action,
            direction=record.direction,
            status=PaperTradeStatus(record.status),
            reason_code=record.reason_code,
            reason=record.reason,
            failed_rules=record.failed_rules,
            checks=_CHECKS_ADAPTER.validate_python(record.check_results),
            proposed_capital=record.proposed_capital,
            reference_price=record.reference_price,
            execution_price=record.execution_price,
            slippage_bps=record.slippage_bps,
            slippage_amount_per_contract=record.slippage_amount_per_contract,
            requested_quantity=record.requested_quantity,
            executed_quantity=record.executed_quantity,
            reference_gross_cost=record.reference_gross_cost,
            gross_cost=record.gross_cost,
            slippage_cost=record.slippage_cost,
            fee_bps=record.fee_bps,
            fee_amount=record.fee_amount,
            total_cost=record.total_cost,
            unused_capital=record.unused_capital,
            effective_unit_cost=record.effective_unit_cost,
            model_probability=record.model_probability,
            raw_edge=record.raw_edge,
            adjusted_edge=record.adjusted_edge,
            mark_price=record.mark_price,
            mark_basis=PaperMarkBasis(record.mark_basis) if record.mark_basis else None,
            market_value=record.market_value,
            unrealized_pnl=record.unrealized_pnl,
            sizing_strategy_version=record.sizing_strategy_version,
            risk_policy_version=record.risk_policy_version,
            execution_policy_name=record.execution_policy_name,
            execution_policy_version=record.execution_policy_version,
            execution_policy_fingerprint=record.execution_policy_fingerprint,
            risk_input_fingerprint=record.risk_input_fingerprint,
            input_fingerprint=record.input_fingerprint,
            attempted_at=record.attempted_at,
            executed_at=record.executed_at,
            audit_snapshot=_JSON_OBJECT_ADAPTER.validate_python(record.audit_snapshot),
        )


class PaperPositionResponse(BaseModel):
    """Entry-only open paper position with mark-to-market P&L."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    opening_trade_id: UUID
    portfolio_id: UUID
    market_id: UUID
    outcome_team_id: UUID
    market_price_id: UUID
    execution_mode: str
    direction: str
    status: PaperPositionStatus
    quantity: int
    average_entry_price: Decimal
    gross_cost_basis: Decimal
    entry_fees: Decimal
    total_cost_basis: Decimal
    mark_price: Decimal
    mark_basis: PaperMarkBasis
    market_value: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    input_fingerprint: str
    opened_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: PaperPositionRecord) -> PaperPositionResponse:
        return cls(
            id=record.id,
            opening_trade_id=record.opening_trade_id,
            portfolio_id=record.portfolio_id,
            market_id=record.market_id,
            outcome_team_id=record.outcome_team_id,
            market_price_id=record.market_price_id,
            execution_mode=record.execution_mode,
            direction=record.direction,
            status=PaperPositionStatus(record.status),
            quantity=record.quantity,
            average_entry_price=record.average_entry_price,
            gross_cost_basis=record.gross_cost_basis,
            entry_fees=record.entry_fees,
            total_cost_basis=record.total_cost_basis,
            mark_price=record.mark_price,
            mark_basis=PaperMarkBasis(record.mark_basis),
            market_value=record.market_value,
            unrealized_pnl=record.unrealized_pnl,
            realized_pnl=record.realized_pnl,
            input_fingerprint=record.input_fingerprint,
            opened_at=record.opened_at,
            updated_at=record.updated_at,
        )


class PaperExecutionResponse(BaseModel):
    """Terminal execution attempt plus any atomic financial effects."""

    model_config = ConfigDict(frozen=True)

    created: bool
    trade: PaperTradeResponse
    position: PaperPositionResponse | None
    portfolio_snapshot: PortfolioSnapshotResponse | None

    @classmethod
    def from_result(cls, result: PaperExecutionResult) -> PaperExecutionResponse:
        return cls(
            created=result.created,
            trade=PaperTradeResponse.from_record(result.trade),
            position=(
                PaperPositionResponse.from_record(result.position)
                if result.position is not None
                else None
            ),
            portfolio_snapshot=(
                PortfolioSnapshotResponse.from_record(result.snapshot)
                if result.snapshot is not None
                else None
            ),
        )
