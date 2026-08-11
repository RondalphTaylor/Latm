from __future__ import annotations

import hashlib
import json
import re
from uuid import UUID

from app.domain.opportunities import (
    OpportunityDirection,
    OpportunityOutcomeInput,
    OpportunityTeamInput,
    OutcomeOrientation,
)
from app.services.matching.aliases import normalize_match_text

ORIENTATION_RESOLVER_VERSION = "binary-event-winner-v1"
_WINNER_PATTERN = re.compile(r"\b(win|wins|winner|beat|beats|defeat|defeats)\b")
_WIN_BY_PATTERN = re.compile(r"\b(?:win|wins|beat|beats|defeat|defeats) by\b")
_UNSUPPORTED_PROPOSITION_PHRASES = (
    "spread",
    "margin",
    "points",
    "point total",
    "total score",
    "over under",
    "first half",
    "second half",
    "quarter",
    "exact score",
    "series",
    "championship",
    "playoff",
    "next team",
    "award",
    "mvp",
)


def _team_aliases(team: OpportunityTeamInput) -> set[str]:
    return {
        normalize_match_text(value)
        for value in (
            team.abbreviation,
            team.city,
            team.name,
            team.full_name,
            f"{team.city} {team.name}",
        )
        if normalize_match_text(value)
    }


def _resolved_team_ids(
    label: str,
    teams: tuple[OpportunityTeamInput, OpportunityTeamInput],
) -> set[UUID]:
    normalized = normalize_match_text(label)
    if normalized in {"yes", "no"}:
        return set()
    return {team.id for team in teams if normalized in _team_aliases(team)}


def _is_supported_winner_contract(*, market_title: str, market_type: str) -> bool:
    normalized_title = normalize_match_text(market_title)
    if normalize_match_text(market_type) != "binary":
        return False
    if not _WINNER_PATTERN.search(normalized_title):
        return False
    if _WIN_BY_PATTERN.search(normalized_title):
        return False
    return not any(phrase in normalized_title for phrase in _UNSUPPORTED_PROPOSITION_PHRASES)


def resolve_outcome_orientation(
    *,
    home_team: OpportunityTeamInput,
    away_team: OpportunityTeamInput,
    outcomes: tuple[OpportunityOutcomeInput, ...],
    market_title: str,
    market_type: str,
) -> OutcomeOrientation | None:
    """Resolve contract direction from label-local evidence without guessing."""
    if home_team.id == away_team.id or not _is_supported_winner_contract(
        market_title=market_title,
        market_type=market_type,
    ):
        return None
    by_side = {
        side: tuple(outcome for outcome in outcomes if outcome.side is side)
        for side in OpportunityDirection
    }
    if len(by_side[OpportunityDirection.YES]) != 1 or len(by_side[OpportunityDirection.NO]) != 1:
        return None

    teams = (home_team, away_team)
    yes_outcome = by_side[OpportunityDirection.YES][0]
    no_outcome = by_side[OpportunityDirection.NO][0]
    yes_ids = _resolved_team_ids(yes_outcome.label, teams)
    no_ids = _resolved_team_ids(no_outcome.label, teams)
    if len(yes_ids) > 1 or len(no_ids) > 1:
        return None

    event_team_ids = {home_team.id, away_team.id}
    if len(yes_ids) == 1 and not no_ids:
        yes_team_id = next(iter(yes_ids))
        no_team_id = next(iter(event_team_ids - {yes_team_id}))
        method = "yes_label_with_inferred_no"
    elif not yes_ids and len(no_ids) == 1:
        no_team_id = next(iter(no_ids))
        yes_team_id = next(iter(event_team_ids - {no_team_id}))
        method = "no_label_with_inferred_yes"
    elif len(yes_ids) == 1 and len(no_ids) == 1:
        yes_team_id = next(iter(yes_ids))
        no_team_id = next(iter(no_ids))
        if yes_team_id == no_team_id:
            return None
        method = "distinct_outcome_labels"
    else:
        return None

    payload = {
        "teams": [
            team.model_dump(mode="json") for team in sorted(teams, key=lambda item: str(item.id))
        ],
        "outcomes": [
            outcome.model_dump(mode="json")
            for outcome in sorted(outcomes, key=lambda item: (item.side.value, str(item.id)))
        ],
        "yes_team_id": str(yes_team_id),
        "no_team_id": str(no_team_id),
        "mapping_method": method,
        "market_title": market_title,
        "market_type": market_type,
        "resolver_version": ORIENTATION_RESOLVER_VERSION,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return OutcomeOrientation(
        yes_team_id=yes_team_id,
        no_team_id=no_team_id,
        mapping_method=f"{ORIENTATION_RESOLVER_VERSION}:{method}",
        input_fingerprint=hashlib.sha256(encoded).hexdigest(),
    )
