from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain.risk import (
    RiskDecisionType,
    RiskEvaluationInput,
    RiskPolicy,
)
from app.services.risk.engine import (
    DeterministicRiskEngine,
    effective_risk_policy_version,
    risk_policy_fingerprint,
)

NOW = datetime(2026, 8, 15, 12, 2, tzinfo=UTC)


def risk_input(
    *,
    exposure: Decimal = Decimal("0.0800000000"),
    available: Decimal = Decimal("100000000.00"),
    evaluated_at: datetime = NOW,
    **changes: object,
) -> RiskEvaluationInput:
    proposed_capital = (available * exposure).quantize(Decimal("0.01"))
    values: dict[str, object] = {
        "proposal_id": UUID("81000000-0000-0000-0000-000000000001"),
        "portfolio_id": UUID("81000000-0000-0000-0000-000000000002"),
        "proposal_snapshot_id": UUID("81000000-0000-0000-0000-000000000003"),
        "latest_snapshot_id": UUID("81000000-0000-0000-0000-000000000003"),
        "opportunity_id": UUID("81000000-0000-0000-0000-000000000004"),
        "market_id": UUID("81000000-0000-0000-0000-000000000005"),
        "outcome_team_id": UUID("81000000-0000-0000-0000-000000000006"),
        "direction": "yes",
        "runtime_trading_mode": "paper",
        "proposal_execution_mode": "paper",
        "proposal_state": "awaiting_risk",
        "confidence_basis": "not_available",
        "portfolio_execution_mode": "paper",
        "portfolio_status": "active",
        "portfolio_is_active": True,
        "proposal_strategy_name": "raw_edge_bands",
        "proposal_strategy_version": "1.0.0+cfg.active123456",
        "active_sizing_strategy_version": "1.0.0+cfg.active123456",
        "proposal_input_fingerprint": "a" * 64,
        "opportunity_input_fingerprint": "b" * 64,
        "proposal_source_is_consistent": True,
        "opportunity_is_current": True,
        "opportunity_semantics_are_current": True,
        "opportunity_status": "trade_candidate",
        "opportunity_trade_candidate_min_raw_edge": Decimal("0.080000"),
        "opportunity_valid_until": NOW + timedelta(minutes=10),
        "snapshot_state_fingerprint": "c" * 64,
        "snapshot_starting_bankroll": available,
        "snapshot_current_bankroll": available,
        "snapshot_cash_balance": available,
        "snapshot_reserved_capital": Decimal("0.00"),
        "snapshot_committed_capital": Decimal("0.00"),
        "snapshot_available_bankroll": available,
        "snapshot_realized_pnl": Decimal("0.00"),
        "proposal_available_bankroll": available,
        "proposed_capital": proposed_capital,
        "proposed_exposure_fraction": exposure,
        "current_authorized_capital": Decimal("0.00"),
        "duplicate_active_intent_exists": False,
        "reference_price": Decimal("0.500000"),
        "model_probability": Decimal("0.600000"),
        "raw_edge": Decimal("0.100000"),
        "market_status": "active",
        "market_close_time": NOW + timedelta(hours=2),
        "event_status": "scheduled",
        "event_postponed": False,
        "event_start_time": NOW + timedelta(hours=2),
        "source_match_id": UUID("81000000-0000-0000-0000-000000000007"),
        "latest_match_id": UUID("81000000-0000-0000-0000-000000000007"),
        "latest_match_status": "matched",
        "latest_match_eligible": True,
        "latest_match_confidence": Decimal("0.9900"),
        "source_market_price_id": UUID("81000000-0000-0000-0000-000000000008"),
        "latest_market_price_id": UUID("81000000-0000-0000-0000-000000000008"),
        "market_price_retrieved_at": NOW - timedelta(minutes=2),
        "source_forecast_id": UUID("81000000-0000-0000-0000-000000000009"),
        "latest_operational_forecast_id": UUID("81000000-0000-0000-0000-000000000009"),
        "forecast_generated_at": NOW - timedelta(minutes=10),
        "evaluated_at": evaluated_at,
    }
    values.update(changes)
    return RiskEvaluationInput.model_validate(values)


