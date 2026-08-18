from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from app.domain.execution import (
    PaperExecutionInput,
    PaperExecutionPolicy,
    PaperMarkBasis,
    PaperTradeStatus,
)
from app.services.execution.engine import (
    ImmediatePaperExecutionEngine,
    effective_paper_execution_policy_version,
    paper_execution_policy_fingerprint,
)

NOW = datetime(2026, 8, 17, 12, 2, tzinfo=UTC)


def execution_input(**changes: object) -> PaperExecutionInput:
    values: dict[str, object] = {
        "risk_decision_id": UUID("85000000-0000-0000-0000-000000000001"),
        "position_size_proposal_id": UUID("85000000-0000-0000-0000-000000000002"),
        "portfolio_id": UUID("85000000-0000-0000-0000-000000000003"),
        "portfolio_snapshot_id": UUID("85000000-0000-0000-0000-000000000004"),
        "opportunity_id": UUID("85000000-0000-0000-0000-000000000005"),
        "market_id": UUID("85000000-0000-0000-0000-000000000006"),
        "outcome_team_id": UUID("85000000-0000-0000-0000-000000000007"),
        "market_event_match_id": UUID("85000000-0000-0000-0000-000000000008"),
        "market_price_id": UUID("85000000-0000-0000-0000-000000000009"),
        "base_forecast_id": UUID("85000000-0000-0000-0000-000000000010"),
        "direction": "yes",
        "runtime_trading_mode": "paper",
        "risk_execution_mode": "paper",
        "risk_decision": "auto_approve",
        "risk_all_required_checks_passed": True,
        "risk_is_latest": True,
        "risk_policy_is_active": True,
        "risk_revalidation_decision": "auto_approve",
        "risk_input_fingerprint": "a" * 64,
        "revalidated_risk_input_fingerprint": "a" * 64,
        "authorization_valid_until": NOW + timedelta(minutes=3),
        "no_prior_execution": True,
        "no_open_market_position": True,
        "latest_snapshot_id": UUID("85000000-0000-0000-0000-000000000004"),
        "current_available_bankroll": Decimal("1000.00"),
        "proposed_capital": Decimal("20.00"),
        "reference_price": Decimal("0.550000"),
        "current_directional_ask": Decimal("0.550000"),
        "current_directional_bid": Decimal("0.530000"),
        "model_probability": Decimal("0.640000"),
        "raw_edge": Decimal("0.090000"),
        "minimum_adjusted_edge": Decimal("0.080000"),
        "attempted_at": NOW,
    }
    values.update(changes)
    return PaperExecutionInput.model_validate(values)


def test_immediate_fill_uses_additive_slippage_fees_and_whole_contracts() -> None:
    decision = ImmediatePaperExecutionEngine(PaperExecutionPolicy()).evaluate(execution_input())

    assert decision.status is PaperTradeStatus.FILLED
    assert decision.execution_price == Decimal("0.552500")
    assert decision.requested_quantity == decision.executed_quantity == 36
    assert decision.reference_gross_cost == Decimal("19.80")
    assert decision.gross_cost == Decimal("19.89")
    assert decision.slippage_cost == Decimal("0.09")
    assert decision.fee_amount == Decimal("0.02")
    assert decision.total_cost == Decimal("19.91")
    assert decision.unused_capital == Decimal("0.09")
    assert decision.effective_unit_cost == Decimal("0.553056")
    assert decision.adjusted_edge == Decimal("0.086944")
    assert decision.mark_basis is PaperMarkBasis.DIRECTIONAL_BID
    assert decision.market_value == Decimal("19.08")
    assert decision.unrealized_pnl == Decimal("-0.83")


def test_directional_ask_and_mark_are_never_synthesized_from_other_side() -> None:
    decision = ImmediatePaperExecutionEngine(
        PaperExecutionPolicy(slippage_bps=Decimal("0"), fee_bps=Decimal("0"))
    ).evaluate(
        execution_input(
            direction="no",
            reference_price=Decimal("0.470000"),
            current_directional_ask=Decimal("0.470000"),
            current_directional_bid=Decimal("0.450000"),
            model_probability=Decimal("0.560000"),
            raw_edge=Decimal("0.090000"),
        )
    )

    assert decision.status is PaperTradeStatus.FILLED
    assert decision.execution_price == Decimal("0.470000")
    assert decision.executed_quantity == 42
    assert decision.mark_price == Decimal("0.450000")


