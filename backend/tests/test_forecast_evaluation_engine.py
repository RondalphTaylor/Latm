from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain.forecast_evaluation import (
    ForecastEvaluationInput,
    ForecastEvaluationPolicy,
)
from app.domain.forecasts import ForecastPurpose
from app.services.evaluation.forecast_engine import (
    DeterministicForecastEvaluationEngine,
    effective_forecast_evaluation_policy_version,
    forecast_evaluation_input_fingerprint,
    forecast_evaluation_policy_fingerprint,
    forecast_outcome_fingerprint,
)

TIP = datetime(2026, 8, 18, 20, tzinfo=UTC)
EVALUATED_AT = datetime(2026, 8, 19, 12, tzinfo=UTC)
HOME_TEAM_ID = UUID(int=101)
AWAY_TEAM_ID = UUID(int=102)


def evaluation_input(
    *,
    event_number: int = 1,
    forecast_number: int = 1001,
    model_number: int = 201,
    probability: Decimal = Decimal("0.700000"),
    home_won: bool = True,
    purpose: ForecastPurpose = ForecastPurpose.OPERATIONAL,
    overrides: dict[str, object] | None = None,
    **updates: object,
) -> ForecastEvaluationInput:
    home_score, away_score = (110, 100) if home_won else (100, 110)
    forecast_as_of = TIP - timedelta(hours=2)
    generated_at = forecast_as_of
    if purpose is ForecastPurpose.HISTORICAL_REPLAY:
        forecast_as_of = TIP
        generated_at = TIP + timedelta(hours=4)
    values: dict[str, object] = {
        "forecast_id": UUID(int=forecast_number),
        "sports_event_id": UUID(int=event_number),
        "model_version_id": UUID(int=model_number),
        "model_name": "nba_elo",
        "model_version": f"1.0.0+cfg.{model_number:012x}",
        "purpose": purpose,
        "forecast_input_fingerprint": f"{forecast_number:064x}",
        "model_configuration_fingerprint": f"{model_number:064x}",
        "home_team_id": HOME_TEAM_ID,
        "away_team_id": AWAY_TEAM_ID,
        "home_win_probability": probability,
        "forecast_as_of": forecast_as_of,
        "forecast_generated_at": generated_at,
        "result_provider_name": "balldontlie",
        "result_league": "nba",
        "result_status": "final",
        "result_postponed": False,
        "result_event_date": TIP.date(),
        "result_scheduled_start_time": TIP,
        "result_home_team_id": HOME_TEAM_ID,
        "result_away_team_id": AWAY_TEAM_ID,
        "result_home_score": home_score,
        "result_away_score": away_score,
        "result_source_last_seen_at": TIP + timedelta(hours=4),
        "evaluated_at": EVALUATED_AT,
    }
    if overrides is not None:
        values.update(overrides)
    values.update(updates)
    return ForecastEvaluationInput.model_validate(values)


def engine(
    policy: ForecastEvaluationPolicy | None = None,
) -> DeterministicForecastEvaluationEngine:
    return DeterministicForecastEvaluationEngine(policy)


def test_binary_home_brier_and_correct_home_prediction_are_exact() -> None:
    result = engine().evaluate(evaluation_input())

    assert result.home_won is True
    assert result.brier_score == Decimal("0.090000000000")
    assert result.predicted_home_win is True
    assert result.prediction_correct is True


def test_home_loss_uses_zero_outcome_and_reports_incorrect_prediction() -> None:
    result = engine().evaluate(evaluation_input(home_won=False))

    assert result.home_won is False
    assert result.brier_score == Decimal("0.490000000000")
    assert result.predicted_home_win is True
    assert result.prediction_correct is False


def test_exact_half_probability_abstains_from_accuracy() -> None:
    result = engine().evaluate(evaluation_input(probability=Decimal("0.500000")))

    assert result.brier_score == Decimal("0.250000000000")
    assert result.predicted_home_win is None
    assert result.prediction_correct is None


