from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from app.domain.markets import MarketPrice
from app.domain.nfl_forecasting import NflPayoutForecastCandidate
from app.domain.nfl_opportunities import NflPaperOpportunityComparison, NflPaperOpportunityPolicy
from app.services.nfl_opportunities.engine import build_nfl_paper_opportunity_comparison
from app.services.nfl_research.shadow import NFL_SHADOW_SEED_FINGERPRINT, NFL_SHADOW_VERSION

NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)


def forecast() -> NflPayoutForecastCandidate:
    return NflPayoutForecastCandidate(
        match_id=UUID(int=1),
        market_id=UUID(int=2),
        event_id=UUID(int=3),
        home_team_id=UUID(int=4),
        away_team_id=UUID(int=5),
        yes_team_id=UUID(int=4),
        model_version=NFL_SHADOW_VERSION,
        seed_fingerprint=NFL_SHADOW_SEED_FINGERPRINT,
        source_shadow_snapshot_id=UUID(int=6),
        generated_at=NOW,
        valid_until=NOW + timedelta(minutes=15),
        expected_home_payout=Decimal(".6"),
        expected_away_payout=Decimal(".4"),
        expected_yes_payout=Decimal(".6"),
        expected_no_payout=Decimal(".4"),
        input_fingerprint="a" * 64,
    )


def compare(
    price: MarketPrice | None,
    *,
    now: datetime = NOW,
    candidate: NflPayoutForecastCandidate | None = None,
) -> NflPaperOpportunityComparison:
    return build_nfl_paper_opportunity_comparison(
        forecast=candidate or forecast(),
        forecast_id=UUID(int=7),
        latest_market_price_id=UUID(int=8) if price else None,
        market_price=price,
        evaluated_at=now,
    )


@pytest.mark.parametrize(
    "ask,status,edge",
    [
        (".570001", "ignore", ".029999"),
        (".57", "watch", ".03"),
        (".520001", "watch", ".079999"),
        (".52", "paper_candidate", ".08"),
        (".7", "ignore", "-.1"),
    ],
)
def test_exact_direct_ask_thresholds(ask: str, status: str, edge: str) -> None:
    result = compare(MarketPrice(yes_ask=Decimal(ask), retrieved_at=NOW))
    assert result.yes_status == status
    assert result.yes_raw_edge == Decimal(edge)
    assert result.no_status == "ineligible" and result.no_reason == "missing_side_ask"
    assert result.no_raw_edge is None


def test_no_side_is_independent_and_no_quotes_are_synthesized() -> None:
    result = compare(MarketPrice(no_ask=Decimal(".3"), last_price=Decimal(".2"), retrieved_at=NOW))
    assert result.no_raw_edge == Decimal(".1")
    assert result.yes_raw_edge is None
    assert result.yes_direct_ask is None
    assert result.execution_mode == "paper" and result.promotion_state == "blocked"
    assert not result.operational_eligible and not result.trading_enabled
    assert not result.costs_included and not result.depth_verified


@pytest.mark.parametrize(
    "updates",
    [
        {"yes_bid": Decimal(".7"), "yes_ask": Decimal(".6")},
        {"no_bid": Decimal(".5"), "no_ask": Decimal(".4")},
        {"yes_bid": Decimal(".7"), "no_bid": Decimal(".4")},
        {"yes_ask": Decimal(".5"), "no_ask": Decimal(".4")},
    ],
)
def test_crossed_book_blocks_both_sides(updates: dict[str, Decimal]) -> None:
    result = compare(MarketPrice.model_validate({"retrieved_at": NOW, **updates}))
    assert result.yes_reason == result.no_reason == "crossed_book"
    assert result.yes_raw_edge is result.no_raw_edge is None
    assert result.valid_until is None


