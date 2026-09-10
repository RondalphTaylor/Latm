from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from app.domain.matching import MarketMatchInput, MatchingPolicy, SportsEventMatchInput
from app.domain.sports import SportsLeague
from app.services.matching.matcher import MATCHER_VERSION, MarketEventMatcher
from tests.test_matching_aliases import team

NE = team("NE", "New England", "Patriots")
SEA = team("SEA", "Seattle", "Seahawks")
KICKOFF = datetime(2026, 9, 10, 0, 20, tzinfo=UTC)
PRIMARY = (
    "If Seattle wins the New England vs Seattle professional football game originally "
    "scheduled for Sep 9, 2026, then the market resolves to Yes."
)
SECONDARY = (
    "The following market refers to the team who wins the New England vs Seattle professional "
    "football game originally scheduled for Sep 9, 2026. If the game ends in a tie, the market "
    "will resolve to $0.50 for each team. If the game is postponed but begins within 48 hours "
    "from its originally scheduled start time, the market will remain open and resolve based "
    "on the official final result. If the game is not started within 48 hours, the market will "
    "resolve to a fair market price."
)


def nfl_market() -> MarketMatchInput:
    return MarketMatchInput(
        id=UUID(int=1),
        league=SportsLeague.NFL,
        provider_name="kalshi",
        provider_market_id="KXNFLGAME-26SEP09NESEA-SEA",
        provider_event_id="KXNFLGAME-26SEP09NESEA",
        series_ticker="KXNFLGAME",
        title="Seattle wins",
        subtitle="NE vs SEA",
        category="Sports",
        market_type="binary",
        rules_primary=PRIMARY,
        rules_secondary=SECONDARY,
        outcome_labels=("Seattle", "Seattle"),
        occurrence_time=KICKOFF,
        close_time=KICKOFF + timedelta(days=3),
        last_seen_at=KICKOFF - timedelta(hours=1),
    )


def nfl_event() -> SportsEventMatchInput:
    return SportsEventMatchInput(
        id=UUID(int=2),
        event_date=date(2026, 9, 9),
        scheduled_start_time=KICKOFF,
        home_team_id=SEA.id,
        away_team_id=NE.id,
        last_seen_at=KICKOFF,
    )


def matcher() -> MarketEventMatcher:
    return MarketEventMatcher(
        MatchingPolicy(
            matcher_version=MATCHER_VERSION,
            min_confidence=Decimal("0.9"),
            ambiguity_margin=Decimal("0.1"),
            time_window_hours=36,
        )
    )


def test_nfl_match_records_rules_but_never_trading_authority() -> None:
    result = matcher().match(nfl_market(), teams=(NE, SEA), events=(nfl_event(),))
    assert result.status.value == "matched"
    assert result.sports_event_id == nfl_event().id
    assert result.automatic_trading_eligible is False
    assert result.evidence["contract_eligible_for_research"] is True
    assert result.evidence["yes_team_id"] == str(SEA.id)
    assert result.evidence["tie_yes_payout"] == "0.50"
    assert result.evidence["execution_supported"] is False


@pytest.mark.parametrize(
    "changes",
    [
        {"rules_primary": None},
        {"rules_secondary": None},
        {"rules_secondary": SECONDARY.replace("$0.50", "$0.00")},
        {"rules_secondary": SECONDARY.replace("48 hours", "two weeks")},
        {"rules_secondary": SECONDARY + " Overtime is excluded."},
        {"rules_primary": PRIMARY.replace("wins the", "wins the first half of the")},
        {"series_ticker": "KXNFLSPREAD"},
        {"provider_market_id": "KXNFLGAME-26SEP09NESEA-NE"},
        {"provider_event_id": "KXNFLGAME-26SEP10NESEA"},
        {"outcome_labels": ("New England", "New England")},
        {
            "provider_market_id": "KXNFLGAME-26SEP09NENSEA-SEA",
            "provider_event_id": "KXNFLGAME-26SEP09NENSEA",
        },
    ],
)
def test_nfl_conflicts_and_unreviewed_rules_fail_closed(changes: dict[str, object]) -> None:
    result = matcher().match(
        nfl_market().model_copy(update=changes), teams=(NE, SEA), events=(nfl_event(),)
    )
    assert result.status.value != "matched"
    assert result.automatic_trading_eligible is False


def test_contract_date_fallback_does_not_use_late_close_as_kickoff() -> None:
    result = matcher().match(
        nfl_market().model_copy(update={"occurrence_time": None}),
        teams=(NE, SEA),
        events=(nfl_event(),),
    )
    assert result.status.value == "matched"
    assert result.method == "nfl_team_pair_contract_date"
    assert result.candidate_scores[0].time_delta_seconds is None


def test_nfl_date_mismatch_and_duplicate_candidates_never_match() -> None:
    later = nfl_event().model_copy(update={"scheduled_start_time": KICKOFF + timedelta(days=1)})
    result = matcher().match(nfl_market(), teams=(NE, SEA), events=(later,))
    assert result.status.value == "unmatched"
    duplicate = nfl_event().model_copy(update={"id": UUID(int=3)})
    result = matcher().match(nfl_market(), teams=(NE, SEA), events=(nfl_event(), duplicate))
    assert result.status.value == "ambiguous"


def test_rule_changes_append_fingerprint_but_poll_times_do_not() -> None:
    first = matcher().match(nfl_market(), teams=(NE, SEA), events=(nfl_event(),))
    replay = matcher().match(
        nfl_market().model_copy(update={"last_seen_at": KICKOFF}),
        teams=(NE, SEA),
        events=(nfl_event(),),
    )
    changed = matcher().match(
        nfl_market().model_copy(update={"rules_secondary": SECONDARY + " Changed."}),
        teams=(NE, SEA),
        events=(nfl_event(),),
    )
    assert replay.input_fingerprint == first.input_fingerprint
    assert changed.input_fingerprint != first.input_fingerprint


@pytest.mark.parametrize(
    "matchup",
    [
        "first half of the New England vs Seattle",
        "New England vs Seattle in regulation",
        "New England vs Seattle by more than 3 points",
    ],
)
def test_consistent_partial_game_rule_mutations_are_rejected(matchup: str) -> None:
    market = nfl_market().model_copy(
        update={
            "rules_primary": PRIMARY.replace("New England vs Seattle", matchup),
            "rules_secondary": SECONDARY.replace("New England vs Seattle", matchup),
        }
    )
    result = matcher().match(market, teams=(NE, SEA), events=(nfl_event(),))
    assert result.status.value == "unmatched"
    assert result.evidence["contract_eligible_for_research"] is False


def test_yes_team_embedded_in_extra_clause_is_rejected() -> None:
    market = nfl_market().model_copy(
        update={"rules_primary": PRIMARY.replace("If Seattle", "If not Seattle")}
    )
    result = matcher().match(market, teams=(NE, SEA), events=(nfl_event(),))
    assert result.status.value == "unmatched"
