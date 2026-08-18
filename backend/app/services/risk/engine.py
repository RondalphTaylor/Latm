from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from uuid import UUID

from pydantic import JsonValue

from app.domain.risk import (
    RiskCheckResult,
    RiskDecision,
    RiskDecisionType,
    RiskEscalationBand,
    RiskEvaluationInput,
    RiskPolicy,
)

RISK_FORMULA = "ordered_hard_checks_then_exposure_escalation_v1"
_EXPOSURE_QUANTUM = Decimal("0.0000000001")


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def risk_policy_fingerprint(policy: RiskPolicy) -> str:
    """Hash every effective V1 rule, threshold, and comparison boundary."""
    return _canonical_hash(
        {
            "policy": policy.model_dump(mode="json"),
            "formula": RISK_FORMULA,
            "auto_comparison": "exposure < auto_approve_exposure_max",
            "medium_comparison": "auto_max <= exposure <= high_confidence_max",
            "large_comparison": "exposure > high_confidence_max",
            "medium_confidence_behavior": "require_human_when_not_available",
            "duplicate_scope": ("portfolio_market_unconsumed_authorizations_or_open_position"),
            "bankroll_rule": "unconsumed_authorized_capital_plus_proposal_lte_available",
            "authorization_window": "fixed_utc_epoch_bucket",
        }
    )


def effective_risk_policy_version(policy: RiskPolicy) -> str:
    """Return a human-readable version tied to the complete effective policy."""
    return f"{policy.code_version}+cfg.{risk_policy_fingerprint(policy)[:12]}"


