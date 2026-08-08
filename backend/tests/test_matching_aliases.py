from __future__ import annotations

from uuid import UUID, uuid5

import pytest

from app.domain.matching import TeamAliasSource, TeamMatchInput
from app.services.matching.aliases import (
    extract_team_signals,
    has_non_nba_sport_signal,
    normalize_match_text,
)

_TEAM_NAMESPACE = UUID("1f5e395c-6611-4073-a699-4688422953b9")

_NBA_TEAMS = (
    ("ATL", "Atlanta", "Hawks"),
    ("BOS", "Boston", "Celtics"),
    ("BKN", "Brooklyn", "Nets"),
    ("CHA", "Charlotte", "Hornets"),
    ("CHI", "Chicago", "Bulls"),
    ("CLE", "Cleveland", "Cavaliers"),
    ("DAL", "Dallas", "Mavericks"),
    ("DEN", "Denver", "Nuggets"),
    ("DET", "Detroit", "Pistons"),
    ("GSW", "Golden State", "Warriors"),
    ("HOU", "Houston", "Rockets"),
    ("IND", "Indiana", "Pacers"),
    ("LAC", "Los Angeles", "Clippers"),
    ("LAL", "Los Angeles", "Lakers"),
    ("MEM", "Memphis", "Grizzlies"),
    ("MIA", "Miami", "Heat"),
    ("MIL", "Milwaukee", "Bucks"),
    ("MIN", "Minnesota", "Timberwolves"),
    ("NOP", "New Orleans", "Pelicans"),
    ("NYK", "New York", "Knicks"),
    ("OKC", "Oklahoma City", "Thunder"),
    ("ORL", "Orlando", "Magic"),
    ("PHI", "Philadelphia", "76ers"),
    ("PHX", "Phoenix", "Suns"),
    ("POR", "Portland", "Trail Blazers"),
    ("SAC", "Sacramento", "Kings"),
    ("SAS", "San Antonio", "Spurs"),
    ("TOR", "Toronto", "Raptors"),
    ("UTA", "Utah", "Jazz"),
    ("WAS", "Washington", "Wizards"),
)


def team(abbreviation: str, city: str, name: str) -> TeamMatchInput:
    return TeamMatchInput(
        id=uuid5(_TEAM_NAMESPACE, abbreviation),
        abbreviation=abbreviation,
        city=city,
        name=name,
        full_name=f"{city} {name}",
    )


ALL_TEAMS = tuple(team(*values) for values in _NBA_TEAMS)


@pytest.mark.parametrize(("abbreviation", "city", "name"), _NBA_TEAMS)
def test_all_canonical_team_names_and_abbreviations_are_supported(
    abbreviation: str,
    city: str,
    name: str,
) -> None:
    selected = team(abbreviation, city, name)
    original = f"NBA: {selected.full_name} ({abbreviation})"
    normalized = normalize_match_text(original)

    signals = extract_team_signals(normalized, (selected,), original_text=original)

    assert len(signals) == 1
    assert signals[0].team_id == selected.id
    assert signals[0].source is TeamAliasSource.FULL_NAME


def test_curated_aliases_and_punctuation_are_boundary_aware() -> None:
    original = "NBA — Sixers vs. Blazers"

    signals = extract_team_signals(
        normalize_match_text(original),
        ALL_TEAMS,
        original_text=original,
    )

    assert {signal.alias for signal in signals} == {"sixers", "blazers"}
    assert all(signal.source is TeamAliasSource.CURATED for signal in signals)


def test_short_abbreviation_requires_original_uppercase_token() -> None:
    original = "This NBA rule was independently reviewed"

    signals = extract_team_signals(
        normalize_match_text(original),
        ALL_TEAMS,
        original_text=original,
    )

    assert uuid5(_TEAM_NAMESPACE, "WAS") not in {signal.team_id for signal in signals}


def test_colliding_city_and_generic_nicknames_do_not_standalone_match() -> None:
    original = "Los Angeles heat and magic"

    signals = extract_team_signals(
        normalize_match_text(original),
        ALL_TEAMS,
        original_text=original,
    )

    assert signals == ()


def test_context_enables_generic_nicknames_but_not_colliding_city() -> None:
    original = "NBA: Heat vs Magic in Los Angeles"

    signals = extract_team_signals(
        normalize_match_text(original),
        ALL_TEAMS,
        original_text=original,
    )

    assert {signal.alias for signal in signals} == {"heat", "magic"}


@pytest.mark.parametrize(
    "text",
    [
        "MIA vs DET Pro Soccer game",
        "PHI vs ATL MLS game",
        "Washington vs Philadelphia Pro Football game",
        "Boston vs New York WNBA game",
    ],
)
def test_explicit_non_nba_sport_signals_are_detected(text: str) -> None:
    assert has_non_nba_sport_signal(normalize_match_text(text))
