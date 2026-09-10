from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain.nfl_shadow_evaluation import NflShadowFinalResult, NflShadowScoringInput
from app.services.nfl_research.shadow_evaluation import aggregate_shadow_labels, build_shadow_label

_KICKOFF = datetime(2026, 9, 13, 17, tzinfo=UTC)
_OBSERVED = _KICKOFF + timedelta(hours=4)


def snapshot(
    identity: int = 1, *, away_yes: bool = False, model: str = "v1", seed: str = "a" * 64
) -> NflShadowScoringInput:
    return NflShadowScoringInput(
        snapshot_id=UUID(int=identity * 100),
        event_id=UUID(int=identity),
        provider_event_id=str(identity),
        model_version=model,
        seed_fingerprint=seed,
        generated_at=_KICKOFF - timedelta(hours=1),
        kickoff=_KICKOFF,
        home_team_id=UUID(int=10),
        away_team_id=UUID(int=20),
        yes_team_id=UUID(int=20 if away_yes else 10),
        expected_home_payout=Decimal("0.600000"),
        expected_yes_payout=Decimal("0.400000" if away_yes else "0.600000"),
    )


def result(identity: int = 1, *, home: int = 24, away: int = 17) -> NflShadowFinalResult:
    return NflShadowFinalResult(
        event_id=UUID(int=identity),
        provider_event_id=str(identity),
        scheduled_start=_KICKOFF,
        home_team_id=UUID(int=10),
        away_team_id=UUID(int=20),
        home_score=home,
        away_score=away,
        source_last_seen=_OBSERVED,
        status="final",
    )


@pytest.mark.parametrize(
    "home,away,payout,error,benchmark",
    [
        (24, 17, "1", "0.16", "0.25"),
        (17, 24, "0", "0.36", "0.25"),
        (17, 17, "0.5", "0.01", "0"),
    ],
)
@pytest.mark.parametrize("away_yes", [False, True])
def test_final_scores_ties_and_orientation(
    home: int, away: int, payout: str, error: str, benchmark: str, away_yes: bool
) -> None:
    label = build_shadow_label(snapshot(away_yes=away_yes), result(home=home, away=away), _OBSERVED)
    assert label.actual_home_payout == Decimal(payout)
    assert label.actual_yes_payout == (
        Decimal(1) - Decimal(payout) if away_yes else Decimal(payout)
    )
    assert label.squared_home_payout_error == Decimal(error)
    assert label.squared_home_payout_error.as_tuple().exponent == -12
    assert label.constant_half_squared_error == Decimal(benchmark)
    assert label.research_only and not label.trading_enabled


def test_timestamp_refresh_replays_but_score_corrections_append() -> None:
    original = build_shadow_label(snapshot(), result(), _OBSERVED)
    refreshed = result().model_copy(update={"source_last_seen": _OBSERVED + timedelta(hours=1)})
    replay = build_shadow_label(snapshot(), refreshed, _OBSERVED + timedelta(hours=2))
    assert original.label_fingerprint == replay.label_fingerprint
    assert original.result_fingerprint == replay.result_fingerprint
    assert original.result != replay.result
    corrected = build_shadow_label(snapshot(), result(home=25), _OBSERVED)
    assert original.actual_home_payout == corrected.actual_home_payout
    assert original.result_fingerprint != corrected.result_fingerprint
    assert original.label_fingerprint != corrected.label_fingerprint
    reverted = build_shadow_label(snapshot(), refreshed, _OBSERVED + timedelta(hours=3))
    assert reverted.label_fingerprint == original.label_fingerprint


@pytest.mark.parametrize(
    "changes",
    [
        {"event_id": UUID(int=2)},
        {"provider_event_id": "wrong"},
        {"home_team_id": UUID(int=30)},
        {"scheduled_start": _KICKOFF + timedelta(minutes=1)},
    ],
)
def test_wrong_event_teams_or_kickoff_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="does not match"):
        build_shadow_label(snapshot(), result().model_copy(update=changes), _OBSERVED)