@pytest.mark.parametrize(
    ("probability", "home_won", "expected"),
    [
        (Decimal("0.000000"), False, Decimal("0.000000000000")),
        (Decimal("0.000000"), True, Decimal("1.000000000000")),
        (Decimal("1.000000"), True, Decimal("0.000000000000")),
        (Decimal("1.000000"), False, Decimal("1.000000000000")),
    ],
)
def test_brier_boundaries(
    probability: Decimal,
    home_won: bool,
    expected: Decimal,
) -> None:
    assert (
        engine().evaluate(evaluation_input(probability=probability, home_won=home_won)).brier_score
        == expected
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"result_home_score": 100, "result_away_score": 100},
        {"result_away_team_id": UUID(int=103)},
        {"result_postponed": True},
        {"forecast_as_of": TIP},
        {"forecast_generated_at": TIP - timedelta(hours=1)},
        {"forecast_generated_at": TIP},
        {"result_source_last_seen_at": EVALUATED_AT + timedelta(seconds=1)},
    ],
)
def test_invalid_or_non_pregame_observations_are_rejected(
    updates: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        evaluation_input(overrides=updates)


def test_historical_replay_requires_tip_cutoff_but_can_be_generated_later() -> None:
    source = evaluation_input(purpose=ForecastPurpose.HISTORICAL_REPLAY)

    assert engine().evaluate(source).purpose is ForecastPurpose.HISTORICAL_REPLAY
    with pytest.raises(ValidationError, match="scheduled tip as cutoff"):
        evaluation_input(
            purpose=ForecastPurpose.HISTORICAL_REPLAY,
            forecast_as_of=TIP - timedelta(seconds=1),
        )


def test_semantic_fingerprints_ignore_observation_and_evaluation_times() -> None:
    source = evaluation_input()
    repeated_observation = evaluation_input(
        result_source_last_seen_at=TIP + timedelta(hours=5),
        evaluated_at=EVALUATED_AT + timedelta(hours=1),
    )
    evaluator = engine()

    assert forecast_outcome_fingerprint(source) == (
        forecast_outcome_fingerprint(repeated_observation)
    )
    assert forecast_evaluation_input_fingerprint(source, evaluator.policy) == (
        forecast_evaluation_input_fingerprint(repeated_observation, evaluator.policy)
    )
    assert evaluator.evaluate(source).input_fingerprint == (
        evaluator.evaluate(repeated_observation).input_fingerprint
    )


def test_result_event_date_changes_outcome_and_evaluation_fingerprints() -> None:
    source = evaluation_input()
    corrected_date = evaluation_input(
        result_event_date=source.result_event_date + timedelta(days=1)
    )
    evaluator = engine()

    assert forecast_outcome_fingerprint(source) != forecast_outcome_fingerprint(corrected_date)
    assert forecast_evaluation_input_fingerprint(source, evaluator.policy) != (
        forecast_evaluation_input_fingerprint(corrected_date, evaluator.policy)
    )


def test_score_correction_changes_outcome_and_evaluation_fingerprints() -> None:
    source = evaluation_input(home_won=True)
    corrected = evaluation_input(home_won=False)
    evaluator = engine()

    first = evaluator.evaluate(source)
    second = evaluator.evaluate(corrected)

    assert first.outcome_fingerprint != second.outcome_fingerprint
    assert first.input_fingerprint != second.input_fingerprint
    assert first.brier_score != second.brier_score


def test_policy_fingerprint_and_version_bind_calibration_configuration() -> None:
    baseline = ForecastEvaluationPolicy()
    changed = ForecastEvaluationPolicy(calibration_bin_count=20)

    assert forecast_evaluation_policy_fingerprint(baseline) != (
        forecast_evaluation_policy_fingerprint(changed)
    )
    assert effective_forecast_evaluation_policy_version(baseline).startswith("1.0.0+cfg.")
    assert effective_forecast_evaluation_policy_version(baseline) != (
        effective_forecast_evaluation_policy_version(changed)
    )


@pytest.mark.parametrize("bin_count", [1, 51])
def test_calibration_bin_count_is_bounded(bin_count: int) -> None:
    with pytest.raises(ValidationError):
        ForecastEvaluationPolicy(calibration_bin_count=bin_count)


def test_empty_calibration_returns_every_configured_empty_bin() -> None:
    report = engine().calibrate(())

    assert report.sample_size == 0
    assert report.mean_brier_score is None
    assert report.expected_calibration_error is None
    assert report.maximum_calibration_error is None
    assert len(report.bins) == 10
    assert all(item.sample_size == 0 for item in report.bins)
    assert all(item.mean_prediction is None for item in report.bins)
    assert report.bins[-1].upper_bound == Decimal("1.000000000000")
    assert report.bins[-1].upper_bound_inclusive is True


def test_calibration_uses_exact_fixed_width_boundaries_and_raw_sum_ece() -> None:
    evaluator = engine()
    evaluations = evaluator.evaluate_many(
        (
            evaluation_input(
                event_number=1,
                forecast_number=1001,
                probability=Decimal("0.050000"),
                home_won=True,
            ),
            evaluation_input(
                event_number=2,
                forecast_number=1002,
                probability=Decimal("0.100000"),
                home_won=False,
            ),
            evaluation_input(
                event_number=3,
                forecast_number=1003,
                probability=Decimal("1.000000"),
                home_won=True,
            ),
        )
    )

    report = evaluator.calibrate(evaluations)

    assert report.sample_size == 3
    assert report.mean_brier_score == Decimal("0.304166666667")
    assert report.expected_calibration_error == Decimal("0.350000000000")
    assert report.maximum_calibration_error == Decimal("0.950000000000")
    assert report.bins[0].sample_size == 1
    assert report.bins[0].mean_prediction == Decimal("0.050000000000")
    assert report.bins[0].observed_frequency == Decimal("1.000000000000")
    assert report.bins[0].signed_calibration_gap == Decimal("0.950000000000")
    assert report.bins[1].sample_size == 1
    assert report.bins[1].mean_prediction == Decimal("0.100000000000")
    assert report.bins[9].sample_size == 1


def test_calibration_bin_count_can_be_configured_from_two_through_fifty() -> None:
    two_bin_engine = engine(ForecastEvaluationPolicy(calibration_bin_count=2))
    evaluations = two_bin_engine.evaluate_many(
        (
            evaluation_input(event_number=1, forecast_number=1001, probability=Decimal("0.49")),
            evaluation_input(event_number=2, forecast_number=1002, probability=Decimal("0.50")),
        )
    )

    report = two_bin_engine.calibrate(evaluations)

    assert len(report.bins) == 2
    assert report.bins[0].sample_size == 1
    assert report.bins[1].sample_size == 1
    assert ForecastEvaluationPolicy(calibration_bin_count=50).calibration_bin_count == 50


def test_calibration_rejects_mixed_models_and_duplicate_events() -> None:
    evaluator = engine()
    mixed_models = evaluator.evaluate_many(
        (
            evaluation_input(event_number=1, forecast_number=1001, model_number=201),
            evaluation_input(event_number=2, forecast_number=1002, model_number=202),
        )
    )
    duplicate_event = evaluator.evaluate_many(
        (
            evaluation_input(event_number=1, forecast_number=1001),
            evaluation_input(event_number=1, forecast_number=1002),
        )
    )

    with pytest.raises(ValueError, match="one model version"):
        evaluator.calibrate(mixed_models)
    with pytest.raises(ValueError, match="one selected evaluation per event"):
        evaluator.calibrate(duplicate_event)


def test_model_summaries_separate_versions_and_exclude_abstentions_from_accuracy() -> None:
    evaluator = engine()
    evaluations = evaluator.evaluate_many(
        (
            evaluation_input(
                event_number=1,
                forecast_number=1001,
                model_number=201,
                probability=Decimal("0.800000"),
                home_won=True,
            ),
            evaluation_input(
                event_number=2,
                forecast_number=1002,
                model_number=201,
                probability=Decimal("0.500000"),
                home_won=False,
            ),
            evaluation_input(
                event_number=1,
                forecast_number=2001,
                model_number=202,
                probability=Decimal("0.600000"),
                home_won=True,
            ),
        )
    )

    summaries = evaluator.summarize_models(evaluations)

    assert len(summaries) == 2
    first = next(item for item in summaries if item.model_version_id == UUID(int=201))
    assert first.sample_size == 2
    assert first.decisive_prediction_count == 1
    assert first.correct_prediction_count == 1
    assert first.prediction_accuracy == Decimal("1.000000000000")
    assert first.mean_brier_score == Decimal("0.145000000000")


def test_paired_comparison_uses_only_common_events() -> None:
    evaluator = engine()
    evaluations = evaluator.evaluate_many(
        (
            evaluation_input(
                event_number=1,
                forecast_number=1001,
                model_number=201,
                probability=Decimal("0.800000"),
                home_won=True,
            ),
            evaluation_input(
                event_number=2,
                forecast_number=1002,
                model_number=201,
                probability=Decimal("0.400000"),
                home_won=True,
            ),
            evaluation_input(
                event_number=2,
                forecast_number=2002,
                model_number=202,
                probability=Decimal("0.600000"),
                home_won=True,
            ),
            evaluation_input(
                event_number=3,
                forecast_number=2003,
                model_number=202,
                probability=Decimal("0.900000"),
                home_won=True,
            ),
        )
    )

    comparison = evaluator.compare_models(
        evaluations,
        model_a_version_id=UUID(int=201),
        model_b_version_id=UUID(int=202),
        purpose=ForecastPurpose.OPERATIONAL,
    )

    assert comparison.model_a_sample_size == 2
    assert comparison.model_b_sample_size == 2
    assert comparison.paired_sample_size == 1
    assert comparison.paired_event_ids == (UUID(int=2),)
    assert comparison.model_a_unpaired_count == 1
    assert comparison.model_b_unpaired_count == 1
    assert comparison.model_a_mean_brier == Decimal("0.360000000000")
    assert comparison.model_b_mean_brier == Decimal("0.160000000000")
    assert comparison.mean_brier_delta_a_minus_b == Decimal("0.200000000000")
    assert comparison.model_b_lower_brier_count == 1


def test_paired_comparison_excludes_same_event_with_different_outcome_fingerprint() -> None:
    evaluator = engine()
    evaluations = evaluator.evaluate_many(
        (
            evaluation_input(
                event_number=1,
                forecast_number=1001,
                model_number=201,
                home_won=True,
            ),
            evaluation_input(
                event_number=1,
                forecast_number=2001,
                model_number=202,
                home_won=False,
            ),
        )
    )

    comparison = evaluator.compare_models(
        evaluations,
        model_a_version_id=UUID(int=201),
        model_b_version_id=UUID(int=202),
        purpose=ForecastPurpose.OPERATIONAL,
    )

    assert comparison.paired_sample_size == 0
    assert comparison.outcome_mismatch_count == 1
    assert comparison.model_a_mean_brier is None
    assert comparison.model_b_mean_brier is None
    assert comparison.mean_brier_delta_a_minus_b is None


def test_summaries_and_comparison_reject_duplicate_selected_event_rows() -> None:
    evaluator = engine()
    duplicate = evaluator.evaluate_many(
        (
            evaluation_input(event_number=1, forecast_number=1001, model_number=201),
            evaluation_input(event_number=1, forecast_number=1002, model_number=201),
            evaluation_input(event_number=1, forecast_number=2001, model_number=202),
        )
    )

    with pytest.raises(ValueError, match="one selected evaluation per event"):
        evaluator.summarize_models(duplicate)
    with pytest.raises(ValueError, match="one selected evaluation per event"):
        evaluator.compare_models(
            duplicate,
            model_a_version_id=UUID(int=201),
            model_b_version_id=UUID(int=202),
            purpose=ForecastPurpose.OPERATIONAL,
        )
