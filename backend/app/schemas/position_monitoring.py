from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter

from app.models.execution import PositionEventRecord
from app.schemas.execution import PaperPositionResponse
from app.schemas.portfolio import PortfolioSnapshotResponse

_CHECK_RESULTS = TypeAdapter(list[dict[str, JsonValue]])
_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class PositionEventResponse(BaseModel):
    """One immutable monitoring decision and its complete accounting transition."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    position_id: UUID
    opening_trade_id: UUID
    portfolio_id: UUID
    market_id: UUID
    outcome_team_id: UUID
    market_price_id: UUID | None
    base_forecast_id: UUID | None
    market_resolution_id: UUID | None
    portfolio_snapshot_before_id: UUID
    portfolio_snapshot_after_id: UUID | None
    execution_mode: str
    decision: str
    reason_code: str
    reason: str
    all_required_checks_passed: bool
    state_changed: bool
    failed_rules: list[str]
    checks: list[dict[str, JsonValue]]
    position_version_before: int
    position_version_after: int
    status_before: str
    status_after: str
    quantity_before: int
    action_quantity: int
    quantity_after: int
    gross_cost_basis_before: Decimal
    entry_fees_before: Decimal
    total_cost_basis_before: Decimal
    allocated_gross_cost_basis: Decimal
    allocated_entry_fees: Decimal
    allocated_total_cost_basis: Decimal
    gross_cost_basis_after: Decimal
    entry_fees_after: Decimal
    total_cost_basis_after: Decimal
    reference_price: Decimal | None
    exit_price: Decimal | None
    exit_slippage_bps: Decimal | None
    exit_slippage_amount_per_contract: Decimal | None
    reference_gross_proceeds: Decimal | None
    slippage_cost: Decimal | None
    gross_proceeds: Decimal | None
    exit_fee_bps: Decimal | None
    exit_fee_amount: Decimal | None
    net_proceeds: Decimal | None
    settlement_payout_per_contract: Decimal | None
    model_probability: Decimal | None
    hold_edge: Decimal | None
    after_mark_price: Decimal
    after_mark_basis: str
    after_market_value: Decimal
    after_unrealized_pnl: Decimal
    realized_pnl_before: Decimal
    realized_pnl_increment: Decimal
    realized_pnl_cumulative: Decimal
    policy_name: str
    policy_version: str
    policy_fingerprint: str
    input_fingerprint: str
    position_projection_fingerprint_before: str
    position_projection_fingerprint_after: str
    evaluated_at: datetime
    executed_at: datetime | None
    recorded_at: datetime
    audit_snapshot: dict[str, JsonValue]

    @classmethod
    def from_record(cls, record: PositionEventRecord) -> PositionEventResponse:
        return cls(
            id=record.id,
            position_id=record.position_id,
            opening_trade_id=record.opening_trade_id,
            portfolio_id=record.portfolio_id,
            market_id=record.market_id,
            outcome_team_id=record.outcome_team_id,
            market_price_id=record.market_price_id,
            base_forecast_id=record.base_forecast_id,
            market_resolution_id=record.market_resolution_id,
            portfolio_snapshot_before_id=record.portfolio_snapshot_before_id,
            portfolio_snapshot_after_id=record.portfolio_snapshot_after_id,
            execution_mode=record.execution_mode,
            decision=record.decision,
            reason_code=record.reason_code,
            reason=record.reason,
            all_required_checks_passed=record.all_required_checks_passed,
            state_changed=record.state_changed,
            failed_rules=record.failed_rules,
            checks=_CHECK_RESULTS.validate_python(record.check_results),
            position_version_before=record.position_version_before,
            position_version_after=record.position_version_after,
            status_before=record.status_before,
            status_after=record.status_after,
            quantity_before=record.quantity_before,
            action_quantity=record.action_quantity,
            quantity_after=record.quantity_after,
            gross_cost_basis_before=record.gross_cost_basis_before,
            entry_fees_before=record.entry_fees_before,
            total_cost_basis_before=record.total_cost_basis_before,
            allocated_gross_cost_basis=record.allocated_gross_cost_basis,
            allocated_entry_fees=record.allocated_entry_fees,
            allocated_total_cost_basis=record.allocated_total_cost_basis,
            gross_cost_basis_after=record.gross_cost_basis_after,
            entry_fees_after=record.entry_fees_after,
            total_cost_basis_after=record.total_cost_basis_after,
            reference_price=record.reference_price,
            exit_price=record.exit_price,
            exit_slippage_bps=record.exit_slippage_bps,
            exit_slippage_amount_per_contract=record.exit_slippage_amount_per_contract,
            reference_gross_proceeds=record.reference_gross_proceeds,
            slippage_cost=record.slippage_cost,
            gross_proceeds=record.gross_proceeds,
            exit_fee_bps=record.exit_fee_bps,
            exit_fee_amount=record.exit_fee_amount,
            net_proceeds=record.net_proceeds,
            settlement_payout_per_contract=record.settlement_payout_per_contract,
            model_probability=record.model_probability,
            hold_edge=record.hold_edge,
            after_mark_price=record.after_mark_price,
            after_mark_basis=record.after_mark_basis,
            after_market_value=record.after_market_value,
            after_unrealized_pnl=record.after_unrealized_pnl,
            realized_pnl_before=record.realized_pnl_before,
            realized_pnl_increment=record.realized_pnl_increment,
            realized_pnl_cumulative=record.realized_pnl_cumulative,
            policy_name=record.policy_name,
            policy_version=record.policy_version,
            policy_fingerprint=record.policy_fingerprint,
            input_fingerprint=record.input_fingerprint,
            position_projection_fingerprint_before=(record.position_projection_fingerprint_before),
            position_projection_fingerprint_after=record.position_projection_fingerprint_after,
            evaluated_at=record.evaluated_at,
            executed_at=record.executed_at,
            recorded_at=record.recorded_at,
            audit_snapshot=_JSON_OBJECT.validate_python(record.audit_snapshot),
        )


class PositionMonitoringItemResponse(BaseModel):
    """New or replayed result for one explicitly bounded position evaluation."""

    model_config = ConfigDict(frozen=True)

    created: bool
    event: PositionEventResponse
    position: PaperPositionResponse
    portfolio_snapshot: PortfolioSnapshotResponse | None


class PositionMonitoringRunResponse(BaseModel):
    """Bounded monitoring-run summary plus its position-level audit results."""

    model_config = ConfigDict(frozen=True)

    examined: int
    created: int
    replayed: int
    snapshots_appended: int
    decision_counts: dict[str, int]
    reason_counts: dict[str, int]
    results: list[PositionMonitoringItemResponse]
