from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain.portfolio import (
    PortfolioSnapshot,
    PortfolioSnapshotReason,
    PositionSizeProposal,
    PositionSizingInput,
    PositionSizingPolicy,
)
from app.services.position_sizing.engine import (
    RulesPositionSizer,
    effective_sizing_strategy_version,
    sizing_policy_fingerprint,
)

NOW = datetime(2026, 8, 11, 12, tzinfo=UTC)
PORTFOLIO_ID = UUID("60000000-0000-0000-0000-000000000001")
SNAPSHOT_ID = UUID("60000000-0000-0000-0000-000000000002")
OPPORTUNITY_ID = UUID("60000000-0000-0000-0000-000000000003")


def snapshot(available: Decimal = Decimal("1000.00")) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        id=SNAPSHOT_ID,
        portfolio_id=PORTFOLIO_ID,
        sequence=0,
        starting_bankroll=available,
        current_bankroll=available,
        cash_balance=available,
        reserved_capital=Decimal("0.00"),
        committed_capital=Decimal("0.00"),
        available_bankroll=available,
        realized_pnl=Decimal("0.00"),
        reason=PortfolioSnapshotReason.CREATED,
        state_fingerprint="a" * 64,
        captured_at=NOW,
    )


def sizing_input(
    *,
    raw_edge: Decimal,
    available: Decimal = Decimal("1000.00"),
    status: str = "trade_candidate",
    proposed_at: datetime = NOW,
) -> PositionSizingInput:
    reference_price = Decimal("0.500000")
    return PositionSizingInput(
        portfolio_snapshot_id=SNAPSHOT_ID,
        portfolio=snapshot(available),
        opportunity_id=OPPORTUNITY_ID,
        market_id=UUID("60000000-0000-0000-0000-000000000004"),
        outcome_team_id=UUID("60000000-0000-0000-0000-000000000005"),
        direction="yes",
        reference_price=reference_price,
        model_probability=reference_price + raw_edge,
        raw_edge=raw_edge,
        opportunity_status=status,
        opportunity_strategy_name="raw_edge",
        opportunity_strategy_version="1.0.0+cfg.abcdef123456",
        opportunity_input_fingerprint="b" * 64,
        opportunity_evaluated_at=NOW - timedelta(minutes=1),
        opportunity_valid_until=NOW + timedelta(minutes=10),
        proposed_at=proposed_at,
        source_snapshot={"price": {"yes_ask": "0.500000"}},
    )


@pytest.mark.parametrize(
    ("edge", "expected_capital", "expected_exposure", "expected_band"),
    [
        (Decimal("0.080000"), Decimal("20.00"), Decimal("0.0200000000"), "candidate"),
        (Decimal("0.119999"), Decimal("20.00"), Decimal("0.0200000000"), "candidate"),
        (Decimal("0.120000"), Decimal("50.00"), Decimal("0.0500000000"), "strong"),
        (Decimal("0.179999"), Decimal("50.00"), Decimal("0.0500000000"), "strong"),
        (
            Decimal("0.180000"),
            Decimal("80.00"),
            Decimal("0.0800000000"),
            "very_strong",
        ),
    ],
)
def test_rules_v1_exact_boundaries(
    edge: Decimal,
    expected_capital: Decimal,
    expected_exposure: Decimal,
    expected_band: str,
) -> None:
    evaluation = RulesPositionSizer(PositionSizingPolicy()).evaluate(sizing_input(raw_edge=edge))

    assert evaluation.skip_reason is None
    assert evaluation.proposal is not None
    assert evaluation.proposal.proposed_capital == expected_capital
    assert evaluation.proposal.proposed_exposure_fraction == expected_exposure
    sizing_audit = cast(dict[str, object], evaluation.proposal.audit_snapshot["sizing"])
    assert sizing_audit["band"] == expected_band
    assert evaluation.proposal.state.value == "awaiting_risk"
    assert evaluation.proposal.confidence_basis.value == "not_available"


def test_below_threshold_and_non_candidate_do_not_propose() -> None:
    sizer = RulesPositionSizer(PositionSizingPolicy())

    below = sizer.evaluate(sizing_input(raw_edge=Decimal("0.079999")))
    watch = sizer.evaluate(sizing_input(raw_edge=Decimal("0.090000"), status="watch"))

    assert below.proposal is None
    assert below.skip_reason == "below_sizing_edge_threshold"
    assert watch.proposal is None
    assert watch.skip_reason == "not_trade_candidate"


