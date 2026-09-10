from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from app.domain.matching import MarketMatchInput

NFL_CONTRACT_POLICY_VERSION = "nfl-full-game-rules-v2"


def nfl_team_codes(abbreviation: str) -> tuple[str, ...]:
    """Reviewed provider-code equivalences, not arbitrary city abbreviations."""
    code = abbreviation.upper()
    for group in (("LA", "LAR"), ("WSH", "WAS"), ("JAC", "JAX")):
        if code in group:
            return group
    return (code,)


_PRIMARY = re.compile(
    r"If (?P<team>.+?) wins the (?P<game>.+?) "
    r"(?P<sport>professional football|Pro Football) game originally scheduled for "
    r"(?P<date>[A-Z][a-z]{2} \d{1,2}, \d{4}), then the market resolves to Yes\."
)
_FOOTER = (
    "Kalshi is not affiliated, associated, authorized, endorsed by, or in any way "
    "officially connected with the Governing League. All trademarks, logos, and brand "
    "names are the property of their respective owners."
)


@dataclass(frozen=True)
class NflContractEligibility:
    """Research contract recognition, never an execution permission."""

    eligible: bool
    reason: str
    game_date: date | None = None
    selected_team: str | None = None
    matchup: str | None = None


def evaluate_nfl_contract(market: MarketMatchInput) -> NflContractEligibility:
    """Recognize only the reviewed full-game rule template and consistent IDs."""
    if (
        market.provider_name != "kalshi"
        or market.series_ticker != "KXNFLGAME"
        or market.market_type.casefold() != "binary"
        or market.category != "Sports"
    ):
        return NflContractEligibility(False, "unsupported_contract_identity")
    event_id = market.provider_event_id or ""
    match = re.fullmatch(r"KXNFLGAME-(\d{2}[A-Z]{3}\d{2})([A-Z]{4,6})", event_id)
    if match is None or not re.fullmatch(
        re.escape(event_id) + r"-[A-Z]{2,3}", market.provider_market_id or ""
    ):
        return NflContractEligibility(False, "inconsistent_contract_identifiers")
    primary = _PRIMARY.fullmatch(" ".join((market.rules_primary or "").split()))
    if primary is None:
        return NflContractEligibility(False, "unrecognized_primary_rules")
    try:
        game_date = datetime.strptime(primary["date"], "%b %d, %Y").date()
        ticker_date = datetime.strptime(match[1], "%y%b%d").date()
    except ValueError:
        return NflContractEligibility(False, "invalid_contract_date")
    if game_date != ticker_date:
        return NflContractEligibility(False, "conflicting_contract_dates")
    expected = (
        f"The following market refers to the team who wins the {primary['game']} "
        f"{primary['sport']} game originally scheduled for {primary['date']}. "
        "If the game ends in a tie, the market will resolve to $0.50 for each team. "
        "If the game is postponed but begins within 48 hours from its originally scheduled "
        "start time, the market will remain open and resolve based on the official final result. "
        "If the game is not started within 48 hours, the market will resolve to a fair price."
    )
    secondary = " ".join((market.rules_secondary or "").split())
    accepted = {
        expected,
        expected.replace("a fair price.", "a fair market price."),
    }
    accepted |= {f"{text} {_FOOTER}" for text in tuple(accepted)}
    if secondary not in accepted:
        return NflContractEligibility(False, "unrecognized_secondary_rules")
    return NflContractEligibility(
        True, "recognized_research_contract", game_date, primary["team"], primary["game"]
    )
