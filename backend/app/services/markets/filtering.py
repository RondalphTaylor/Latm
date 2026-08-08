from __future__ import annotations

import re

from app.domain.markets import PredictionMarket

_NBA_TEAM_NAMES = (
    "atlanta hawks",
    "boston celtics",
    "brooklyn nets",
    "charlotte hornets",
    "chicago bulls",
    "cleveland cavaliers",
    "dallas mavericks",
    "denver nuggets",
    "detroit pistons",
    "golden state warriors",
    "houston rockets",
    "indiana pacers",
    "los angeles clippers",
    "los angeles lakers",
    "memphis grizzlies",
    "miami heat",
    "milwaukee bucks",
    "minnesota timberwolves",
    "new orleans pelicans",
    "new york knicks",
    "oklahoma city thunder",
    "orlando magic",
    "philadelphia 76ers",
    "phoenix suns",
    "portland trail blazers",
    "sacramento kings",
    "san antonio spurs",
    "toronto raptors",
    "utah jazz",
    "washington wizards",
)

_NBA_NICKNAMES = tuple(name.rsplit(" ", maxsplit=1)[-1] for name in _NBA_TEAM_NAMES)
_NBA_ABBREVIATIONS = (
    "atl",
    "bos",
    "bkn",
    "cha",
    "chi",
    "cle",
    "dal",
    "den",
    "det",
    "gsw",
    "hou",
    "ind",
    "lac",
    "lal",
    "mem",
    "mia",
    "mil",
    "min",
    "nop",
    "nyk",
    "okc",
    "orl",
    "phi",
    "phx",
    "por",
    "sac",
    "sas",
    "tor",
    "uta",
    "was",
)


def _contains_token(text: str, token: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", text) is not None


def is_likely_nba_market(market: PredictionMarket) -> bool:
    """Identify likely NBA markets, preferring structured provider metadata."""
    structured_text = " ".join(
        value.lower()
        for value in (
            market.series_ticker,
            market.provider_event_id,
            str(market.raw_data.get("event", "")),
        )
        if value
    )
    if _contains_token(structured_text, "nba") or "kxnba" in structured_text:
        return True

    category = (market.category or "").casefold()
    if category and category != "sports":
        return False

    descriptive_text = " ".join(
        value.casefold() for value in (market.title, market.subtitle) if value
    )
    if _contains_token(descriptive_text, "nba"):
        return True

    team_matches = sum(
        1
        for team_name in _NBA_TEAM_NAMES
        if team_name in descriptive_text
        or _contains_token(descriptive_text, team_name.rsplit(" ", maxsplit=1)[-1])
    )
    abbreviation_matches = sum(
        1 for abbreviation in _NBA_ABBREVIATIONS if _contains_token(descriptive_text, abbreviation)
    )
    nickname_matches = sum(
        1 for nickname in _NBA_NICKNAMES if _contains_token(descriptive_text, nickname)
    )
    return team_matches >= 2 or abbreviation_matches >= 2 or nickname_matches >= 2
