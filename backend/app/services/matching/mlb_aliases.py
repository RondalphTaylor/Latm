from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.domain.matching import TeamAliasSource, TeamMatchInput, TeamSignal
from app.services.matching.aliases import normalize_match_text

_MLB_CONTEXT_PHRASES = (
    "mlb",
    "baseball game",
    "pro baseball",
    "professional baseball game",
    "major league baseball",
)
_NON_MLB_SPORT_PHRASES = (
    "college baseball",
    "minor league baseball",
    "milb",
    "kbo",
    "npb",
    "basketball",
    "nba",
    "football",
    "nfl",
    "soccer",
    "mls",
    "hockey",
    "nhl",
)
_CURATED_ALIASES: dict[str, tuple[str, ...]] = {
    "ATH": ("a s", "athletics"),
    "CHC": ("chicago c",),
    "CWS": ("chicago w", "white sox"),
    "LAA": ("los angeles a",),
    "LAD": ("los angeles d",),
    "NYM": ("new york m",),
    "NYY": ("new york y",),
}
_AMBIGUOUS_CITIES = {"chicago", "los angeles", "new york"}


@dataclass(frozen=True)
class _AliasSpec:
    team_id: UUID
    alias: str
    source: TeamAliasSource
    quality: Decimal
    requires_context: bool


def _contains_phrase(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "


def _contains_uppercase_token(text: str, token: str) -> bool:
    pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(token.upper())}(?![A-Za-z0-9])")
    return pattern.search(text) is not None


def has_non_mlb_sport_signal(text: str) -> bool:
    """Reject explicit competing sport or baseball-league signals."""
    return any(_contains_phrase(text, phrase) for phrase in _NON_MLB_SPORT_PHRASES)


def _team_alias_specs(team: TeamMatchInput) -> list[_AliasSpec]:
    nickname = normalize_match_text(team.name)
    city = normalize_match_text(team.city)
    specs = [
        _AliasSpec(
            team.id,
            normalize_match_text(team.full_name),
            TeamAliasSource.FULL_NAME,
            Decimal("1.00"),
            False,
        ),
        _AliasSpec(
            team.id,
            nickname,
            TeamAliasSource.NICKNAME,
            Decimal("0.95"),
            False,
        ),
        _AliasSpec(
            team.id,
            normalize_match_text(team.abbreviation),
            TeamAliasSource.ABBREVIATION,
            Decimal("0.90"),
            True,
        ),
    ]
    if city not in _AMBIGUOUS_CITIES:
        specs.append(
            _AliasSpec(
                team.id,
                city,
                TeamAliasSource.CITY,
                Decimal("0.75"),
                True,
            )
        )
    specs.extend(
        _AliasSpec(
            team.id,
            normalize_match_text(alias),
            TeamAliasSource.CURATED,
            Decimal("0.95"),
            True,
        )
        for alias in _CURATED_ALIASES.get(team.abbreviation.upper(), ())
    )
    return specs


def extract_mlb_team_signals(
    text: str,
    teams: tuple[TeamMatchInput, ...],
    *,
    original_text: str,
) -> tuple[TeamSignal, ...]:
    """Return strongest unambiguous MLB aliases from official market text."""
    context_present = any(_contains_phrase(text, phrase) for phrase in _MLB_CONTEXT_PHRASES)
    specs = [spec for team in teams for spec in _team_alias_specs(team) if spec.alias]
    owners: dict[str, set[UUID]] = {}
    for spec in specs:
        owners.setdefault(spec.alias, set()).add(spec.team_id)

    strongest: dict[UUID, _AliasSpec] = {}
    for spec in specs:
        if len(owners[spec.alias]) != 1 or (spec.requires_context and not context_present):
            continue
        present = (
            _contains_uppercase_token(original_text, spec.alias)
            if spec.source is TeamAliasSource.ABBREVIATION
            else _contains_phrase(text, spec.alias)
        )
        if not present:
            continue
        current = strongest.get(spec.team_id)
        if current is None or (spec.quality, spec.source.value, spec.alias) > (
            current.quality,
            current.source.value,
            current.alias,
        ):
            strongest[spec.team_id] = spec
    return tuple(
        TeamSignal(
            team_id=spec.team_id,
            alias=spec.alias,
            source=spec.source,
            quality=spec.quality,
        )
        for spec in sorted(strongest.values(), key=lambda item: str(item.team_id))
    )
