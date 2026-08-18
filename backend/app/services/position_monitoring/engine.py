from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal
from uuid import UUID

from pydantic import JsonValue

from app.domain.position_monitoring import (
    MonitoredPositionStatus,
    PositionAccountingState,
    PositionDispositionEconomics,
    PositionMonitoringAction,
    PositionMonitoringCheck,
    PositionMonitoringDecision,
    PositionMonitoringInput,
    PositionMonitoringPolicy,
    PositionPortfolioDelta,
    cumulative_basis_allocation,
    floor_money,
)

_CENT = Decimal("0.01")
_PRICE_QUANTUM = Decimal("0.000001")
_BPS_DENOMINATOR = Decimal("10000")


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def position_monitoring_policy_fingerprint(policy: PositionMonitoringPolicy) -> str:
    """Hash every monitoring, disposition, freshness, and rounding assumption."""
    return _canonical_hash(
        {
            "policy": policy.model_dump(mode="json"),
            "hold_edge": "model_probability-current_same_side_bid",
            "exit_price": "floor_6(bid-exit_slippage_bps/10000)_bounded_at_zero",
            "gross_proceeds": "floor_to_cents",
            "nonzero_exit_fee": "ceil_to_cents",
            "partial_basis": "cumulative_original_component_allocation_floor_cents",
            "settlement": "explicit_official_held_side_payout_zero_exit_costs",
            "mark": "same_side_directional_bid_floor_value_to_cents",
        }
    )


def effective_position_monitoring_policy_version(policy: PositionMonitoringPolicy) -> str:
    """Return a readable code version bound to the complete effective policy."""
    return f"{policy.code_version}+cfg.{position_monitoring_policy_fingerprint(policy)[:12]}"