@pytest.mark.parametrize(
    "changes",
    [
        {"generated_at": _KICKOFF},
        {"generated_at": _KICKOFF.replace(tzinfo=None)},
        {"yes_team_id": UUID(int=30)},
        {"away_team_id": UUID(int=10)},
        {"expected_yes_payout": "0.3"},
        {"expected_home_payout": "NaN"},
        {"expected_home_payout": "Infinity"},
        {"expected_home_payout": "-0.1"},
    ],
)
def test_bad_snapshot_rejected(changes: dict[str, object]) -> None:
    payload = snapshot().model_dump()
    payload.update(changes)
    with pytest.raises(ValidationError):
        NflShadowScoringInput.model_validate(payload)


@pytest.mark.parametrize(
    "changes",
    [
        {"home_score": None},
        {"home_score": True},
        {"home_score": -1},
        {"status": "in_progress"},
        {"status": "suspended"},
        {"source_last_seen": _KICKOFF - timedelta(seconds=1)},
    ],
)
def test_missing_scores_or_nonfinal_results_rejected(changes: dict[str, object]) -> None:
    payload = result().model_dump()
    payload.update(changes)
    with pytest.raises(ValidationError):
        NflShadowFinalResult.model_validate(payload)


@pytest.mark.parametrize(
    "evaluated", [_OBSERVED - timedelta(seconds=1), _OBSERVED.replace(tzinfo=None)]
)
def test_future_observation_and_naive_evaluation_rejected(evaluated: datetime) -> None:
    with pytest.raises(ValueError):
        build_shadow_label(snapshot(), result(), evaluated)


def test_decimal_semantics_not_string_format_determine_fingerprint() -> None:
    simple = snapshot().model_dump()
    simple.update(expected_home_payout="0.6", expected_yes_payout="0.6")
    assert (
        build_shadow_label(snapshot(), result(), _OBSERVED).snapshot_fingerprint
        == build_shadow_label(
            NflShadowScoringInput.model_validate(simple), result(), _OBSERVED
        ).snapshot_fingerprint
    )


def test_aggregate_one_event_once_and_report_calibration() -> None:
    rows = [
        build_shadow_label(snapshot(), result(), _OBSERVED),
        build_shadow_label(snapshot(2), result(2, home=17), _OBSERVED),
    ]
    summary = aggregate_shadow_labels(rows)
    group = summary.model_groups[0]
    assert summary.count == group.count == 2
    assert group.tie_count == 1
    assert group.mean_squared_home_payout_error == Decimal("0.085000000000")
    assert group.constant_half_mean_squared_error == Decimal("0.125000000000")
    assert group.calibration_bins[6].count == 2
    assert group.calibration_bins[6].mean_actual_payout == Decimal("0.75")
    assert group.calibration_bins[0].mean_actual_payout is None
    assert aggregate_shadow_labels(list(reversed(rows))) == summary


def test_dual_contracts_and_repeated_labels_require_canonicalization() -> None:
    home = build_shadow_label(snapshot(), result(), _OBSERVED)
    away_input = snapshot(away_yes=True).model_copy(update={"snapshot_id": UUID(int=999)})
    away = build_shadow_label(away_input, result(), _OBSERVED)
    with pytest.raises(ValueError, match="canonicalize"):
        aggregate_shadow_labels([home, away])
    with pytest.raises(ValueError, match="canonicalize"):
        aggregate_shadow_labels([home, home])


def test_models_and_seed_versions_never_pool_errors() -> None:
    rows = [
        build_shadow_label(snapshot(model="v2"), result(), _OBSERVED),
        build_shadow_label(snapshot(seed="b" * 64), result(), _OBSERVED),
        build_shadow_label(snapshot(), result(), _OBSERVED),
    ]
    summary = aggregate_shadow_labels(rows)
    assert len(summary.model_groups) == 3
    assert all(group.count == 1 for group in summary.model_groups)
    assert summary.mean_squared_home_payout_error is None
    assert summary.constant_half_mean_squared_error is None


def test_empty_summary_metrics_are_null() -> None:
    summary = aggregate_shadow_labels([])
    assert summary.count == 0
    assert summary.model_groups == ()
    assert summary.mean_squared_home_payout_error is None


def test_tampered_scoring_scalar_is_rejected() -> None:
    label = build_shadow_label(snapshot(), result(), _OBSERVED)
    with pytest.raises(ValueError, match="integrity"):
        aggregate_shadow_labels(
            [label.model_copy(update={"squared_home_payout_error": Decimal("0")})]
        )