def test_missing_bid_uses_explicit_non_executable_ask_fallback_mark() -> None:
    decision = ImmediatePaperExecutionEngine(PaperExecutionPolicy()).evaluate(
        execution_input(current_directional_bid=None)
    )

    assert decision.status is PaperTradeStatus.FILLED
    assert decision.mark_basis is PaperMarkBasis.DIRECTIONAL_ASK_FALLBACK
    assert decision.mark_price == Decimal("0.550000")


def test_cent_rounded_fee_never_overdraws_authorized_capital() -> None:
    decision = ImmediatePaperExecutionEngine(
        PaperExecutionPolicy(slippage_bps=Decimal("0"), fee_bps=Decimal("100.00"))
    ).evaluate(
        execution_input(
            proposed_capital=Decimal("1.00"),
            reference_price=Decimal("0.490000"),
            current_directional_ask=Decimal("0.490000"),
            current_directional_bid=Decimal("0.480000"),
            model_probability=Decimal("0.600000"),
            raw_edge=Decimal("0.110000"),
        )
    )

    assert decision.status is PaperTradeStatus.FILLED
    assert decision.requested_quantity == 2
    assert decision.executed_quantity == 2
    assert decision.gross_cost == Decimal("0.98")
    assert decision.fee_amount == Decimal("0.01")
    assert decision.total_cost == Decimal("0.99")


def test_expiry_equality_and_nonautomatic_decisions_are_rejected() -> None:
    engine = ImmediatePaperExecutionEngine(PaperExecutionPolicy())
    expired = engine.evaluate(execution_input(authorization_valid_until=NOW))
    human = engine.evaluate(
        execution_input(
            risk_decision="require_human_approval",
            risk_all_required_checks_passed=True,
        )
    )

    assert expired.status is PaperTradeStatus.REJECTED
    assert expired.failed_rules == ("risk_authorization_unexpired",)
    assert human.status is PaperTradeStatus.REJECTED
    assert "automatic_risk_authorization" in human.failed_rules


def test_changed_snapshot_or_risk_fingerprint_fails_closed() -> None:
    decision = ImmediatePaperExecutionEngine(PaperExecutionPolicy()).evaluate(
        execution_input(
            latest_snapshot_id=UUID("85000000-0000-0000-0000-000000000099"),
            revalidated_risk_input_fingerprint="b" * 64,
        )
    )

    assert decision.status is PaperTradeStatus.REJECTED
    assert decision.failed_rules == (
        "exact_risk_revalidation",
        "latest_portfolio_snapshot",
    )


def test_invalid_book_or_slippage_at_one_dollar_is_rejected() -> None:
    engine = ImmediatePaperExecutionEngine(PaperExecutionPolicy())
    crossed = engine.evaluate(execution_input(current_directional_bid=Decimal("0.560000")))
    at_one = engine.evaluate(
        execution_input(
            reference_price=Decimal("0.999000"),
            current_directional_ask=Decimal("0.999000"),
            current_directional_bid=Decimal("0.998000"),
            model_probability=Decimal("1.000000"),
            raw_edge=Decimal("0.001000"),
            minimum_adjusted_edge=Decimal("0.000000"),
        )
    )

    assert crossed.failed_rules == ("valid_current_directional_book",)
    assert at_one.failed_rules == ("execution_price_below_one",)


def test_costs_that_destroy_edge_or_cannot_buy_one_contract_are_rejected() -> None:
    engine = ImmediatePaperExecutionEngine(PaperExecutionPolicy())
    lost_edge = engine.evaluate(
        execution_input(model_probability=Decimal("0.630000"), raw_edge=Decimal("0.080000"))
    )
    too_small = engine.evaluate(execution_input(proposed_capital=Decimal("0.01")))

    assert lost_edge.failed_rules == ("minimum_adjusted_edge",)
    assert too_small.failed_rules == ("minimum_one_contract",)


def test_execution_policy_identity_changes_with_effective_costs() -> None:
    baseline = PaperExecutionPolicy()
    changed = PaperExecutionPolicy(fee_bps=Decimal("20.00"))

    assert paper_execution_policy_fingerprint(baseline) != paper_execution_policy_fingerprint(
        changed
    )
    assert effective_paper_execution_policy_version(
        baseline
    ) != effective_paper_execution_policy_version(changed)
