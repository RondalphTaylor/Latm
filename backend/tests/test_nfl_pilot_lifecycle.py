from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pytest

from app.models.markets import MarketPriceRecord, MarketResolutionRecord
from app.models.nfl_forecasting import NflPayoutForecastRecord
from app.models.nfl_pilot import NflPilotPositionRecord
from app.services.nfl_pilot.lifecycle import (
    _disposition_plan,
    _floor_cent,
    _official_resolution,
    _quote_assessment,
    _recommendation,
)


def test_reduce_disposition_uses_a_deterministic_majority_half_and_preserves_cost() -> None:
    position = SimpleNamespace(
        status="open",
        remaining_quantity=3,
        remaining_cost_basis=Decimal("1.00"),
    )
    plan = _disposition_plan(cast(NflPilotPositionRecord, position), "reduce")
    assert (plan.action, plan.quantity, plan.allocated_cost_basis) == (
        "reduce",
        2,
        Decimal("0.66"),
    )


def test_reduce_of_one_contract_becomes_a_full_paper_close() -> None:
    position = SimpleNamespace(
        status="open",
        remaining_quantity=1,
        remaining_cost_basis=Decimal("0.51"),
    )
    plan = _disposition_plan(cast(NflPilotPositionRecord, position), "reduce")
    assert (plan.action, plan.quantity, plan.allocated_cost_basis) == (
        "close",
        1,
        Decimal("0.51"),
    )


def test_nfl_pilot_lifecycle_floors_fractional_contract_payouts_to_cents() -> None:
    assert _floor_cent(Decimal("3") * Decimal("0.333333")) == Decimal("0.99")
    assert _floor_cent(Decimal("3") * Decimal("0.500000")) == Decimal("1.50")


def test_nfl_pilot_lifecycle_never_rounds_mark_value_up() -> None:
    assert _floor_cent(Decimal("4") * Decimal("0.412500")) == Decimal("1.65")


def test_official_fractional_resolution_rejects_conflicts() -> None:
    now = datetime(2026, 9, 12, tzinfo=UTC)
    fractional = SimpleNamespace(
        yes_payout=Decimal("0.333333"),
        no_payout=Decimal("0.666667"),
        source="official_provider",
        settled_at=now,
        retrieved_at=now,
    )
    assert _official_resolution([cast(MarketResolutionRecord, fractional)]).yes_payout == Decimal(
        "0.333333"
    )
    conflicting = SimpleNamespace(
        yes_payout=Decimal("0.500000"),
        no_payout=Decimal("0.500000"),
        source="official_provider",
        settled_at=now,
        retrieved_at=now,
    )
    with pytest.raises(ValueError, match="conflicting"):
        _official_resolution(
            [
                cast(MarketResolutionRecord, fractional),
                cast(MarketResolutionRecord, conflicting),
            ]
        )


def test_quote_assessment_requires_fresh_two_sided_directional_quote() -> None:
    now = datetime(2026, 9, 12, 12, tzinfo=UTC)
    fresh_price = SimpleNamespace(
        yes_bid=Decimal("0.400000"),
        yes_ask=Decimal("0.420000"),
        no_bid=Decimal("0.580000"),
        no_ask=Decimal("0.600000"),
        retrieved_at=datetime(2026, 9, 12, 11, 59, 30, tzinfo=UTC),
    )
    assessment = _quote_assessment(cast(MarketPriceRecord, fresh_price), "yes", now)
    assert assessment.quote_status == "fresh"
    assert assessment.spread == Decimal("0.020000")
    assert assessment.quote_age_seconds == 30


def test_quote_assessment_flags_stale_and_unusable_quotes() -> None:
    now = datetime(2026, 9, 12, 12, tzinfo=UTC)
    stale_price = SimpleNamespace(
        yes_bid=Decimal("0.400000"),
        yes_ask=Decimal("0.420000"),
        no_bid=None,
        no_ask=None,
        retrieved_at=datetime(2026, 9, 12, 11, 44, 59, tzinfo=UTC),
    )
    assert (
        _quote_assessment(cast(MarketPriceRecord, stale_price), "yes", now).quote_status == "stale"
    )
    unusable_price = SimpleNamespace(
        yes_bid=None,
        yes_ask=Decimal("0.420000"),
        no_bid=None,
        no_ask=None,
        retrieved_at=datetime(2026, 9, 12, 12, tzinfo=UTC),
    )
    assert (
        _quote_assessment(cast(MarketPriceRecord, unusable_price), "yes", now).quote_status
        == "unusable"
    )


def test_recommendation_holds_stale_forecast_and_flags_negative_edge() -> None:
    now = datetime(2026, 9, 12, 12, tzinfo=UTC)
    stale = SimpleNamespace(
        generated_at=datetime(2026, 9, 12, 11, 40, tzinfo=UTC),
        valid_until=datetime(2026, 9, 12, 11, 55, tzinfo=UTC),
        expected_yes_payout=Decimal("0.55"),
        expected_no_payout=Decimal("0.45"),
    )
    result = _recommendation(
        "fresh", cast(NflPayoutForecastRecord, stale), "yes", Decimal("0.40"), now
    )
    assert (result.recommendation, result.reason) == ("hold", "forecast_stale")
    current = SimpleNamespace(
        generated_at=now,
        valid_until=datetime(2026, 9, 12, 12, 15, tzinfo=UTC),
        expected_yes_payout=Decimal("0.40"),
        expected_no_payout=Decimal("0.60"),
    )
    result = _recommendation(
        "fresh", cast(NflPayoutForecastRecord, current), "yes", Decimal("0.41"), now
    )
    assert (result.recommendation, result.reason, result.remaining_edge) == (
        "close",
        "remaining_edge_nonpositive",
        Decimal("-0.010000"),
    )
