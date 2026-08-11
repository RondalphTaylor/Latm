from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain.opportunities import (
    OpportunityDirection,
    OpportunityEvaluationInput,
    OpportunityOutcomeInput,
    OpportunityPolicy,
    OpportunityPriceSource,
    OpportunityStatus,
    OpportunityTeamInput,
)
from app.services.opportunities.engine import (
    RawEdgeOpportunityEngine,
    effective_strategy_version,
    policy_fingerprint,
)
from app.services.opportunities.orientation import resolve_outcome_orientation

HOME_ID = UUID("144119bc-d1a9-4327-870c-207a9e03fe8e")
AWAY_ID = UUID("57eb99af-147a-4443-bc06-9be664503148")
YES_OUTCOME_ID = UUID("2477d197-6942-46d8-a4ea-da76fbef36af")
NO_OUTCOME_ID = UUID("c6507062-c59d-44e7-897b-c198b2028427")
NOW = datetime(2026, 8, 8, 12, tzinfo=UTC)


def team(team_id: UUID, abbreviation: str, city: str, name: str) -> OpportunityTeamInput:
    return OpportunityTeamInput(
        id=team_id,
        abbreviation=abbreviation,
        city=city,
        name=name,
        full_name=f"{city} {name}",
    )


HOME = team(HOME_ID, "BOS", "Boston", "Celtics")
AWAY = team(AWAY_ID, "NYK", "New York", "Knicks")


def outcomes(yes_label: str, no_label: str) -> tuple[OpportunityOutcomeInput, ...]:
    return (
        OpportunityOutcomeInput(
            id=YES_OUTCOME_ID,
            side=OpportunityDirection.YES,
            label=yes_label,
        ),
        OpportunityOutcomeInput(
            id=NO_OUTCOME_ID,
            side=OpportunityDirection.NO,
            label=no_label,
        ),
    )


def evaluation_input(
    *,
    market_probability: Decimal,
    model_probability: Decimal = Decimal("0.600000"),
    direction: OpportunityDirection = OpportunityDirection.YES,
    evaluated_at: datetime = NOW,
) -> OpportunityEvaluationInput:
    yes_team_id = HOME_ID
    no_team_id = AWAY_ID
    return OpportunityEvaluationInput(
        market_id=UUID("40d19d4f-817e-4b8e-b9fb-41ad7213d45f"),
        market_price_id=UUID("23e00bf9-a11d-45e5-abee-9b70968f20cc"),
        market_event_match_id=UUID("2fd39e2f-b7df-4691-8289-8240b5226255"),
        sports_event_id=UUID("c84aa6a1-8d4e-42d6-8333-2a92900393d4"),
        base_forecast_id=UUID("d4d2479c-7d13-4e52-8d75-0218af0acb65"),
        model_version_id=UUID("f917029b-a5e3-46ae-933e-d321f518f84f"),
        outcome_team_id=(yes_team_id if direction is OpportunityDirection.YES else no_team_id),
        yes_team_id=yes_team_id,
        no_team_id=no_team_id,
        direction=direction,
        price_source=(
            OpportunityPriceSource.DIRECT_YES_ASK
            if direction is OpportunityDirection.YES
            else OpportunityPriceSource.DIRECT_NO_ASK
        ),
        mapping_method="binary-event-winner-v1:distinct_outcome_labels",
        orientation_fingerprint="a" * 64,
        match_input_fingerprint="b" * 64,
        forecast_input_fingerprint="c" * 64,
        market_probability=market_probability,
        model_probability=model_probability,
        price_retrieved_at=evaluated_at - timedelta(minutes=5),
        forecast_generated_at=evaluated_at - timedelta(hours=1),
        valid_until=evaluated_at + timedelta(minutes=10),
        evaluated_at=evaluated_at,
        source_snapshot={"market_title": "Will Boston win?"},
    )


def test_orientation_maps_home_and_away_yes_labels() -> None:
    home_yes = resolve_outcome_orientation(
        home_team=HOME,
        away_team=AWAY,
        outcomes=outcomes("Boston Celtics", "New York Knicks"),
        market_title="Will Boston win the Pro Basketball game?",
        market_type="binary",
    )
    away_yes = resolve_outcome_orientation(
        home_team=HOME,
        away_team=AWAY,
        outcomes=outcomes("NYK", "BOS"),
        market_title="Will New York beat Boston?",
        market_type="binary",
    )

    assert home_yes is not None
    assert home_yes.yes_team_id == HOME_ID
    assert home_yes.no_team_id == AWAY_ID
    assert away_yes is not None
    assert away_yes.yes_team_id == AWAY_ID
    assert away_yes.no_team_id == HOME_ID