@pytest.mark.parametrize(
    "bad", [Decimal("NaN"), Decimal("Infinity"), Decimal("1.1"), Decimal("-.1")]
)
def test_invalid_book_blocks_both_sides(bad: Decimal) -> None:
    price = MarketPrice(no_ask=Decimal(".4"), retrieved_at=NOW).model_copy(update={"yes_ask": bad})
    result = compare(price)
    assert result.yes_reason == result.no_reason == "invalid_book"
    assert result.yes_raw_edge is result.no_raw_edge is None


@pytest.mark.parametrize(
    "age,reason", [(900, "stale_quote"), (901, "stale_quote"), (-1, "future_quote")]
)
def test_quote_freshness_boundaries(age: int, reason: str) -> None:
    result = compare(MarketPrice(yes_ask=Decimal(".5"), retrieved_at=NOW - timedelta(seconds=age)))
    assert result.yes_reason == reason
    assert result.valid_until is None


def test_quote_expiry_caps_comparison() -> None:
    result = compare(MarketPrice(yes_ask=Decimal(".5"), retrieved_at=NOW - timedelta(seconds=899)))
    assert result.valid_until == NOW + timedelta(seconds=1)


@pytest.mark.parametrize(
    "now", [NOW - timedelta(seconds=1), NOW + timedelta(minutes=15), NOW.replace(tzinfo=None)]
)
def test_forecast_expiry_future_and_naive_time_raise(now: datetime) -> None:
    with pytest.raises(ValueError):
        compare(MarketPrice(yes_ask=Decimal(".5"), retrieved_at=NOW), now=now)


@pytest.mark.parametrize("ask", [Decimal(0), Decimal(1)])
def test_endpoint_asks_are_not_comparable(ask: Decimal) -> None:
    result = compare(MarketPrice(yes_ask=ask, retrieved_at=NOW))
    assert result.yes_reason == "invalid_side_ask"
    assert result.yes_raw_edge is None


def test_missing_quote_and_determinism() -> None:
    assert compare(None).yes_reason == "missing_quote"
    price = MarketPrice(yes_ask=Decimal(".55"), no_ask=Decimal(".5"), retrieved_at=NOW)
    assert compare(price) == compare(price)
    assert (
        compare(price).input_fingerprint
        != compare(price, now=NOW + timedelta(seconds=1)).input_fingerprint
    )


def test_forecast_orientation_is_used_not_home_assumption() -> None:
    changed = forecast().model_copy(
        update={
            "yes_team_id": UUID(int=5),
            "expected_yes_payout": Decimal(".4"),
            "expected_no_payout": Decimal(".6"),
        }
    )
    result = compare(MarketPrice(yes_ask=Decimal(".3"), retrieved_at=NOW), candidate=changed)
    assert result.yes_raw_edge == Decimal(".1")


def test_forecast_authority_and_pin_tampering_raise() -> None:
    for changes in (
        {"trading_enabled": True},
        {"seed_fingerprint": "b" * 64},
        {"model_version": "other"},
    ):
        with pytest.raises(ValueError):
            compare(None, candidate=forecast().model_copy(update=changes))


def test_policy_requires_ordered_thresholds() -> None:
    with pytest.raises(ValueError):
        NflPaperOpportunityPolicy(watch_threshold=Decimal(".1"), candidate_threshold=Decimal(".05"))


@pytest.mark.parametrize(
    "changes",
    [
        {"yes_raw_edge": Decimal("0.9")},
        {"no_expected_payout": Decimal("0.9")},
        {"valid_until": NOW},
        {"price_id": None},
        {"price_retrieved_at": None},
        {"yes_status": "ineligible"},
        {"operational_eligible": True},
        {"trading_enabled": True},
        {"execution_mode": "live"},
        {"costs_included": True},
    ],
)
def test_comparison_contract_rejects_arithmetic_and_authority_tampering(
    changes: dict[str, object],
) -> None:
    payload = compare(MarketPrice(yes_ask=Decimal(".5"), retrieved_at=NOW)).model_dump()
    payload.update(changes)
    with pytest.raises(ValueError):
        NflPaperOpportunityComparison.model_validate(payload)