class DeterministicRiskEngine:
    """Evaluate immutable proposal evidence without reserving or executing capital."""

    def __init__(self, policy: RiskPolicy) -> None:
        self.policy = policy
        self.policy_fingerprint = risk_policy_fingerprint(policy)
        self.policy_version = effective_risk_policy_version(policy)

    def evaluate(self, source: RiskEvaluationInput) -> RiskDecision:
        """Return one fully explained deterministic risk decision."""
        checks: list[RiskCheckResult] = []

        def check(
            rule: str,
            passed: bool,
            actual: object,
            expected: object,
            detail: str,
        ) -> None:
            checks.append(
                RiskCheckResult(
                    rule=rule,
                    passed=passed,
                    actual=self._json_value(actual),
                    expected=self._json_value(expected),
                    detail=detail,
                )
            )

        check(
            "runtime_paper_mode",
            source.runtime_trading_mode == "paper",
            source.runtime_trading_mode,
            "paper",
            "runtime trading mode must be paper",
        )
        check(
            "proposal_paper_mode",
            source.proposal_execution_mode == "paper",
            source.proposal_execution_mode,
            "paper",
            "position-size proposal must be paper-only",
        )
        check(
            "proposal_awaiting_risk",
            source.proposal_state == "awaiting_risk",
            source.proposal_state,
            "awaiting_risk",
            "proposal must remain in its pre-risk state",
        )
        check(
            "active_paper_portfolio",
            source.portfolio_execution_mode == "paper"
            and source.portfolio_status == "active"
            and source.portfolio_is_active,
            {
                "mode": source.portfolio_execution_mode,
                "status": source.portfolio_status,
                "is_active": source.portfolio_is_active,
            },
            {"mode": "paper", "status": "active", "is_active": True},
            "portfolio must be active and paper-only",
        )
        check(
            "active_sizing_strategy",
            source.proposal_strategy_version == source.active_sizing_strategy_version,
            source.proposal_strategy_version,
            source.active_sizing_strategy_version,
            "proposal must use the currently configured sizing strategy",
        )
        check(
            "latest_portfolio_snapshot",
            source.proposal_snapshot_id == source.latest_snapshot_id,
            str(source.proposal_snapshot_id),
            str(source.latest_snapshot_id),
            "proposal must reference the latest authoritative portfolio snapshot",
        )
        balance_equations_hold = (
            source.snapshot_current_bankroll
            == source.snapshot_starting_bankroll + source.snapshot_realized_pnl
            and source.snapshot_cash_balance
            == source.snapshot_current_bankroll - source.snapshot_committed_capital
            and source.snapshot_available_bankroll
            == source.snapshot_cash_balance - source.snapshot_reserved_capital
        )
        check(
            "portfolio_accounting_valid",
            balance_equations_hold,
            {
                "current": str(source.snapshot_current_bankroll),
                "cash": str(source.snapshot_cash_balance),
                "reserved": str(source.snapshot_reserved_capital),
                "committed": str(source.snapshot_committed_capital),
                "available": str(source.snapshot_available_bankroll),
                "realized_pnl": str(source.snapshot_realized_pnl),
            },
            "canonical portfolio accounting equations",
            "latest portfolio balances must satisfy the canonical equations",
        )
        check(
            "proposal_balance_matches_snapshot",
            source.proposal_available_bankroll == source.snapshot_available_bankroll,
            str(source.proposal_available_bankroll),
            str(source.snapshot_available_bankroll),
            "proposal bankroll denominator must match its authoritative snapshot",
        )
        capital_valid = (
            source.proposed_capital > 0
            and source.snapshot_available_bankroll > 0
            and source.proposed_capital <= source.snapshot_available_bankroll
        )
        check(
            "individual_bankroll_sufficient",
            capital_valid,
            {
                "proposed_capital": str(source.proposed_capital),
                "available_bankroll": str(source.snapshot_available_bankroll),
            },
            "0 < proposed_capital <= available_bankroll",
            "proposal must fit inside the current available bankroll",
        )
        recomputed_exposure = self._recompute_exposure(source)
        exposure_valid = (
            source.proposed_exposure_fraction > 0
            and source.proposed_exposure_fraction <= 1
            and recomputed_exposure == source.proposed_exposure_fraction
        )
        check(
            "proposal_exposure_valid",
            exposure_valid,
            {
                "stored": str(source.proposed_exposure_fraction),
                "recomputed": str(recomputed_exposure),
            },
            "0 < exposure <= 1 and equals capital/current available bankroll",
            "stored exposure must be valid and reproducible",
        )
        remaining = source.snapshot_available_bankroll - source.current_authorized_capital
        aggregate_valid = (
            source.current_authorized_capital >= 0
            and remaining >= 0
            and source.proposed_capital <= remaining
        )
        check(
            "aggregate_bankroll_sufficient",
            aggregate_valid,
            {
                "authorized_capital": str(source.current_authorized_capital),
                "remaining": str(remaining),
                "proposed_capital": str(source.proposed_capital),
            },
            "authorized_capital + proposed_capital <= available_bankroll",
            "current unexpired automatic authorizations must leave enough capital",
        )
        check(
            "current_trade_candidate",
            source.opportunity_is_current and source.opportunity_status == "trade_candidate",
            {
                "is_current": source.opportunity_is_current,
                "status": source.opportunity_status,
            },
            {"is_current": True, "status": "trade_candidate"},
            "proposal must still reference the exact current trade candidate",
        )
        check(
            "proposal_source_consistent",
            source.proposal_source_is_consistent,
            source.proposal_source_is_consistent,
            True,
            "copied proposal fields and fingerprints must match the source opportunity",
        )
        check(
            "opportunity_semantics_current",
            source.opportunity_semantics_are_current,
            source.opportunity_semantics_are_current,
            True,
            "event fingerprint and outcome orientation must remain current",
        )
        market_open = source.market_status in {"active", "open"} and (
            source.market_close_time is None or source.market_close_time > source.evaluated_at
        )
        check(
            "market_open",
            market_open,
            {
                "status": source.market_status,
                "close_time": (
                    source.market_close_time.isoformat()
                    if source.market_close_time is not None
                    else None
                ),
            },
            "active/open and not closed",
            "market must be valid and open",
        )
        event_open = (
            source.event_status == "scheduled"
            and not source.event_postponed
            and source.event_start_time > source.evaluated_at
        )
        check(
            "event_not_started",
            event_open,
            {
                "status": source.event_status,
                "postponed": source.event_postponed,
                "start_time": source.event_start_time.isoformat(),
            },
            "scheduled, not postponed, and starts after evaluation",
            "underlying event must remain eligible for pregame entry",
        )
        match_current = (
            source.source_match_id == source.latest_match_id
            and source.latest_match_status == "matched"
            and source.latest_match_eligible
        )
        check(
            "eligible_current_match",
            match_current,
            {
                "source_id": str(source.source_match_id),
                "latest_id": str(source.latest_match_id),
                "status": source.latest_match_status,
                "eligible": source.latest_match_eligible,
            },
            "exact latest matched and automatically eligible record",
            "market-to-event match must remain current and unambiguous",
        )
        check(
            "minimum_match_confidence",
            source.latest_match_confidence >= self.policy.min_match_confidence,
            str(source.latest_match_confidence),
            str(self.policy.min_match_confidence),
            "match confidence must meet the risk-policy minimum",
        )
        price_current = source.source_market_price_id == source.latest_market_price_id
        check(
            "current_market_price",
            price_current,
            str(source.source_market_price_id),
            str(source.latest_market_price_id),
            "proposal must reference the latest market-price snapshot",
        )
        price_age = int((source.evaluated_at - source.market_price_retrieved_at).total_seconds())
        check(
            "fresh_market_price",
            0 <= price_age <= self.policy.max_market_price_age_seconds,
            price_age,
            f"0..{self.policy.max_market_price_age_seconds}",
            "market price must not be future-dated or stale",
        )
        forecast_current = source.source_forecast_id == source.latest_operational_forecast_id
        check(
            "current_operational_forecast",
            forecast_current,
            str(source.source_forecast_id),
            str(source.latest_operational_forecast_id),
            "proposal must reference the latest operational forecast for its model",
        )
        forecast_age = int((source.evaluated_at - source.forecast_generated_at).total_seconds())
        check(
            "fresh_operational_forecast",
            0 <= forecast_age <= self.policy.max_operational_forecast_age_seconds,
            forecast_age,
            f"0..{self.policy.max_operational_forecast_age_seconds}",
            "operational forecast must not be future-dated or stale",
        )
        edge_consistent = source.raw_edge == source.model_probability - source.reference_price
        check(
            "raw_edge_consistent",
            edge_consistent,
            {
                "raw_edge": str(source.raw_edge),
                "model_probability": str(source.model_probability),
                "reference_price": str(source.reference_price),
            },
            "raw_edge = model_probability - reference_price",
            "raw edge must reproduce from proposal probabilities",
        )
        required_edge = max(
            self.policy.min_raw_edge,
            source.opportunity_trade_candidate_min_raw_edge,
        )
        check(
            "minimum_raw_edge",
            source.raw_edge >= required_edge,
            str(source.raw_edge),
            str(required_edge),
            "raw edge must meet both opportunity and risk thresholds",
        )
        check(
            "confidence_basis_supported",
            source.confidence_basis == "not_available",
            source.confidence_basis,
            "not_available",
            "Phase 7 must not infer confidence from raw edge",
        )
        check(
            "duplicate_active_intent_absent",
            not source.duplicate_active_intent_exists,
            source.duplicate_active_intent_exists,
            False,
            "another current authorization or escalation must not cover the same intent",
        )

        failed_rules = tuple(item.rule for item in checks if not item.passed)
        if failed_rules:
            decision = RiskDecisionType.REJECT
            band = RiskEscalationBand.HARD_REJECTION
            primary_reason = failed_rules[0]
            reason = "risk hard checks failed: " + ", ".join(failed_rules)
            valid_until = None
        elif source.proposed_exposure_fraction < self.policy.auto_approve_exposure_max:
            decision = RiskDecisionType.AUTO_APPROVE
            band = RiskEscalationBand.AUTOMATIC
            primary_reason = "all_checks_passed_below_auto_exposure"
            reason = "all hard checks passed and exposure is below the automatic boundary"
            valid_until = self._authorization_valid_until(source)
        elif source.proposed_exposure_fraction <= self.policy.high_confidence_auto_approve_max:
            decision = RiskDecisionType.REQUIRE_HUMAN_APPROVAL
            band = RiskEscalationBand.MEDIUM_CONFIDENCE_UNAVAILABLE
            primary_reason = "confidence_unavailable_for_medium_exposure"
            reason = "exposure is at least 10% and calibrated confidence is unavailable"
            valid_until = self._authorization_valid_until(source)
        else:
            decision = RiskDecisionType.REQUIRE_HUMAN_APPROVAL
            band = RiskEscalationBand.LARGE_EXPOSURE
            primary_reason = "large_exposure_requires_human_approval"
            reason = "exposure is above the 40% human-approval boundary"
            valid_until = self._authorization_valid_until(source)

        semantic_source = source.model_dump(mode="json", exclude={"evaluated_at"})
        authorization_window = (
            self._authorization_window_start(source.evaluated_at).isoformat()
            if not failed_rules
            else None
        )
        input_fingerprint = _canonical_hash(
            {
                "source": semantic_source,
                "policy_fingerprint": self.policy_fingerprint,
                "check_outcomes": [{"rule": item.rule, "passed": item.passed} for item in checks],
                "decision": decision.value,
                "authorization_window": authorization_window,
            }
        )
        audit_snapshot = {
            "proposal": {
                "id": str(source.proposal_id),
                "strategy_name": source.proposal_strategy_name,
                "strategy_version": source.proposal_strategy_version,
                "input_fingerprint": source.proposal_input_fingerprint,
                "proposed_capital": str(source.proposed_capital),
                "proposed_exposure_fraction": str(source.proposed_exposure_fraction),
            },
            "portfolio": {
                "id": str(source.portfolio_id),
                "snapshot_id": str(source.latest_snapshot_id),
                "state_fingerprint": source.snapshot_state_fingerprint,
                "available_bankroll": str(source.snapshot_available_bankroll),
                "current_authorized_capital": str(source.current_authorized_capital),
                "remaining_authorizable_bankroll": str(remaining),
            },
            "sources": {
                "opportunity_id": str(source.opportunity_id),
                "opportunity_input_fingerprint": source.opportunity_input_fingerprint,
                "market_id": str(source.market_id),
                "match_id": str(source.latest_match_id),
                "market_price_id": str(source.latest_market_price_id),
                "forecast_id": str(source.latest_operational_forecast_id),
                "price_age_seconds": price_age,
                "forecast_age_seconds": forecast_age,
            },
            "limitations": {
                "edge_basis": "raw_edge",
                "adjusted_edge": "not_available",
                "confidence": "not_available",
                "liquidity": "not_evaluated_phase7",
                "existing_positions": "same_portfolio_market_open_position_gate_phase8",
            },
            "checks": [item.model_dump(mode="json") for item in checks],
        }
        return RiskDecision(
            position_size_proposal_id=source.proposal_id,
            portfolio_id=source.portfolio_id,
            portfolio_snapshot_id=source.latest_snapshot_id,
            opportunity_id=source.opportunity_id,
            market_id=source.market_id,
            outcome_team_id=source.outcome_team_id,
            direction=source.direction,
            execution_mode="paper",
            decision=decision,
            escalation_band=band,
            primary_reason_code=primary_reason,
            reason=reason,
            all_required_checks_passed=not failed_rules,
            hard_failure_count=len(failed_rules),
            failed_rules=failed_rules,
            check_results=tuple(checks),
            proposed_capital=source.proposed_capital,
            proposal_available_bankroll=source.proposal_available_bankroll,
            current_available_bankroll=source.snapshot_available_bankroll,
            current_authorized_capital=source.current_authorized_capital,
            remaining_authorizable_bankroll=remaining,
            proposed_exposure_fraction=source.proposed_exposure_fraction,
            recomputed_exposure_fraction=recomputed_exposure,
            reference_price=source.reference_price,
            model_probability=source.model_probability,
            raw_edge=source.raw_edge,
            match_confidence=source.latest_match_confidence,
            market_price_age_seconds=price_age,
            forecast_age_seconds=forecast_age,
            risk_policy_name=self.policy.policy_name,
            risk_policy_version=self.policy_version,
            risk_policy_fingerprint=self.policy_fingerprint,
            auto_approve_exposure_max=self.policy.auto_approve_exposure_max,
            high_confidence_auto_approve_max=(self.policy.high_confidence_auto_approve_max),
            min_raw_edge=self.policy.min_raw_edge,
            min_match_confidence=self.policy.min_match_confidence,
            max_market_price_age_seconds=self.policy.max_market_price_age_seconds,
            max_operational_forecast_age_seconds=(self.policy.max_operational_forecast_age_seconds),
            authorization_ttl_seconds=self.policy.authorization_ttl_seconds,
            proposal_strategy_name=source.proposal_strategy_name,
            proposal_strategy_version=source.proposal_strategy_version,
            proposal_input_fingerprint=source.proposal_input_fingerprint,
            opportunity_input_fingerprint=source.opportunity_input_fingerprint,
            input_fingerprint=input_fingerprint,
            evaluated_at=source.evaluated_at,
            authorization_valid_until=valid_until,
            audit_snapshot=audit_snapshot,
        )

    def _recompute_exposure(self, source: RiskEvaluationInput) -> Decimal:
        if source.snapshot_available_bankroll <= 0 or source.proposed_capital <= 0:
            return Decimal("0.0000000000")
        return (source.proposed_capital / source.snapshot_available_bankroll).quantize(
            _EXPOSURE_QUANTUM,
            rounding=ROUND_DOWN,
        )

    def _authorization_window_start(self, evaluated_at: datetime) -> datetime:
        ttl = self.policy.authorization_ttl_seconds
        epoch_seconds = int(evaluated_at.timestamp())
        return datetime.fromtimestamp(epoch_seconds - (epoch_seconds % ttl), tz=evaluated_at.tzinfo)

    def _authorization_valid_until(self, source: RiskEvaluationInput) -> datetime:
        window_start = self._authorization_window_start(source.evaluated_at)
        candidates = [
            window_start + timedelta(seconds=self.policy.authorization_ttl_seconds),
            source.opportunity_valid_until,
            source.event_start_time,
            source.market_price_retrieved_at
            + timedelta(seconds=self.policy.max_market_price_age_seconds),
            source.forecast_generated_at
            + timedelta(seconds=self.policy.max_operational_forecast_age_seconds),
        ]
        if source.market_close_time is not None:
            candidates.append(source.market_close_time)
        return min(candidates)

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
                str(key): DeterministicRiskEngine._json_value(item) for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [DeterministicRiskEngine._json_value(item) for item in value]
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)
