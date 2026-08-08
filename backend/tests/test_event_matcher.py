from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain.matching import (
    MarketEventMatchDecision,
    MarketEventMatchStatus,
    MarketMatchInput,
    MatchingPolicy,
    SportsEventMatchInput,
    TeamMatchInput,
)
from app.services.matching.matcher import MATCHER_VERSION, MarketEventMatcher

BOS_ID = UUID("a7129d9c-0d4c-44d6-8a2d-dda4dc34cf82")
NYK_ID = UUID("92d9bccf-dd34-4f1f-8886-9d2e884940d1")
PHI_ID = UUID("b5ed29f7-c2aa-4ceb-94d9-9fca483f8670")
MARKET_ID = UUID("3da220e1-b6d0-45e9-b507-7e75dc95a353")
EVENT_ID = UUID("8701782a-4d22-4147-9d60-edbf2e243adc")
SECOND_EVENT_ID = UUID("4c7009f8-07c4-4a0e-bddb-6dafed2f7915")
TIP_TIME = datetime(2026, 8, 1, 23, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 8, 1, 12, tzinfo=UTC)


def policy(
    *,
    min_confidence: str = "0.90",
    ambiguity_margin: str = "0.10",
    time_window_hours: int = 36,
) -> MatchingPolicy:
    return MatchingPolicy(
        matcher_version=MATCHER_VERSION,
        min_confidence=Decimal(min_confidence),
        ambiguity_margin=Decimal(ambiguity_margin),
        time_window_hours=time_window_hours,
    )


def teams() -> tuple[TeamMatchInput, ...]:
    return (
        TeamMatchInput(
            id=BOS_ID,
            abbreviation="BOS",
            city="Boston",
            name="Celtics",
            full_name="Boston Celtics",
        ),
        TeamMatchInput(
            id=NYK_ID,
            abbreviation="NYK",
            city="New York",
            name="Knicks",
            full_name="New York Knicks",
        ),
        TeamMatchInput(
            id=PHI_ID,
            abbreviation="PHI",
            city="Philadelphia",
            name="76ers",
            full_name="Philadelphia 76ers",
        ),
    )


def market(
    *,
    title: str = "Will the Boston Celtics beat the New York Knicks?",
    subtitle: str | None = None,
    occurrence_time: datetime | None = TIP_TIME,
    close_time: datetime | None = TIP_TIME + timedelta(hours=2),
    last_seen_at: datetime = OBSERVED_AT,
) -> MarketMatchInput:
    return MarketMatchInput(
        id=MARKET_ID,
        title=title,
        subtitle=subtitle,
        market_type="binary",
        occurrence_time=occurrence_time,
        close_time=close_time,
        last_seen_at=last_seen_at,
    )


def event(
    *,
    event_id: UUID = EVENT_ID,
    start_time: datetime = TIP_TIME,
    home_team_id: UUID = BOS_ID,
    away_team_id: UUID = NYK_ID,
    last_seen_at: datetime = OBSERVED_AT,
) -> SportsEventMatchInput:
    return SportsEventMatchInput(
        id=event_id,
        event_date=start_time.date(),
        scheduled_start_time=start_time,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        last_seen_at=last_seen_at,
    )


def evaluate(
    market_input: MarketMatchInput,
    *events: SportsEventMatchInput,
    matching_policy: MatchingPolicy | None = None,
) -> MarketEventMatchDecision:
    return MarketEventMatcher(matching_policy or policy()).match(
        market_input,
        teams=teams(),
        events=tuple(events),
        evaluated_at=OBSERVED_AT,
    )


def test_exact_full_names_and_time_match_reversed_home_away_wording() -> None:
    decision = evaluate(
        market(title="New York Knicks at Boston Celtics"),
        event(home_team_id=NYK_ID, away_team_id=BOS_ID),
    )

    assert decision.status is MarketEventMatchStatus.MATCHED
    assert decision.sports_event_id == EVENT_ID
    assert decision.confidence == Decimal("1.0000")
    assert decision.method == "exact_team_pair_and_time"
    assert decision.automatic_trading_eligible


def test_uppercase_abbreviations_match_with_explicit_nba_context() -> None:
    decision = evaluate(market(title="NBA: BOS @ NYK"), event())

    assert decision.status is MarketEventMatchStatus.MATCHED
    assert decision.confidence == Decimal("0.9300")


def test_exact_time_disambiguates_back_to_back_pair() -> None:
    exact = event()
    next_day = event(
        event_id=SECOND_EVENT_ID,
        start_time=TIP_TIME + timedelta(hours=24),
    )

    decision = evaluate(market(), next_day, exact)

    assert decision.status is MarketEventMatchStatus.MATCHED
    assert decision.sports_event_id == EVENT_ID
    assert [candidate.event_id for candidate in decision.candidate_scores] == [
        EVENT_ID,
        SECOND_EVENT_ID,
    ]