def test_money_is_rounded_down_and_actual_exposure_uses_rounded_capital() -> None:
    policy = PositionSizingPolicy(
        candidate_exposure_fraction=Decimal("0.030000"),
        strong_exposure_fraction=Decimal("0.050000"),
        very_strong_exposure_fraction=Decimal("0.080000"),
    )

    proposal = (
        RulesPositionSizer(policy)
        .evaluate(sizing_input(raw_edge=Decimal("0.080000"), available=Decimal("100.01")))
        .proposal
    )

    assert proposal is not None
    assert proposal.proposed_capital == Decimal("3.00")
    assert proposal.proposed_exposure_fraction == Decimal("0.0299970002")
    assert proposal.proposed_exposure_fraction < proposal.target_exposure_fraction


def test_tiny_bankroll_safely_skips_below_one_cent() -> None:
    result = RulesPositionSizer(PositionSizingPolicy()).evaluate(
        sizing_input(raw_edge=Decimal("0.080000"), available=Decimal("0.01"))
    )

    assert result.proposal is None
    assert result.skip_reason == "below_minimum_currency_unit"


def test_semantic_identity_ignores_proposal_time_and_policy_changes_version() -> None:
    baseline = PositionSizingPolicy()
    changed = baseline.model_copy(update={"candidate_exposure_fraction": Decimal("0.030000")})
    first = (
        RulesPositionSizer(baseline)
        .evaluate(sizing_input(raw_edge=Decimal("0.080000"), proposed_at=NOW))
        .proposal
    )
    rerun = (
        RulesPositionSizer(baseline)
        .evaluate(
            sizing_input(raw_edge=Decimal("0.080000"), proposed_at=NOW + timedelta(minutes=1))
        )
        .proposal
    )

    assert first is not None and rerun is not None
    assert first.input_fingerprint == rerun.input_fingerprint
    assert sizing_policy_fingerprint(changed) != sizing_policy_fingerprint(baseline)
    assert effective_sizing_strategy_version(changed) != effective_sizing_strategy_version(baseline)


def test_snapshot_accounting_and_policy_bounds_are_validated() -> None:
    with pytest.raises(ValidationError, match="available bankroll"):
        PortfolioSnapshot.model_validate(
            {
                **snapshot().model_dump(),
                "available_bankroll": Decimal("999.00"),
            }
        )
    with pytest.raises(ValidationError, match="edge bands"):
        PositionSizingPolicy(strong_min_raw_edge=Decimal("0.08"))
    with pytest.raises(ValidationError, match="below 10%"):
        PositionSizingPolicy(max_exposure_fraction=Decimal("0.10"))


def test_proposal_representation_supports_future_risk_escalation_bands() -> None:
    baseline = (
        RulesPositionSizer(PositionSizingPolicy())
        .evaluate(sizing_input(raw_edge=Decimal("0.180000")))
        .proposal
    )
    assert baseline is not None

    future_strategy_proposal = PositionSizeProposal.model_validate(
        {
            **baseline.model_dump(mode="python"),
            "target_exposure_fraction": Decimal("0.40"),
            "proposed_exposure_fraction": Decimal("0.4000000000"),
            "proposed_capital": Decimal("400.00"),
            "candidate_exposure_fraction": Decimal("0.10"),
            "strong_exposure_fraction": Decimal("0.20"),
            "very_strong_exposure_fraction": Decimal("0.40"),
            "max_exposure_fraction": Decimal("0.40"),
        }
    )

    assert future_strategy_proposal.proposed_exposure_fraction == Decimal("0.4000000000")
    with pytest.raises(ValidationError, match="below 10%"):
        PositionSizingPolicy(max_exposure_fraction=Decimal("0.40"))


def test_expired_or_inconsistent_opportunity_input_is_rejected() -> None:
    with pytest.raises(ValidationError, match="expired"):
        sizing_input(
            raw_edge=Decimal("0.080000"),
            proposed_at=NOW + timedelta(minutes=11),
        )
    with pytest.raises(ValidationError, match="raw edge"):
        PositionSizingInput.model_validate(
            {
                **sizing_input(raw_edge=Decimal("0.080000")).model_dump(),
                "model_probability": Decimal("0.590000"),
            }
        )
    with pytest.raises(ValidationError, match="must match the embedded snapshot"):
        PositionSizingInput.model_validate(
            {
                **sizing_input(raw_edge=Decimal("0.080000")).model_dump(),
                "portfolio_snapshot_id": UUID("60000000-0000-0000-0000-000000000099"),
            }
        )
