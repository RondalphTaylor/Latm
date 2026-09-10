from decimal import Decimal
from uuid import UUID

import pytest

from app.domain.matching import TeamAliasSource, TeamMatchInput
from app.services.matching.aliases import normalize_match_text
from app.services.matching.nfl_aliases import (
    extract_nfl_team_signals,
    has_non_nfl_sport_signal,
)


def _team(number: int, abbreviation: str, city: str, name: str) -> TeamMatchInput:
    return TeamMatchInput(
        id=UUID(int=number),
        abbreviation=abbreviation,
        city=city,
        name=name,
        full_name=f"{city} {name}",
    )


TEAMS = (
    _team(1, "NYG", "New York", "Giants"),
    _team(2, "NYJ", "New York", "Jets"),
    _team(3, "LAR", "Los Angeles", "Rams"),
    _team(4, "LAC", "Los Angeles", "Chargers"),
    _team(5, "WAS", "Washington", "Commanders"),
    _team(6, "JAX", "Jacksonville", "Jaguars"),
    _team(7, "NO", "New Orleans", "Saints"),
)


@pytest.mark.parametrize(
    ("alias", "team_number"),
    [
        ("New York G", 1),
        ("NY Giants", 1),
        ("New York J", 2),
        ("NY Jets", 2),
        ("Los Angeles R", 3),
        ("LA Rams", 3),
        ("Los Angeles C", 4),
        ("LA Chargers", 4),
        ("LA", 3),
        ("LAR", 3),
        ("WSH", 5),
        ("WAS", 5),
        ("JAC", 6),
        ("JAX", 6),
    ],
)
def test_provider_and_curated_aliases(alias: str, team_number: int) -> None:
    text = f"Pro Football: {alias} wins"
    signals = extract_nfl_team_signals(normalize_match_text(text), TEAMS, original_text=text)
    assert [signal.team_id for signal in signals] == [UUID(int=team_number)]


@pytest.mark.parametrize("text", ["NFL New York", "NFL Los Angeles", "NFL ny", "NFL la"])
def test_ambiguous_cities_do_not_select_teams(text: str) -> None:
    assert extract_nfl_team_signals(text, TEAMS, original_text=text) == ()


@pytest.mark.parametrize("text", ["NFL was no good", "WAS vs NO", "NFL jac vs lar"])
def test_abbreviations_require_context_and_uppercase(text: str) -> None:
    assert extract_nfl_team_signals(text, TEAMS, original_text=text) == ()


@pytest.mark.parametrize("league", ["NCAAF", "college football", "NBA", "MLB", "CFL", "UFL"])
def test_other_leagues_rejected_even_with_nfl_context(league: str) -> None:
    text = f"NFL {league}: Giants vs Jets"
    assert has_non_nfl_sport_signal(text)
    assert extract_nfl_team_signals(text, TEAMS, original_text=text) == ()


def test_unique_city_requires_context_and_has_matching_quality() -> None:
    text = "Pro Football Washington wins"
    signals = extract_nfl_team_signals(text, TEAMS, original_text=text)
    assert len(signals) == 1
    assert signals[0].source is TeamAliasSource.CITY
    assert signals[0].quality >= Decimal("0.9")
    assert extract_nfl_team_signals("Washington", TEAMS, original_text="Washington") == ()


def test_full_name_is_strongest_and_order_is_stable() -> None:
    text = "NFL New York Giants NYG Giants vs New York Jets"
    signals = extract_nfl_team_signals(text, TEAMS, original_text=text)
    assert [signal.team_id for signal in signals] == [UUID(int=1), UUID(int=2)]
    assert all(signal.source is TeamAliasSource.FULL_NAME for signal in signals)
    assert signals == extract_nfl_team_signals(text, tuple(reversed(TEAMS)), original_text=text)


@pytest.mark.parametrize(
    ("abbreviation", "alternate"), [("LA", "LAR"), ("WSH", "WAS"), ("JAC", "JAX")]
)
def test_alternate_provider_abbreviation(abbreviation: str, alternate: str) -> None:
    team = _team(8, abbreviation, "Example", "Example Team")
    text = f"NFL {alternate}"
    assert extract_nfl_team_signals(text, (team,), original_text=text)[0].team_id == team.id
