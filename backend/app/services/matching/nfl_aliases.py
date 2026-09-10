from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.domain.matching import TeamAliasSource, TeamMatchInput, TeamSignal
from app.services.matching.aliases import normalize_match_text

_NFL_CONTEXT_PHRASES = (
    "nfl",
    "national football league",
    "professional football",
    "pro football",
)
_NON_NFL_SPORT_PHRASES = (
    "college",
    "ncaa",
    "ncaaf",
    "ncaa football",
    "college football",
    "fbs",
    "fcs",
    "cfl",
    "ufl",
    "xfl",
    "usfl",
    "canadian football",
    "arena football",
    "baseball",
    "mlb",
    "basketball",
    "nba",
    "wnba",
    "soccer",
    "mls",
    "hockey",
    "nhl",
)
_AMBIGUOUS_CITIES = {"new york", "ny", "los angeles", "la"}
_CANONICAL_ABBREVIATIONS = {"LA": "LAR", "WSH": "WAS", "JAC": "JAX"}
_ALTERNATE_ABBREVIATIONS: dict[str, tuple[str, ...]] = {
    "LAR": ("LA",),
    "WAS": ("WSH",),
    "JAX": ("JAC",),
}
_CURATED_ALIASES: dict[str, tuple[str, ...]] = {
    "NYG": ("new york g", "ny giants"),
    "NYJ": ("new york j", "ny jets"),
    "LAR": ("los angeles r", "la rams"),
    "LAC": ("los angeles c", "la chargers"),
}


@dataclass(frozen=True)
class _AliasSpec:
    team_id: UUID
    alias: str
    source: TeamAliasSource
    quality: Decimal
    requires_context: bool


def _contains_phrase(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "


def has_non_nfl_sport_signal(text: str) -> bool:
    """Reject explicit competing sports and non-NFL football leagues."""
    normalized = normalize_match_text(text)
    return any(_contains_phrase(normalized, phrase) for phrase in _NON_NFL_SPORT_PHRASES)


def _team_alias_specs(team: TeamMatchInput) -> list[_AliasSpec]:
    abbreviation = _CANONICAL_ABBREVIATIONS.get(
        team.abbreviation.upper(), team.abbreviation.upper()
    )
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
            normalize_match_text(team.name),
            TeamAliasSource.NICKNAME,
            Decimal("0.95"),
            False,
        ),
    ]
    for alias in (abbreviation, *_ALTERNATE_ABBREVIATIONS.get(abbreviation, ())):
        specs.append(
            _AliasSpec(
                team.id,
                normalize_match_text(alias),
                TeamAliasSource.ABBREVIATION,
                Decimal("0.90"),
                True,
            )
        )
    city = normalize_match_text(team.city)
    if city not in _AMBIGUOUS_CITIES:
        specs.append(_AliasSpec(team.id, city, TeamAliasSource.CITY, Decimal("0.90"), True))
    specs.extend(
        _AliasSpec(
            team.id, normalize_match_text(alias), TeamAliasSource.CURATED, Decimal("0.95"), True
        )
        for alias in _CURATED_ALIASES.get(abbreviation, ())
    )
    return specs


def extract_nfl_team_signals(
    text: str,
    teams: tuple[TeamMatchInput, ...],
    *,
    original_text: str,
) -> tuple[TeamSignal, ...]:
    """Extract unambiguous NFL aliases, with context and uppercase guards."""
    text = normalize_match_text(text)
    if has_non_nfl_sport_signal(text):
        return ()
    context_present = any(_contains_phrase(text, phrase) for phrase in _NFL_CONTEXT_PHRASES)
    specs = [spec for team in teams for spec in _team_alias_specs(team) if spec.alias]
    owners: dict[str, set[UUID]] = {}
    for spec in specs:
        owners.setdefault(spec.alias, set()).add(spec.team_id)
    strongest: dict[UUID, _AliasSpec] = {}
    for spec in specs:
        if len(owners[spec.alias]) != 1 or (spec.requires_context and not context_present):
            continue
        if spec.source is TeamAliasSource.ABBREVIATION:
            # LA is a provider code for the Rams, but in "LA Chargers" it is a city.
            suffix_guard = r"(?!\s+(?i:chargers)\b)" if spec.alias == "la" else ""
            present = (
                re.search(
                    rf"(?<![A-Za-z0-9]){re.escape(spec.alias.upper())}(?![A-Za-z0-9])"
                    + suffix_guard,
                    original_text,
                )
                is not None
            )
        else:
            present = _contains_phrase(text, spec.alias)
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
        TeamSignal(team_id=spec.team_id, alias=spec.alias, source=spec.source, quality=spec.quality)
        for spec in sorted(strongest.values(), key=lambda item: str(item.team_id))
    )


def resolve_nfl_team_designator(value: str, teams: tuple[TeamMatchInput, ...]) -> UUID | None:
    """Resolve a complete reviewed team label, never a team embedded in a clause."""
    normalized = normalize_match_text(value)
    owners = {
        spec.team_id
        for team in teams
        for spec in _team_alias_specs(team)
        if spec.alias == normalized
        and (spec.source is not TeamAliasSource.ABBREVIATION or value == value.upper())
    }
    return next(iter(owners)) if len(owners) == 1 else None