def test_tied_candidates_are_ambiguous_and_ineligible() -> None:
    earlier = event(start_time=TIP_TIME - timedelta(hours=1))
    later = event(event_id=SECOND_EVENT_ID, start_time=TIP_TIME + timedelta(hours=1))

    decision = evaluate(market(), earlier, later)

    assert decision.status is MarketEventMatchStatus.AMBIGUOUS
    assert decision.sports_event_id is None
    assert not decision.automatic_trading_eligible
    assert "runner-up" in decision.reason


def test_missing_team_or_event_is_unmatched() -> None:
    one_team = evaluate(market(title="Will the Boston Celtics win tonight?"), event())
    no_event = evaluate(market(), event(home_team_id=BOS_ID, away_team_id=PHI_ID))

    assert one_team.status is MarketEventMatchStatus.UNMATCHED
    assert one_team.method == "insufficient_team_evidence"
    assert no_event.status is MarketEventMatchStatus.UNMATCHED
    assert no_event.method == "no_team_pair_event"


def test_cross_sport_false_positive_and_multi_team_future_are_unmatched() -> None:
    soccer = evaluate(
        market(title="Will Miami win the MIA vs DET Pro Soccer game?"),
        event(),
    )
    future = evaluate(
        market(title="Boston Celtics, New York Knicks, or Philadelphia 76ers to win?"),
        event(),
    )

    assert soccer.status is MarketEventMatchStatus.UNMATCHED
    assert soccer.method == "non_nba_sport_signal"
    assert future.status is MarketEventMatchStatus.UNMATCHED
    assert future.method == "non_single_game_market"


def test_time_outside_window_is_unmatched_and_missing_time_is_ambiguous() -> None:
    boundary = evaluate(market(), event(start_time=TIP_TIME + timedelta(hours=36)))
    stale = evaluate(market(), event(start_time=TIP_TIME + timedelta(hours=36, seconds=1)))
    no_time = evaluate(
        market(occurrence_time=None, close_time=None),
        event(),
    )

    assert boundary.status is MarketEventMatchStatus.AMBIGUOUS
    assert boundary.candidate_scores[0].within_time_window
    assert stale.status is MarketEventMatchStatus.UNMATCHED
    assert stale.method == "date_mismatch"
    assert no_time.status is MarketEventMatchStatus.AMBIGUOUS
    assert no_time.method == "team_pair_only"


def test_threshold_and_margin_boundaries_are_inclusive() -> None:
    abbreviation_market = market(title="NBA: BOS vs NYK")
    at_threshold = evaluate(
        abbreviation_market,
        event(),
        matching_policy=policy(min_confidence="0.93"),
    )
    above_threshold = evaluate(
        abbreviation_market,
        event(),
        matching_policy=policy(min_confidence="0.9301"),
    )
    second = event(event_id=SECOND_EVENT_ID, start_time=TIP_TIME + timedelta(hours=24))
    at_margin = evaluate(
        market(),
        event(),
        second,
        matching_policy=policy(ambiguity_margin="0.12"),
    )
    above_margin = evaluate(
        market(),
        event(),
        second,
        matching_policy=policy(ambiguity_margin="0.1201"),
    )

    assert at_threshold.status is MarketEventMatchStatus.MATCHED
    assert above_threshold.status is MarketEventMatchStatus.AMBIGUOUS
    assert at_margin.status is MarketEventMatchStatus.MATCHED
    assert above_margin.status is MarketEventMatchStatus.AMBIGUOUS


def test_fingerprint_is_order_stable_and_ignores_observation_timestamps() -> None:
    first = MarketEventMatcher(policy()).match(
        market(last_seen_at=OBSERVED_AT),
        teams=teams(),
        events=(event(last_seen_at=OBSERVED_AT),),
        evaluated_at=OBSERVED_AT,
    )
    second = MarketEventMatcher(policy()).match(
        market(last_seen_at=OBSERVED_AT + timedelta(days=1)),
        teams=tuple(reversed(teams())),
        events=(event(last_seen_at=OBSERVED_AT + timedelta(days=1)),),
        evaluated_at=OBSERVED_AT + timedelta(days=1),
    )
    rescheduled = evaluate(market(), event(start_time=TIP_TIME + timedelta(hours=1)))

    assert first.input_fingerprint == second.input_fingerprint
    assert first.input_fingerprint != rescheduled.input_fingerprint


def test_domain_rejects_ineligible_or_linkless_matched_decision() -> None:
    valid = evaluate(market(), event())
    payload = valid.model_dump()
    payload["sports_event_id"] = None

    with pytest.raises(ValidationError):
        MarketEventMatchDecision.model_validate(payload)