@pytest.mark.parametrize(
    ("exposure", "expected"),
    [
        (Decimal("0.0999999999"), RiskDecisionType.AUTO_APPROVE),
        (Decimal("0.1000000000"), RiskDecisionType.REQUIRE_HUMAN_APPROVAL),
        (Decimal("0.4000000000"), RiskDecisionType.REQUIRE_HUMAN_APPROVAL),
        (Decimal("0.4000000001"), RiskDecisionType.REQUIRE_HUMAN_APPROVAL),
    ],
)
def test_exact_exposure_boundaries(exposure: Decimal, expected: RiskDecisionType) -> None:
    decision = DeterministicRiskEngine(RiskPolicy()).evaluate(risk_input(exposure=exposure))

    assert decision.decision is expected
    assert decision.all_required_checks_passed is True
    assert decision.authorization_valid_until == datetime(2026, 8, 15, 12, 5, tzinfo=UTC)
    if exposure == Decimal("0.4000000001"):
        assert decision.primary_reason_code == "large_exposure_requires_human_approval"
    if Decimal("0.10") <= exposure <= Decimal("0.40"):
        assert decision.primary_reason_code == "confidence_unavailable_for_medium_exposure"


def test_hard_failures_override_small_exposure_and_collect_ordered_reasons() -> None:
    decision = DeterministicRiskEngine(RiskPolicy()).evaluate(
        risk_input(
            exposure=Decimal("0.02"),
            runtime_trading_mode="live",
            market_status="closed",
            duplicate_active_intent_exists=True,
        )
    )

    assert decision.decision is RiskDecisionType.REJECT
    assert decision.primary_reason_code == "runtime_paper_mode"
    assert decision.failed_rules == (
        "runtime_paper_mode",
        "market_open",
        "duplicate_active_intent_absent",
    )
    assert decision.authorization_valid_until is None


@pytest.mark.parametrize(
    ("changes", "failed_rule"),
    [
        ({"portfolio_is_active": False}, "active_paper_portfolio"),
        (
            {"latest_snapshot_id": UUID("81000000-0000-0000-0000-000000000099")},
            "latest_portfolio_snapshot",
        ),
        ({"proposal_source_is_consistent": False}, "proposal_source_consistent"),
        ({"opportunity_is_current": False}, "current_trade_candidate"),
        ({"opportunity_semantics_are_current": False}, "opportunity_semantics_current"),
        ({"latest_match_status": "ambiguous"}, "eligible_current_match"),
        ({"latest_match_confidence": Decimal("0.8999")}, "minimum_match_confidence"),
        (
            {"market_price_retrieved_at": NOW - timedelta(seconds=901)},
            "fresh_market_price",
        ),
        (
            {"forecast_generated_at": NOW - timedelta(seconds=86401)},
            "fresh_operational_forecast",
        ),
        ({"raw_edge": Decimal("0.070000")}, "raw_edge_consistent"),
        ({"duplicate_active_intent_exists": True}, "duplicate_active_intent_absent"),
    ],
)
def test_each_major_safety_failure_rejects(changes: dict[str, object], failed_rule: str) -> None:
    source = RiskEvaluationInput.model_validate(
        {**risk_input().model_dump(mode="python"), **changes}
    )
    decision = DeterministicRiskEngine(RiskPolicy()).evaluate(source)

    assert decision.decision is RiskDecisionType.REJECT
    assert failed_rule in decision.failed_rules


def test_aggregate_authorizations_cannot_overcommit_unreserved_bankroll() -> None:
    decision = DeterministicRiskEngine(RiskPolicy()).evaluate(
        risk_input(
            exposure=Decimal("0.08"),
            available=Decimal("1000.00"),
            current_authorized_capital=Decimal("920.01"),
        )
    )

    assert decision.decision is RiskDecisionType.REJECT
    assert "aggregate_bankroll_sufficient" in decision.failed_rules
    assert decision.remaining_authorizable_bankroll == Decimal("79.99")


def test_semantic_idempotence_uses_fixed_authorization_windows() -> None:
    engine = DeterministicRiskEngine(RiskPolicy())
    first = engine.evaluate(risk_input(evaluated_at=NOW))
    same_window = engine.evaluate(risk_input(evaluated_at=NOW + timedelta(minutes=1)))
    next_window = engine.evaluate(risk_input(evaluated_at=NOW + timedelta(minutes=3)))

    assert first.input_fingerprint == same_window.input_fingerprint
    assert first.input_fingerprint != next_window.input_fingerprint


def test_policy_identity_changes_with_effective_thresholds() -> None:
    baseline = RiskPolicy()
    changed = RiskPolicy(min_raw_edge=Decimal("0.0900000000"))

    assert risk_policy_fingerprint(baseline) != risk_policy_fingerprint(changed)
    assert effective_risk_policy_version(baseline) != effective_risk_policy_version(changed)
    with pytest.raises(ValidationError, match="must increase"):
        RiskPolicy(high_confidence_auto_approve_max=Decimal("0.10"))
