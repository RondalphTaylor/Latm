from __future__ import annotations

import hashlib
import json
from decimal import ROUND_DOWN, ROUND_UP, Decimal
from uuid import UUID

from pydantic import JsonValue

from app.domain.execution import (
    PaperExecutionCheck,
    PaperExecutionDecision,
    PaperExecutionInput,
    PaperExecutionPolicy,
    PaperMarkBasis,
    PaperTradeStatus,
)

_CENT = Decimal("0.01")
_PRICE_QUANTUM = Decimal("0.000001")
_BPS_DENOMINATOR = Decimal("10000")


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def paper_execution_policy_fingerprint(policy: PaperExecutionPolicy) -> str:
    """Hash every effective immediate-fill assumption and rounding rule."""
    return _canonical_hash(
        {
            "policy": policy.model_dump(mode="json"),
            "slippage_interpretation": "absolute_binary_price_points",
            "execution_price_rounding": "up_to_six_decimals",
            "quantity": "largest_whole_contract_within_all_in_cap",
            "gross_cost_rounding": "up_to_cents",
            "fee_rounding": "up_to_cents",
            "market_value_rounding": "down_to_cents",
            "mark_priority": "directional_bid_then_directional_ask_fallback",
        }
    )


def effective_paper_execution_policy_version(policy: PaperExecutionPolicy) -> str:
    """Return a readable version bound to all configured assumptions."""
    return f"{policy.code_version}+cfg.{paper_execution_policy_fingerprint(policy)[:12]}"


