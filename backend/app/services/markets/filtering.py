from __future__ import annotations

import hashlib
import json
import re

from app.domain.markets import (
    PredictionMarket,
    SportsMarketClassification,
    SportsMarketType,
)
from app.domain.sports import SportsLeague

SPORTS_CLASSIFICATION_VERSION = "kalshi-official-series-v1"
SPORTS_CLASSIFICATION_METHOD = "official_series_metadata"
_SUPPORTED_SERIES = {
    SportsLeague.NBA: "KXNBAGAME",
    SportsLeague.MLB: "KXMLBGAME",
}

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


def supported_series_ticker(league: SportsLeague) -> str:
    """Return the exact official Kalshi single-game-winner series for a league."""
    return _SUPPORTED_SERIES[league]


def _event_product_metadata(market: PredictionMarket) -> dict[str, object]:
    event = market.raw_data.get("event")
    if not isinstance(event, dict):
        return {}
    metadata = event.get("product_metadata")
    return (
        {str(key): value for key, value in metadata.items()} if isinstance(metadata, dict) else {}
    )


def classify_sports_market(
    market: PredictionMarket,
) -> SportsMarketClassification | None:
    """Classify only exact, provider-declared single-game winner contracts."""
    if (
        market.provider_name != "kalshi"
        or market.category != "Sports"
        or market.market_type.casefold() != "binary"
        or market.provider_event_id is None
    ):
        return None
    league = next(
        (
            candidate
            for candidate, series_ticker in _SUPPORTED_SERIES.items()
            if market.series_ticker == series_ticker
        ),
        None,
    )
    if league is None:
        return None

    product_metadata = _event_product_metadata(market)
    expected_competition = "Pro Baseball" if league is SportsLeague.MLB else None
    if product_metadata.get("competition_scope") != "Game":
        return None
    if (
        expected_competition is not None
        and product_metadata.get("competition") != expected_competition
    ):
        return None

    payload = {
        "provider_name": market.provider_name,
        "provider_market_id": market.provider_market_id,
        "provider_event_id": market.provider_event_id,
        "series_ticker": market.series_ticker,
        "category": market.category,
        "market_type": market.market_type.casefold(),
        "competition": product_metadata.get("competition"),
        "competition_scope": product_metadata.get("competition_scope"),
        "sports_market_type": SportsMarketType.SINGLE_GAME_WINNER.value,
        "method": SPORTS_CLASSIFICATION_METHOD,
        "version": SPORTS_CLASSIFICATION_VERSION,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return SportsMarketClassification(
        league=league,
        sports_market_type=SportsMarketType.SINGLE_GAME_WINNER,
        method=SPORTS_CLASSIFICATION_METHOD,
        version=SPORTS_CLASSIFICATION_VERSION,
        fingerprint=hashlib.sha256(encoded).hexdigest(),
    )