def test_orientation_can_infer_one_generic_complement_but_never_guess_both() -> None:
    inferred = resolve_outcome_orientation(
        home_team=HOME,
        away_team=AWAY,
        outcomes=outcomes("Boston", "No"),
        market_title="Will Boston win?",
        market_type="binary",
    )
    generic = resolve_outcome_orientation(
        home_team=HOME,
        away_team=AWAY,
        outcomes=outcomes("Yes", "No"),
        market_title="Will Boston win?",
        market_type="binary",
    )
    conflicting = resolve_outcome_orientation(
        home_team=HOME,
        away_team=AWAY,
        outcomes=outcomes("Boston", "Boston Celtics"),
        market_title="Will Boston win?",
        market_type="binary",
    )

    assert inferred is not None
    assert inferred.mapping_method.endswith("yes_label_with_inferred_no")
    assert generic is None
    assert conflicting is None


@pytest.mark.parametrize(
    ("title", "market_type"),
    [
        ("Will Boston win by 10 points?", "binary"),
        ("Boston at New York", "binary"),
        ("Will Boston win?", "scalar"),
        ("Will Boston win the championship?", "binary"),
    ],
)
def test_orientation_rejects_unsupported_or_unclear_propositions(
    title: str,
    market_type: str,
) -> None:
    assert (
        resolve_outcome_orientation(
            home_team=HOME,
            away_team=AWAY,
            outcomes=outcomes("Boston", "New York"),
            market_title=title,
            market_type=market_type,
        )
        is None
    )


@pytest.mark.parametrize(
    ("market_probability", "expected_status"),
    [
        (Decimal("0.570001"), OpportunityStatus.IGNORE),
        (Decimal("0.570000"), OpportunityStatus.WATCH),
        (Decimal("0.550000"), OpportunityStatus.WATCH),
        (Decimal("0.520000"), OpportunityStatus.TRADE_CANDIDATE),
        (Decimal("0.510000"), OpportunityStatus.TRADE_CANDIDATE),
        (Decimal("0.700000"), OpportunityStatus.IGNORE),
    ],
)
def test_raw_edge_threshold_boundaries_are_exact_and_signed(
    market_probability: Decimal,
    expected_status: OpportunityStatus,
) -> None:
    decision = RawEdgeOpportunityEngine(OpportunityPolicy()).evaluate(
        evaluation_input(market_probability=market_probability)
    )

    assert decision.raw_edge == Decimal("0.600000") - market_probability
    assert decision.status is expected_status
    assert decision.market_probability == market_probability


def test_no_direction_uses_its_own_ask_and_model_probability() -> None:
    decision = RawEdgeOpportunityEngine(OpportunityPolicy()).evaluate(
        evaluation_input(
            direction=OpportunityDirection.NO,
            market_probability=Decimal("0.430000"),
            model_probability=Decimal("0.400000"),
        )
    )

    assert decision.price_source is OpportunityPriceSource.DIRECT_NO_ASK
    assert decision.raw_edge == Decimal("-0.030000")
    assert decision.status is OpportunityStatus.IGNORE


def test_policy_and_input_fingerprints_are_deterministic_and_versioned() -> None:
    baseline = OpportunityPolicy()
    changed = baseline.model_copy(update={"watch_min_raw_edge": Decimal("0.040000")})
    source = evaluation_input(market_probability=Decimal("0.550000"))
    first = RawEdgeOpportunityEngine(baseline).evaluate(source)
    rerun = RawEdgeOpportunityEngine(baseline).evaluate(source)
    changed_decision = RawEdgeOpportunityEngine(changed).evaluate(source)

    assert first.input_fingerprint == rerun.input_fingerprint
    assert len(policy_fingerprint(baseline)) == 64
    assert policy_fingerprint(changed) != policy_fingerprint(baseline)
    assert effective_strategy_version(changed) != effective_strategy_version(baseline)
    assert changed_decision.input_fingerprint != first.input_fingerprint


def test_future_source_time_and_invalid_policy_fail_validation() -> None:
    source = evaluation_input(market_probability=Decimal("0.500000"))
    with pytest.raises(ValidationError, match="after evaluation"):
        OpportunityEvaluationInput.model_validate(
            {
                **source.model_dump(),
                "price_retrieved_at": NOW + timedelta(seconds=1),
            }
        )
    with pytest.raises(ValidationError, match="watch threshold"):
        OpportunityPolicy(
            watch_min_raw_edge=Decimal("0.080000"),
            trade_candidate_min_raw_edge=Decimal("0.080000"),
        )