class ImmediatePaperExecutionEngine:
    """Create a conservative immediate paper fill without external side effects."""

    def __init__(self, policy: PaperExecutionPolicy) -> None:
        self.policy = policy
        self.policy_fingerprint = paper_execution_policy_fingerprint(policy)
        self.policy_version = effective_paper_execution_policy_version(policy)

    def evaluate(self, source: PaperExecutionInput) -> PaperExecutionDecision:
        """Evaluate hard gates, then calculate the largest affordable whole-contract fill."""
        checks: list[PaperExecutionCheck] = []

        def check(
            rule: str,
            passed: bool,
            actual: object,
            expected: object,
            detail: str,
        ) -> None:
            checks.append(
                PaperExecutionCheck(
                    rule=rule,
                    passed=passed,
                    actual=self._json_value(actual),
                    expected=self._json_value(expected),
                    detail=detail,
                )
            )

        check(
            "paper_only",
            source.runtime_trading_mode == source.risk_execution_mode == "paper",
            {
                "runtime": source.runtime_trading_mode,
                "risk": source.risk_execution_mode,
            },
            {"runtime": "paper", "risk": "paper"},
            "paper execution cannot consume or create live-mode state",
        )
        check(
            "automatic_risk_authorization",
            source.risk_decision == "auto_approve" and source.risk_all_required_checks_passed,
            {
                "decision": source.risk_decision,
                "all_checks_passed": source.risk_all_required_checks_passed,
            },
            {"decision": "auto_approve", "all_checks_passed": True},
            "only a fully passed automatic authorization may enter paper execution",
        )
        check(
            "risk_authorization_unexpired",
            source.authorization_valid_until is not None
            and source.authorization_valid_until > source.attempted_at,
            (
                source.authorization_valid_until.isoformat()
                if source.authorization_valid_until is not None
                else None
            ),
            f"> {source.attempted_at.isoformat()}",
            "risk authorization must expire strictly after the locked execution time",
        )
        check(
            "latest_active_risk_policy",
            source.risk_is_latest and source.risk_policy_is_active,
            {
                "is_latest": source.risk_is_latest,
                "policy_is_active": source.risk_policy_is_active,
            },
            {"is_latest": True, "policy_is_active": True},
            "the requested decision must be the latest result under the active policy",
        )
        check(
            "exact_risk_revalidation",
            source.risk_revalidation_decision == "auto_approve"
            and source.risk_input_fingerprint == source.revalidated_risk_input_fingerprint,
            {
                "decision": source.risk_revalidation_decision,
                "fingerprint_matches": (
                    source.risk_input_fingerprint == source.revalidated_risk_input_fingerprint
                ),
            },
            {"decision": "auto_approve", "fingerprint_matches": True},
            "all mutable risk inputs must reproduce the authorized decision exactly",
        )
        check(
            "latest_portfolio_snapshot",
            source.portfolio_snapshot_id == source.latest_snapshot_id,
            str(source.portfolio_snapshot_id),
            str(source.latest_snapshot_id),
            "execution must consume the exact latest authorized portfolio snapshot",
        )
        check(
            "single_use_authorization",
            source.no_prior_execution,
            source.no_prior_execution,
            True,
            "one risk decision may create at most one terminal execution attempt",
        )
        check(
            "no_open_market_position",
            source.no_open_market_position,
            source.no_open_market_position,
            True,
            "Phase 8 permits only one open position per portfolio and market",
        )
        check(
            "available_bankroll",
            source.proposed_capital > 0
            and source.proposed_capital <= source.current_available_bankroll,
            {
                "proposed_capital": str(source.proposed_capital),
                "available_bankroll": str(source.current_available_bankroll),
            },
            "0 < proposed_capital <= current_available_bankroll",
            "authorized capital must still fit inside available paper cash",
        )
        ask = source.current_directional_ask
        bid = source.current_directional_bid
        book_valid = (
            ask is not None
            and Decimal("0") < ask < Decimal("1")
            and (bid is None or (Decimal("0") <= bid < Decimal("1") and bid <= ask))
            and ask == source.reference_price
        )
        check(
            "valid_current_directional_book",
            book_valid,
            {
                "ask": str(ask) if ask is not None else None,
                "bid": str(bid) if bid is not None else None,
                "authorized_reference_price": str(source.reference_price),
            },
            "0 < direct ask < 1, 0 <= direct bid <= ask, ask equals authorized source",
            "execution must use the unchanged direct directional ask and a valid book",
        )

        failed = tuple(item.rule for item in checks if not item.passed)
        if failed:
            return self._rejected(source, checks, failed)
        assert ask is not None

        execution_price = (ask + self.policy.slippage_bps / _BPS_DENOMINATOR).quantize(
            _PRICE_QUANTUM,
            rounding=ROUND_UP,
        )
        check(
            "execution_price_below_one",
            execution_price < Decimal("1"),
            str(execution_price),
            "< 1",
            "configured slippage cannot make a binary contract cost one dollar or more",
        )
        if execution_price >= Decimal("1"):
            failed = ("execution_price_below_one",)
            return self._rejected(source, checks, failed)

        fee_rate = self.policy.fee_bps / _BPS_DENOMINATOR
        estimated_unit_cost = execution_price * (Decimal("1") + fee_rate)
        requested_quantity = int(
            (source.proposed_capital / estimated_unit_cost).to_integral_value(rounding=ROUND_DOWN)
        )
        quantity = requested_quantity
        gross_cost = Decimal("0.00")
        fee_amount = Decimal("0.00")
        total_cost = Decimal("0.00")
        while quantity > 0:
            gross_cost = self._ceil_money(execution_price * quantity)
            fee_amount = (
                Decimal("0.00")
                if self.policy.fee_bps == 0
                else self._ceil_money(gross_cost * fee_rate)
            )
            total_cost = gross_cost + fee_amount
            if total_cost <= source.proposed_capital:
                break
            quantity -= 1
        check(
            "minimum_one_contract",
            quantity >= 1,
            quantity,
            ">= 1 whole contract",
            "authorized capital must fund at least one all-in contract",
        )
        if quantity < 1:
            return self._rejected(source, checks, ("minimum_one_contract",))

        reference_gross_cost = self._ceil_money(ask * quantity)
        slippage_cost = gross_cost - reference_gross_cost
        unused_capital = source.proposed_capital - total_cost
        effective_unit_cost = (total_cost / quantity).quantize(
            _PRICE_QUANTUM,
            rounding=ROUND_UP,
        )
        adjusted_edge = (source.model_probability - effective_unit_cost).quantize(
            _PRICE_QUANTUM,
        )
        check(
            "minimum_adjusted_edge",
            adjusted_edge >= source.minimum_adjusted_edge,
            str(adjusted_edge),
            str(source.minimum_adjusted_edge),
            "post-slippage and post-fee edge must remain independently qualifying",
        )
        if adjusted_edge < source.minimum_adjusted_edge:
            return self._rejected(source, checks, ("minimum_adjusted_edge",))

        mark_price = bid if bid is not None else ask
        mark_basis = (
            PaperMarkBasis.DIRECTIONAL_BID
            if bid is not None
            else PaperMarkBasis.DIRECTIONAL_ASK_FALLBACK
        )
        market_value = (mark_price * quantity).quantize(_CENT, rounding=ROUND_DOWN)
        unrealized_pnl = market_value - total_cost
        semantic_input = source.model_dump(mode="json", exclude={"attempted_at"})
        input_fingerprint = _canonical_hash(
            {
                "source": semantic_input,
                "policy_fingerprint": self.policy_fingerprint,
                "execution_price": str(execution_price),
                "quantity": quantity,
                "total_cost": str(total_cost),
            }
        )
        audit_snapshot = self._audit_snapshot(
            source=source,
            checks=checks,
            economics={
                "reference_price": str(ask),
                "execution_price": str(execution_price),
                "requested_quantity": requested_quantity,
                "executed_quantity": quantity,
                "reference_gross_cost": str(reference_gross_cost),
                "gross_cost": str(gross_cost),
                "slippage_cost": str(slippage_cost),
                "fee_amount": str(fee_amount),
                "total_cost": str(total_cost),
                "unused_capital": str(unused_capital),
                "effective_unit_cost": str(effective_unit_cost),
                "adjusted_edge": str(adjusted_edge),
                "mark_price": str(mark_price),
                "mark_basis": mark_basis.value,
                "market_value": str(market_value),
                "unrealized_pnl": str(unrealized_pnl),
            },
        )
        return PaperExecutionDecision(
            status=PaperTradeStatus.FILLED,
            reason_code="paper_entry_filled",
            reason="automatic risk authorization revalidated and immediate paper fill completed",
            checks=tuple(checks),
            failed_rules=(),
            requested_capital=source.proposed_capital,
            reference_price=source.reference_price,
            execution_price=execution_price,
            slippage_amount_per_contract=execution_price - ask,
            requested_quantity=requested_quantity,
            executed_quantity=quantity,
            reference_gross_cost=reference_gross_cost,
            gross_cost=gross_cost,
            slippage_cost=slippage_cost,
            fee_amount=fee_amount,
            total_cost=total_cost,
            unused_capital=unused_capital,
            effective_unit_cost=effective_unit_cost,
            adjusted_edge=adjusted_edge,
            mark_price=mark_price,
            mark_basis=mark_basis,
            market_value=market_value,
            unrealized_pnl=unrealized_pnl,
            execution_policy_name=self.policy.strategy_name,
            execution_policy_version=self.policy_version,
            execution_policy_fingerprint=self.policy_fingerprint,
            input_fingerprint=input_fingerprint,
            attempted_at=source.attempted_at,
            audit_snapshot=audit_snapshot,
        )

    def _rejected(
        self,
        source: PaperExecutionInput,
        checks: list[PaperExecutionCheck],
        failed_rules: tuple[str, ...],
    ) -> PaperExecutionDecision:
        input_fingerprint = _canonical_hash(
            {
                "source": source.model_dump(mode="json", exclude={"attempted_at"}),
                "policy_fingerprint": self.policy_fingerprint,
                "failed_rules": failed_rules,
            }
        )
        return PaperExecutionDecision(
            status=PaperTradeStatus.REJECTED,
            reason_code=failed_rules[0],
            reason="paper execution hard checks failed: " + ", ".join(failed_rules),
            checks=tuple(checks),
            failed_rules=failed_rules,
            requested_capital=source.proposed_capital,
            reference_price=source.reference_price,
            execution_policy_name=self.policy.strategy_name,
            execution_policy_version=self.policy_version,
            execution_policy_fingerprint=self.policy_fingerprint,
            input_fingerprint=input_fingerprint,
            attempted_at=source.attempted_at,
            audit_snapshot=self._audit_snapshot(source=source, checks=checks, economics=None),
        )

    def _audit_snapshot(
        self,
        *,
        source: PaperExecutionInput,
        checks: list[PaperExecutionCheck],
        economics: dict[str, JsonValue] | None,
    ) -> dict[str, JsonValue]:
        return {
            "authorization": {
                "risk_decision_id": str(source.risk_decision_id),
                "risk_input_fingerprint": source.risk_input_fingerprint,
                "authorization_valid_until": (
                    source.authorization_valid_until.isoformat()
                    if source.authorization_valid_until is not None
                    else None
                ),
            },
            "proposal": {
                "id": str(source.position_size_proposal_id),
                "proposed_capital": str(source.proposed_capital),
                "reference_price": str(source.reference_price),
                "model_probability": str(source.model_probability),
                "raw_edge": str(source.raw_edge),
            },
            "policy": self.policy.model_dump(mode="json"),
            "checks": [item.model_dump(mode="json") for item in checks],
            "economics": economics,
            "limitations": {
                "fill_model": "immediate_full_fill",
                "quantity": "whole_contracts",
                "slippage": "fixed_absolute_binary_price_points",
                "fee": "flat_configured_estimate",
                "liquidity": "not_modeled",
                "partial_fills": "not_supported",
                "live_execution": "not_implemented",
            },
        }

    @staticmethod
    def _ceil_money(value: Decimal) -> Decimal:
        return value.quantize(_CENT, rounding=ROUND_UP)

    @staticmethod
    def _json_value(value: object) -> JsonValue:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, dict):
            return {
                str(key): ImmediatePaperExecutionEngine._json_value(item)
                for key, item in value.items()
            }
        if isinstance(value, (str, int, bool)) or value is None:
            return value
        return str(value)