class DeterministicPositionMonitoringEngine:
    """Evaluate one open paper position and return exact accounting deltas."""

    def __init__(self, policy: PositionMonitoringPolicy) -> None:
        self.policy = policy
        self.policy_fingerprint = position_monitoring_policy_fingerprint(policy)
        self.policy_version = effective_position_monitoring_policy_version(policy)

    def evaluate(self, source: PositionMonitoringInput) -> PositionMonitoringDecision:
        """Apply settlement-first Phase 9 precedence without persistence side effects."""
        checks: list[PositionMonitoringCheck] = []

        def check(
            rule: str,
            passed: bool,
            actual: object,
            expected: object,
            detail: str,
        ) -> None:
            checks.append(
                PositionMonitoringCheck(
                    rule=rule,
                    passed=passed,
                    actual=self._json_value(actual),
                    expected=self._json_value(expected),
                    detail=detail,
                )
            )

        paper_only = (
            source.runtime_trading_mode == "paper" and source.position_execution_mode == "paper"
        )
        check(
            "paper_only",
            paper_only,
            {
                "runtime": source.runtime_trading_mode,
                "position": source.position_execution_mode,
            },
            {"runtime": "paper", "position": "paper"},
            "position monitoring cannot create live-mode financial state",
        )
        position_open = source.position.status is MonitoredPositionStatus.OPEN
        check(
            "position_open",
            position_open,
            source.position.status.value,
            MonitoredPositionStatus.OPEN.value,
            "only an open position may be monitored or disposed",
        )
        resolution_complete = not source.official_resolution_is_final or (
            source.official_resolution_id is not None
            and source.official_held_side_payout is not None
        )
        check(
            "official_resolution_complete",
            resolution_complete,
            {
                "is_final": source.official_resolution_is_final,
                "resolution_id": (
                    str(source.official_resolution_id)
                    if source.official_resolution_id is not None
                    else None
                ),
                "held_side_payout": (
                    str(source.official_held_side_payout)
                    if source.official_held_side_payout is not None
                    else None
                ),
            },
            "not final, or final with explicit official payout",
            "settlement requires an explicit normalized official held-side payout",
        )

        bid = source.yes_bid if source.direction == "yes" else source.no_bid
        price_age = self._age_seconds(source.evaluated_at, source.market_price_retrieved_at)
        forecast_age = self._age_seconds(source.evaluated_at, source.forecast_generated_at)
        event_semantics_valid = source.event_semantics_are_current
        price_current = source.market_price_is_current and source.market_price_id is not None
        price_fresh = (
            price_age is not None and 0 <= price_age <= self.policy.max_market_price_age_seconds
        )
        bid_available = bid is not None
        forecast_current = (
            source.forecast_is_current
            and source.forecast_id is not None
            and source.model_probability is not None
        )
        forecast_fresh = (
            forecast_age is not None and 0 <= forecast_age <= self.policy.max_forecast_age_seconds
        )
        pregame = (
            source.event_status == "scheduled"
            and not source.event_postponed
            and source.event_start_time > source.evaluated_at
        )
        market_open = source.market_status in {"active", "open"}
        check(
            "event_semantics_current",
            event_semantics_valid,
            event_semantics_valid,
            True,
            "event and held-outcome semantics must remain current",
        )
        check(
            "current_market_price",
            price_current,
            {
                "market_price_id": (
                    str(source.market_price_id) if source.market_price_id is not None else None
                ),
                "is_current": source.market_price_is_current,
            },
            {"market_price_id": "present", "is_current": True},
            "monitoring must use the exact latest market-price snapshot",
        )
        check(
            "fresh_market_price",
            price_fresh,
            price_age,
            f"0..{self.policy.max_market_price_age_seconds}",
            "market price must not be future-dated or stale",
        )
        check(
            "same_side_directional_bid",
            bid_available,
            str(bid) if bid is not None else None,
            f"direct {source.direction} bid",
            "holds and exits use only the held side's direct bid",
        )
        check(
            "current_forecast",
            forecast_current,
            {
                "forecast_id": str(source.forecast_id) if source.forecast_id is not None else None,
                "is_current": source.forecast_is_current,
                "model_probability": (
                    str(source.model_probability) if source.model_probability is not None else None
                ),
            },
            {"forecast_id": "present", "is_current": True, "model_probability": "present"},
            "monitoring must use the exact latest operational forecast",
        )
        check(
            "fresh_forecast",
            forecast_fresh,
            forecast_age,
            f"0..{self.policy.max_forecast_age_seconds}",
            "operational forecast must not be future-dated or stale",
        )
        check(
            "pregame_state",
            pregame,
            {
                "event_status": source.event_status,
                "postponed": source.event_postponed,
                "start_time": source.event_start_time.isoformat(),
            },
            "scheduled, not postponed, and starts after evaluation",
            "post-start or otherwise ineligible events are held pending a later safe transition",
        )
        check(
            "market_open_or_resolved",
            market_open or source.official_resolution_is_final,
            {
                "market_status": source.market_status,
                "official_resolution_final": source.official_resolution_is_final,
            },
            "open/active market or final official resolution",
            "closed unresolved markets must await authoritative settlement",
        )

        if not paper_only:
            return self._hold(
                source, checks, "paper_only", "monitoring is disabled outside paper mode"
            )
        if not position_open:
            return self._hold(
                source,
                checks,
                "position_not_open",
                "only open positions can enter monitoring",
            )
        if source.official_resolution_is_final:
            if not resolution_complete:
                return self._hold(
                    source,
                    checks,
                    "official_resolution_payout_unavailable",
                    "final resolution lacks an explicit official held-side payout",
                )
            assert source.official_held_side_payout is not None
            return self._settle(source, checks, source.official_held_side_payout)
        if not market_open:
            return self._hold(
                source,
                checks,
                "market_closed_unresolved",
                "market is closed without final resolution",
            )

        invalid_reasons = (
            (
                event_semantics_valid,
                "event_semantics_invalid",
                "event or held-outcome semantics are no longer current",
            ),
            (price_current, "market_price_not_current", "latest market price is unavailable"),
            (price_fresh, "market_price_stale", "market price is future-dated or stale"),
            (bid_available, "directional_bid_unavailable", "held-side direct bid is unavailable"),
            (
                forecast_current,
                "forecast_not_current",
                "latest operational forecast is unavailable",
            ),
            (forecast_fresh, "forecast_stale", "operational forecast is future-dated or stale"),
            (pregame, "event_not_pregame", "event is postponed, started, or no longer scheduled"),
        )
        for passed, reason_code, reason in invalid_reasons:
            if not passed:
                return self._hold(source, checks, reason_code, reason)

        assert bid is not None
        assert source.model_probability is not None
        hold_edge = (source.model_probability - bid).quantize(
            _PRICE_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
        if hold_edge <= 0:
            return self._sell(
                source,
                checks,
                action=PositionMonitoringAction.CLOSE,
                quantity=source.position.remaining_quantity,
                bid=bid,
                hold_edge=hold_edge,
                reason_code="hold_edge_nonpositive",
                reason="remaining forecast edge is nonpositive at the executable bid",
            )
        if hold_edge < self.policy.min_hold_edge and source.model_probability <= Decimal("0.5"):
            return self._sell(
                source,
                checks,
                action=PositionMonitoringAction.CLOSE,
                quantity=source.position.remaining_quantity,
                bid=bid,
                hold_edge=hold_edge,
                reason_code="forecast_reversed_below_hold_threshold",
                reason="forecast is at most 50% and remaining edge is below the hold threshold",
            )
        if hold_edge < self.policy.min_hold_edge:
            if source.position.remaining_quantity == 1:
                return self._sell(
                    source,
                    checks,
                    action=PositionMonitoringAction.CLOSE,
                    quantity=1,
                    bid=bid,
                    hold_edge=hold_edge,
                    reason_code="single_contract_cannot_reduce",
                    reason="one remaining contract cannot be partially reduced",
                )
            reduce_quantity = max(
                1,
                int(
                    (
                        source.position.remaining_quantity * self.policy.reduce_fraction
                    ).to_integral_value(rounding=ROUND_UP)
                ),
            )
            reduce_quantity = min(reduce_quantity, source.position.remaining_quantity - 1)
            return self._sell(
                source,
                checks,
                action=PositionMonitoringAction.REDUCE,
                quantity=reduce_quantity,
                bid=bid,
                hold_edge=hold_edge,
                reason_code="edge_below_hold_threshold_reduce",
                reason="positive remaining edge is below the hold threshold",
            )
        return self._hold(
            source,
            checks,
            "minimum_hold_edge_met",
            "remaining edge meets the configured hold threshold",
            bid=bid,
            hold_edge=hold_edge,
        )

    def _hold(
        self,
        source: PositionMonitoringInput,
        checks: list[PositionMonitoringCheck],
        reason_code: str,
        reason: str,
        *,
        bid: Decimal | None = None,
        hold_edge: Decimal | None = None,
    ) -> PositionMonitoringDecision:
        before = source.position
        if bid is None:
            after = before
        else:
            market_value = floor_money(bid * before.remaining_quantity)
            after = before.model_copy(
                update={
                    "mark_price": bid,
                    "mark_basis": "directional_bid",
                    "market_value": market_value,
                    "unrealized_pnl": market_value - before.remaining_total_cost_basis,
                }
            )
        delta = self._portfolio_delta(
            before, after, net_proceeds=Decimal("0.00"), realized=Decimal("0.00")
        )
        return self._decision(
            source=source,
            checks=checks,
            action=PositionMonitoringAction.HOLD,
            reason_code=reason_code,
            reason=reason,
            hold_edge=hold_edge,
            before=before,
            after=after,
            economics=None,
            portfolio_delta=delta,
        )

    def _sell(
        self,
        source: PositionMonitoringInput,
        checks: list[PositionMonitoringCheck],
        *,
        action: PositionMonitoringAction,
        quantity: int,
        bid: Decimal,
        hold_edge: Decimal,
        reason_code: str,
        reason: str,
    ) -> PositionMonitoringDecision:
        execution_price = max(
            Decimal("0"),
            (bid - self.policy.exit_slippage_bps / _BPS_DENOMINATOR).quantize(
                _PRICE_QUANTUM,
                rounding=ROUND_DOWN,
            ),
        )
        reference_gross = floor_money(bid * quantity)
        gross = floor_money(execution_price * quantity)
        slippage = reference_gross - gross
        fee = (
            Decimal("0.00")
            if self.policy.exit_fee_bps == 0
            else self._ceil_money(gross * self.policy.exit_fee_bps / _BPS_DENOMINATOR)
        )
        net = gross - fee
        return self._disposition(
            source=source,
            checks=checks,
            action=action,
            quantity=quantity,
            reference_price=bid,
            execution_price=execution_price,
            reference_gross=reference_gross,
            gross=gross,
            slippage=slippage,
            fee=fee,
            net=net,
            hold_edge=hold_edge,
            reason_code=reason_code,
            reason=reason,
            settlement=False,
        )

    def _settle(
        self,
        source: PositionMonitoringInput,
        checks: list[PositionMonitoringCheck],
        payout: Decimal,
    ) -> PositionMonitoringDecision:
        quantity = source.position.remaining_quantity
        gross = floor_money(payout * quantity)
        return self._disposition(
            source=source,
            checks=checks,
            action=PositionMonitoringAction.SETTLE,
            quantity=quantity,
            reference_price=payout,
            execution_price=payout,
            reference_gross=gross,
            gross=gross,
            slippage=Decimal("0.00"),
            fee=Decimal("0.00"),
            net=gross,
            hold_edge=None,
            reason_code="official_resolution_settlement",
            reason="official held-side payout settled the remaining paper position",
            settlement=True,
        )

    def _disposition(
        self,
        *,
        source: PositionMonitoringInput,
        checks: list[PositionMonitoringCheck],
        action: PositionMonitoringAction,
        quantity: int,
        reference_price: Decimal,
        execution_price: Decimal,
        reference_gross: Decimal,
        gross: Decimal,
        slippage: Decimal,
        fee: Decimal,
        net: Decimal,
        hold_edge: Decimal | None,
        reason_code: str,
        reason: str,
        settlement: bool,
    ) -> PositionMonitoringDecision:
        before = source.position
        new_disposed = before.disposed_quantity + quantity
        if quantity == before.remaining_quantity:
            allocated_gross = before.remaining_gross_cost_basis
            allocated_entry_fees = before.remaining_entry_fees
        else:
            allocated_gross = cumulative_basis_allocation(
                original_amount=before.original_gross_cost_basis,
                disposed_quantity=new_disposed,
                initial_quantity=before.initial_quantity,
            ) - cumulative_basis_allocation(
                original_amount=before.original_gross_cost_basis,
                disposed_quantity=before.disposed_quantity,
                initial_quantity=before.initial_quantity,
            )
            allocated_entry_fees = cumulative_basis_allocation(
                original_amount=before.original_entry_fees,
                disposed_quantity=new_disposed,
                initial_quantity=before.initial_quantity,
            ) - cumulative_basis_allocation(
                original_amount=before.original_entry_fees,
                disposed_quantity=before.disposed_quantity,
                initial_quantity=before.initial_quantity,
            )
        allocated_total = allocated_gross + allocated_entry_fees
        realized_increment = net - allocated_total
        economics = PositionDispositionEconomics(
            disposed_quantity=quantity,
            reference_price=reference_price,
            execution_price=execution_price,
            reference_gross_proceeds=reference_gross,
            gross_proceeds=gross,
            slippage_cost=slippage,
            exit_fee=fee,
            net_proceeds=net,
            allocated_gross_cost_basis=allocated_gross,
            allocated_entry_fees=allocated_entry_fees,
            allocated_total_cost_basis=allocated_total,
            realized_pnl_increment=realized_increment,
        )
        remaining_quantity = before.remaining_quantity - quantity
        if remaining_quantity:
            bid = source.yes_bid if source.direction == "yes" else source.no_bid
            if bid is None:
                raise RuntimeError("partial disposition requires its validated same-side bid")
            remaining_gross = before.remaining_gross_cost_basis - allocated_gross
            remaining_fees = before.remaining_entry_fees - allocated_entry_fees
            remaining_total = remaining_gross + remaining_fees
            market_value = floor_money(bid * remaining_quantity)
            after = PositionAccountingState(
                status=MonitoredPositionStatus.OPEN,
                initial_quantity=before.initial_quantity,
                disposed_quantity=new_disposed,
                remaining_quantity=remaining_quantity,
                original_gross_cost_basis=before.original_gross_cost_basis,
                original_entry_fees=before.original_entry_fees,
                original_total_cost_basis=before.original_total_cost_basis,
                remaining_gross_cost_basis=remaining_gross,
                remaining_entry_fees=remaining_fees,
                remaining_total_cost_basis=remaining_total,
                mark_price=bid,
                mark_basis="directional_bid",
                market_value=market_value,
                unrealized_pnl=market_value - remaining_total,
                realized_pnl=before.realized_pnl + realized_increment,
            )
        else:
            after = PositionAccountingState(
                status=(
                    MonitoredPositionStatus.SETTLED
                    if settlement
                    else MonitoredPositionStatus.CLOSED
                ),
                initial_quantity=before.initial_quantity,
                disposed_quantity=before.initial_quantity,
                remaining_quantity=0,
                original_gross_cost_basis=before.original_gross_cost_basis,
                original_entry_fees=before.original_entry_fees,
                original_total_cost_basis=before.original_total_cost_basis,
                remaining_gross_cost_basis=Decimal("0.00"),
                remaining_entry_fees=Decimal("0.00"),
                remaining_total_cost_basis=Decimal("0.00"),
                mark_price=execution_price,
                mark_basis="settlement_payout" if settlement else "exit_execution",
                market_value=Decimal("0.00"),
                unrealized_pnl=Decimal("0.00"),
                realized_pnl=before.realized_pnl + realized_increment,
            )
        delta = self._portfolio_delta(
            before,
            after,
            net_proceeds=net,
            realized=realized_increment,
        )
        return self._decision(
            source=source,
            checks=checks,
            action=action,
            reason_code=reason_code,
            reason=reason,
            hold_edge=hold_edge,
            before=before,
            after=after,
            economics=economics,
            portfolio_delta=delta,
        )

    def _decision(
        self,
        *,
        source: PositionMonitoringInput,
        checks: list[PositionMonitoringCheck],
        action: PositionMonitoringAction,
        reason_code: str,
        reason: str,
        hold_edge: Decimal | None,
        before: PositionAccountingState,
        after: PositionAccountingState,
        economics: PositionDispositionEconomics | None,
        portfolio_delta: PositionPortfolioDelta,
    ) -> PositionMonitoringDecision:
        # Deliberately exclude projection state and evaluation time. An application service can
        # replay a prior event by this fingerprint before a repeated REDUCE mutates the position.
        input_fingerprint = _canonical_hash(
            {
                "position_id": str(source.position_id),
                "portfolio_id": str(source.portfolio_id),
                "market_id": str(source.market_id),
                "outcome_team_id": str(source.outcome_team_id),
                "direction": source.direction,
                "runtime_trading_mode": source.runtime_trading_mode,
                "position_execution_mode": source.position_execution_mode,
                "market_event_match_id": (
                    str(source.market_event_match_id)
                    if source.market_event_match_id is not None
                    else None
                ),
                "market": {
                    "status": source.market_status,
                    "event_status": source.event_status,
                    "event_postponed": source.event_postponed,
                    "event_start_time": source.event_start_time.isoformat(),
                    "event_semantics_are_current": source.event_semantics_are_current,
                },
                "price": {
                    "id": str(source.market_price_id) if source.market_price_id else None,
                    "is_current": source.market_price_is_current,
                    "retrieved_at": (
                        source.market_price_retrieved_at.isoformat()
                        if source.market_price_retrieved_at
                        else None
                    ),
                    "yes_bid": str(source.yes_bid) if source.yes_bid is not None else None,
                    "no_bid": str(source.no_bid) if source.no_bid is not None else None,
                },
                "forecast": {
                    "id": str(source.forecast_id) if source.forecast_id else None,
                    "is_current": source.forecast_is_current,
                    "generated_at": (
                        source.forecast_generated_at.isoformat()
                        if source.forecast_generated_at
                        else None
                    ),
                    "model_probability": (
                        str(source.model_probability)
                        if source.model_probability is not None
                        else None
                    ),
                },
                "resolution": {
                    "id": (
                        str(source.official_resolution_id)
                        if source.official_resolution_id
                        else None
                    ),
                    "is_final": source.official_resolution_is_final,
                    "held_side_payout": (
                        str(source.official_held_side_payout)
                        if source.official_held_side_payout is not None
                        else None
                    ),
                },
                "source_check_outcomes": [
                    {"rule": item.rule, "passed": item.passed} for item in checks
                ],
                "policy_fingerprint": self.policy_fingerprint,
            }
        )
        audit_snapshot: dict[str, JsonValue] = {
            "source": {
                "position_id": str(source.position_id),
                "portfolio_snapshot_id": str(source.portfolio_snapshot_id),
                "market_event_match_id": (
                    str(source.market_event_match_id)
                    if source.market_event_match_id is not None
                    else None
                ),
                "market_price_id": (
                    str(source.market_price_id) if source.market_price_id else None
                ),
                "forecast_id": str(source.forecast_id) if source.forecast_id else None,
                "resolution_id": (
                    str(source.official_resolution_id) if source.official_resolution_id else None
                ),
            },
            "decision": {
                "action": action.value,
                "reason_code": reason_code,
                "hold_edge": str(hold_edge) if hold_edge is not None else None,
            },
            "before": before.model_dump(mode="json"),
            "after": after.model_dump(mode="json"),
            "economics": economics.model_dump(mode="json") if economics else None,
            "portfolio_delta": portfolio_delta.model_dump(mode="json"),
            "checks": [item.model_dump(mode="json") for item in checks],
            "policy": self.policy.model_dump(mode="json"),
        }
        return PositionMonitoringDecision(
            position_id=source.position_id,
            portfolio_id=source.portfolio_id,
            portfolio_snapshot_id=source.portfolio_snapshot_id,
            market_id=source.market_id,
            outcome_team_id=source.outcome_team_id,
            market_event_match_id=source.market_event_match_id,
            market_price_id=source.market_price_id,
            forecast_id=source.forecast_id,
            official_resolution_id=source.official_resolution_id,
            direction=source.direction,
            action=action,
            reason_code=reason_code,
            reason=reason,
            checks=tuple(checks),
            hold_edge=hold_edge,
            before=before,
            after=after,
            economics=economics,
            portfolio_delta=portfolio_delta,
            policy_name=self.policy.strategy_name,
            policy_version=self.policy_version,
            policy_fingerprint=self.policy_fingerprint,
            input_fingerprint=input_fingerprint,
            evaluated_at=source.evaluated_at,
            audit_snapshot=audit_snapshot,
        )

    @staticmethod
    def _portfolio_delta(
        before: PositionAccountingState,
        after: PositionAccountingState,
        *,
        net_proceeds: Decimal,
        realized: Decimal,
    ) -> PositionPortfolioDelta:
        committed = after.remaining_total_cost_basis - before.remaining_total_cost_basis
        open_value = after.market_value - before.market_value
        unrealized = after.unrealized_pnl - before.unrealized_pnl
        return PositionPortfolioDelta(
            current_bankroll=realized,
            cash_balance=net_proceeds,
            reserved_capital=Decimal("0.00"),
            committed_capital=committed,
            available_bankroll=net_proceeds,
            realized_pnl=realized,
            open_position_value=open_value,
            unrealized_pnl=unrealized,
            total_portfolio_value=net_proceeds + open_value,
        )

    @staticmethod
    def _ceil_money(value: Decimal) -> Decimal:
        return value.quantize(_CENT, rounding=ROUND_UP)

    @staticmethod
    def _age_seconds(evaluated_at: datetime, observed_at: datetime | None) -> int | None:
        if observed_at is None:
            return None
        return int((evaluated_at - observed_at).total_seconds())

    @staticmethod
    def _json_value(value: object) -> JsonValue:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {
                str(key): DeterministicPositionMonitoringEngine._json_value(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [DeterministicPositionMonitoringEngine._json_value(item) for item in value]
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)
