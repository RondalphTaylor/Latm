from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from app.domain.matching import TeamAliasSource, TeamMatchInput, TeamSignal

_SPACE_PATTERN = re.compile(r"\s+")
_NON_ALPHANUMERIC_PATTERN = re.compile(r"[^a-z0-9]+")

_NBA_CONTEXT_PHRASES = (
    "nba",
    "basketball game",
    "pro basketball",
    "national basketball association",
)

_NON_NBA_SPORT_PHRASES = (
    "college basketball",
    "ncaa",
    "women s basketball",
    "wnba",
    "pro football",
    "football game",
    "nfl",
    "pro baseball",
    "baseball game",
    "mlb",
    "pro soccer",
    "soccer game",
    "mls",
    "usl",
    "hockey",
    "nhl",
)

_CONTEXT_REQUIRED_NICKNAMES = {
    "heat",
    "jazz",
    "kings",
    "magic",
    "nets",
    "suns",
    "thunder",
}

_CURATED_ALIASES: dict[str, tuple[tuple[str, bool], ...]] = {
    "BKN": (("bk nets", False),),
    "GSW": (("dubs", False),),
    "LAC": (("la clippers", False),),
    "LAL": (("la lakers", False),),
    "NOP": (("nola pelicans", False),),
    "NYK": (("ny knicks", False),),
    "OKC": (("okc thunder", False), ("okc", True)),
    "PHI": (("sixers", False), ("philly 76ers", False)),
    "PHX": (("phx suns", False),),
    "POR": (("blazers", False),),
    "SAS": (("sa spurs", False),),
}


@dataclass(frozen=True)
class _AliasSpec:
    team_id: UUID
    alias: str
    source: TeamAliasSource
    quality: Decimal
    requires_context: bool


def normalize_match_text(value: str) -> str:
    """Normalize provider-neutral text for boundary-aware phrase matching."""
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    ascii_text = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return _SPACE_PATTERN.sub(" ", _NON_ALPHANUMERIC_PATTERN.sub(" ", ascii_text)).strip()


def _contains_phrase(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "


def _contains_uppercase_token(text: str, token: str) -> bool:
    pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(token.upper())}(?![A-Za-z0-9])")
    return pattern.search(text) is not None


def has_nba_context(text: str) -> bool:
    """Return whether text explicitly identifies NBA/pro-basketball context."""
    return any(_contains_phrase(text, phrase) for phrase in _NBA_CONTEXT_PHRASES)


def has_non_nba_sport_signal(text: str) -> bool:
    """Reject concrete cross-sport signals before interpreting shared aliases."""
    return any(_contains_phrase(text, phrase) for phrase in _NON_NBA_SPORT_PHRASES)


def _team_alias_specs(team: TeamMatchInput) -> list[_AliasSpec]:
    nickname = normalize_match_text(team.name)
    specs = [
        _AliasSpec(
            team_id=team.id,
            alias=normalize_match_text(team.full_name),
            source=TeamAliasSource.FULL_NAME,
            quality=Decimal("1.00"),
            requires_context=False,
        ),
        _AliasSpec(
            team_id=team.id,
            alias=nickname,
            source=TeamAliasSource.NICKNAME,
            quality=Decimal("0.95"),
            requires_context=nickname in _CONTEXT_REQUIRED_NICKNAMES,
        ),
        _AliasSpec(
            team_id=team.id,
            alias=normalize_match_text(team.abbreviation),
            source=TeamAliasSource.ABBREVIATION,
            quality=Decimal("0.90"),
            requires_context=True,
        ),
        _AliasSpec(
            team_id=team.id,
            alias=normalize_match_text(team.city),
            source=TeamAliasSource.CITY,
            quality=Decimal("0.75"),
            requires_context=True,
        ),
    ]
    specs.extend(
        _AliasSpec(
            team_id=team.id,
            alias=normalize_match_text(alias),
            source=TeamAliasSource.CURATED,
            quality=Decimal("0.95"),
            requires_context=requires_context,
        )
        for alias, requires_context in _CURATED_ALIASES.get(team.abbreviation.upper(), ())
    )
    return specs


def extract_team_signals(
    text: str,
    teams: tuple[TeamMatchInput, ...],
    *,
    original_text: str,
) -> tuple[TeamSignal, ...]:
    """Return the strongest unambiguous alias observed for every team."""
    context_present = has_nba_context(text)
    specs = [spec for team in teams for spec in _team_alias_specs(team) if spec.alias]
    alias_owners: dict[str, set[UUID]] = {}
    for spec in specs:
        alias_owners.setdefault(spec.alias, set()).add(spec.team_id)

    strongest: dict[UUID, _AliasSpec] = {}
    for spec in specs:
        if len(alias_owners[spec.alias]) != 1:
            continue
        if spec.requires_context and not context_present:
            continue
        alias_present = (
            _contains_uppercase_token(original_text, spec.alias)
            if spec.source is TeamAliasSource.ABBREVIATION
            else _contains_phrase(text, spec.alias)
        )
        if not alias_present:
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
