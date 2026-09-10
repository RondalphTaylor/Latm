from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.services.nfl_research.baseline import NflResearchGame, evaluate_games


def game(
    identity: int = 1,
    *,
    season: int = 2018,
    week: int = 1,
    home: int = 1,
    away: int = 2,
    home_score: int = 20,
    away_score: int = 10,
    kickoff: datetime | None = None,
) -> NflResearchGame:
    start = kickoff or datetime(season, 9, 1, tzinfo=UTC) + timedelta(weeks=week - 1)
    return NflResearchGame(
        event_id=UUID(int=identity),
        provider_event_id=str(identity),
        season=season,
        week=week,
        scheduled_start=start,
        home_team_id=UUID(int=home),
        away_team_id=UUID(int=away),
        home_score=home_score,
        away_score=away_score,
        source_last_seen=start + timedelta(days=1),
    )


def test_tie_is_half_payout_not_win_label() -> None:
    report = evaluate_games([game(home_score=10)])
    row = report.games[0]
    assert row.expected_home_payout == row.actual_home_payout == 0.5
    assert report.split_metrics[0].mean_squared_payout_error == 0
    assert report.split_metrics[0].constant_half_mean_squared_payout_error == 0
    assert report.research_only and not report.promotion_ready and not report.coverage_verified


def test_elo_update_and_prior_benchmark_use_only_prior_weeks() -> None:
    report = evaluate_games([game(), game(2, week=2)])
    first, second = report.games
    assert first.home_rating == first.away_rating == 1500
    assert first.prior_home_payout == 0.5
    assert second.home_rating == 1510
    assert second.away_rating == 1490
    assert second.expected_home_payout == pytest.approx(1 / (1 + 10 ** (-20 / 400)))
    assert second.prior_home_payout == 1
    assert second.prior_game_count == 1


def test_same_week_games_are_batched_even_with_different_kickoffs() -> None:
    first = game()
    later = game(2, home=3, away=4, kickoff=first.scheduled_start + timedelta(days=3))
    next_week = game(3, week=2)
    report = evaluate_games([first, later, next_week])
    assert report.games[0].prior_game_count == report.games[1].prior_game_count == 0
    assert report.games[1].prior_home_payout == 0.5
    assert report.games[2].prior_game_count == 2


def test_future_score_changes_leave_past_predictions_unchanged() -> None:
    first = game()
    second = game(2, week=2)
    before = evaluate_games([first, second])
    after = evaluate_games([first, game(2, week=2, home_score=0, away_score=40)])
    assert before.games[0] == after.games[0]
    assert before.games[1].expected_home_payout == after.games[1].expected_home_payout
    assert before.input_fingerprint != after.input_fingerprint


def test_replay_is_independent_of_input_order() -> None:
    games = [game(), game(2, week=2), game(3, season=2023), game(4, season=2025)]
    assert evaluate_games(games) == evaluate_games(list(reversed(games)))


def test_fixed_splits_and_offseason_regression() -> None:
    report = evaluate_games([game(season=2022), game(2, season=2023), game(3, season=2025)])
    assert [row.split for row in report.games] == ["development", "validation", "test"]
    assert [metric.count for metric in report.split_metrics] == [1, 1, 1]
    assert report.games[1].home_rating == pytest.approx(1500 + 10 * (2 / 3))
    assert report.config.home_advantage == 0
    assert len(report.season_coverage) == 8
    assert report.season_coverage[0].game_count == 0
    assert report.season_coverage[-1].completeness == "unverified"


def test_calibration_and_metric_denominators() -> None:
    report = evaluate_games([game(), game(2, home=3, away=4, home_score=10)])
    metrics = report.split_metrics[0]
    assert metrics.count == 2
    assert metrics.mean_squared_payout_error == 0.125
    assert metrics.prior_home_mean_squared_payout_error == 0.125
    assert sum(bin.count for bin in metrics.calibration_bins) == 2
    assert metrics.calibration_bins[5].mean_actual_payout == 0.75
    assert report.split_metrics[1].mean_squared_payout_error is None


def test_empty_dataset_is_blocked() -> None:
    with pytest.raises(ValueError, match="blocked"):
        evaluate_games([])


@pytest.mark.parametrize(
    "games",
    [
        [game(), game()],
        [game(), game(2, home=1, away=3)],
        [game(1, week=1, kickoff=datetime(2018, 9, 10, tzinfo=UTC)), game(2, week=2)],
    ],
)
def test_duplicate_and_chronology_inputs_fail_closed(games: list[NflResearchGame]) -> None:
    with pytest.raises(ValueError):
        evaluate_games(games)


def test_duplicate_provider_id_rejected_even_with_distinct_local_identity() -> None:
    other = game(2, week=2).model_copy(update={"provider_event_id": "1"})
    with pytest.raises(ValueError, match="duplicate"):
        evaluate_games([game(), other])


@pytest.mark.parametrize(
    "changes",
    [
        {"home_score": -1},
        {"home_score": True},
        {"week": 19},
        {"season": 2026},
        {"away_team_id": UUID(int=1)},
        {"scheduled_start": "2018-09-01T00:00:00"},
        {"scheduled_start": "2019-09-01T00:00:00Z"},
        {"source_last_seen": "2018-08-01T00:00:00Z"},
    ],
)
def test_invalid_input_rejected(changes: dict[str, object]) -> None:
    values = game().model_dump()
    values.update(changes)
    with pytest.raises(ValidationError):
        NflResearchGame.model_validate(values)


def test_january_kickoff_belongs_to_previous_season() -> None:
    row = game(week=17, kickoff=datetime(2019, 1, 1, tzinfo=UTC))
    assert evaluate_games([row]).games[0].input_snapshot.season == 2018
