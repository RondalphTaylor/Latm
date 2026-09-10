from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain.nfl_shadow import NflShadowTarget
from app.services.nfl_research.baseline import NflResearchGame, evaluate_games
from app.services.nfl_research.shadow import NFL_SHADOW_SEED_FINGERPRINT, build_shadow_prediction

_AS_OF = datetime(2026, 9, 10, 12, tzinfo=UTC)


@pytest.fixture(scope="module")
def history() -> list[NflResearchGame]:
    archive = Path(__file__).resolve().parents[2] / "docs/research/nfl-baseline-2026-09-10"
    rows: list[NflResearchGame] = []
    for season in range(2018, 2026):
        rows.extend(
            NflResearchGame.model_validate(row)
            for row in json.loads((archive / f"inputs-{season}.json").read_text(encoding="utf-8"))
        )
    return rows


@pytest.fixture
def target(history: list[NflResearchGame]) -> NflShadowTarget:
    last = history[-1]
    return NflShadowTarget(
        event_id=UUID(int=2026001),
        provider_event_id="shadow-test-game",
        season=2026,
        week=1,
        scheduled_start=_AS_OF + timedelta(hours=12),
        home_team_id=last.home_team_id,
        away_team_id=last.away_team_id,
        source_last_seen=_AS_OF - timedelta(minutes=5),
    )


def test_real_archived_seed_is_pinned_and_replays_exactly(
    history: list[NflResearchGame], target: NflShadowTarget
) -> None:
    prediction = build_shadow_prediction(history, target, _AS_OF)
    replay = build_shadow_prediction(list(reversed(history)), target, _AS_OF)
    assert prediction == replay
    assert prediction.seed_fingerprint == NFL_SHADOW_SEED_FINGERPRINT
    assert prediction.research_only and not prediction.trading_enabled
    assert prediction.configuration.rating_policy == "frozen_preseason2026"
    assert prediction.expected_home_payout + prediction.expected_away_payout == Decimal("1")
    assert prediction.expected_home_payout.as_tuple().exponent == -6


def test_final_seed_ratings_include_ties_then_regress_one_offseason(
    history: list[NflResearchGame], target: NflShadowTarget
) -> None:
    report = evaluate_games(history)
    assert any(row.actual_home_payout == 0.5 for row in report.games)
    row = next(
        row
        for row in reversed(report.games)
        if target.home_team_id in {row.input_snapshot.home_team_id, row.input_snapshot.away_team_id}
    )
    delta = 20 * (row.actual_home_payout - row.expected_home_payout)
    postgame = (
        row.home_rating + delta
        if target.home_team_id == row.input_snapshot.home_team_id
        else row.away_rating - delta
    )
    result = build_shadow_prediction(history, target, _AS_OF)
    assert result.home_rating == pytest.approx(1500 + (postgame - 1500) * (2 / 3))


def test_team_inversion_swaps_payouts_without_home_advantage(
    history: list[NflResearchGame], target: NflShadowTarget
) -> None:
    original = build_shadow_prediction(history, target, _AS_OF)
    reversed_target = target.model_copy(
        update={"home_team_id": target.away_team_id, "away_team_id": target.home_team_id}
    )
    inverted = build_shadow_prediction(history, reversed_target, _AS_OF)
    assert original.expected_home_payout == inverted.expected_away_payout
    assert original.expected_away_payout == inverted.expected_home_payout
    assert original.target_fingerprint != inverted.target_fingerprint


@pytest.mark.parametrize(
    "as_of", [_AS_OF.replace(tzinfo=None), _AS_OF + timedelta(hours=12), _AS_OF + timedelta(days=1)]
)
def test_naive_or_after_kickoff_asof_rejected(
    history: list[NflResearchGame], target: NflShadowTarget, as_of: datetime
) -> None:
    with pytest.raises(ValueError):
        build_shadow_prediction(history, target, as_of)


@pytest.mark.parametrize(
    "observation",
    [_AS_OF - timedelta(hours=24, microseconds=1), _AS_OF + timedelta(microseconds=1)],
)
def test_stale_or_future_target_observation_rejected(
    history: list[NflResearchGame], target: NflShadowTarget, observation: datetime
) -> None:
    with pytest.raises(ValueError):
        build_shadow_prediction(
            history, target.model_copy(update={"source_last_seen": observation}), _AS_OF
        )


def test_exact_24h_freshness_boundary_is_allowed(
    history: list[NflResearchGame], target: NflShadowTarget
) -> None:
    result = build_shadow_prediction(
        history,
        target.model_copy(update={"source_last_seen": _AS_OF - timedelta(hours=24)}),
        _AS_OF,
    )
    assert result.research_only


def test_refresh_changes_snapshot_but_not_semantic_target_identity(
    history: list[NflResearchGame], target: NflShadowTarget
) -> None:
    original = build_shadow_prediction(history, target, _AS_OF)
    refreshed = build_shadow_prediction(
        history, target.model_copy(update={"source_last_seen": _AS_OF}), _AS_OF
    )
    assert original.target_fingerprint == refreshed.target_fingerprint
    assert original.target_snapshot != refreshed.target_snapshot
    assert original.expected_home_payout == refreshed.expected_home_payout


@pytest.mark.parametrize("change", ["gap", "score", "observation"])
def test_seed_gaps_corrections_or_refresh_require_new_release(
    history: list[NflResearchGame], target: NflShadowTarget, change: str
) -> None:
    changed = list(history)
    if change == "gap":
        changed.pop()
    elif change == "score":
        changed[0] = changed[0].model_copy(update={"home_score": changed[0].home_score + 1})
    else:
        changed[0] = changed[0].model_copy(update={"source_last_seen": _AS_OF})
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        build_shadow_prediction(changed, target, _AS_OF)


def test_seed_not_observed_at_asof_rejected(
    history: list[NflResearchGame], target: NflShadowTarget
) -> None:
    changed = [
        history[0].model_copy(update={"source_last_seen": _AS_OF + timedelta(seconds=1)}),
        *history[1:],
    ]
    with pytest.raises(ValueError, match="seed source observation"):
        build_shadow_prediction(changed, target, _AS_OF)


def test_unknown_team_is_blocked_without_cold_start(
    history: list[NflResearchGame], target: NflShadowTarget
) -> None:
    with pytest.raises(ValueError, match="cold starts"):
        build_shadow_prediction(
            history, target.model_copy(update={"home_team_id": UUID(int=999)}), _AS_OF
        )


def test_late_season_uses_same_frozen_model_with_warning(
    history: list[NflResearchGame], target: NflShadowTarget
) -> None:
    initial = build_shadow_prediction(history, target, _AS_OF)
    late_asof = datetime(2026, 12, 1, tzinfo=UTC)
    late = build_shadow_prediction(
        history,
        target.model_copy(
            update={
                "week": 14,
                "scheduled_start": late_asof + timedelta(days=1),
                "source_last_seen": late_asof,
            }
        ),
        late_asof,
    )
    assert initial.expected_home_payout == late.expected_home_payout
    assert any("stale" in warning for warning in late.warnings)


@pytest.mark.parametrize(
    "changes",
    [
        {"season": 2025},
        {"week": 19},
        {"home_score": 24},
        {"scheduled_start": "2026-09-10T20:00:00"},
        {"scheduled_start": "2026-08-10T20:00:00Z"},
    ],
)
def test_target_rejects_wrong_season_scores_and_ambiguous_times(
    target: NflShadowTarget, changes: dict[str, object]
) -> None:
    payload = target.model_dump()
    payload.update(changes)
    with pytest.raises(ValidationError):
        NflShadowTarget.model_validate(payload)
