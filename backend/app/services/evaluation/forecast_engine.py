from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal, localcontext
from uuid import UUID

from pydantic import JsonValue

from app.domain.forecast_evaluation import (
    ForecastCalibrationBin,
    ForecastCalibrationReport,
    ForecastEvaluation,
    ForecastEvaluationInput,
    ForecastEvaluationPolicy,
    ModelEvaluationSummary,
    PairedModelComparison,
)
from app.domain.forecasts import ForecastPurpose

_METRIC_QUANTUM = Decimal("0.000000000001")


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def forecast_evaluation_policy_fingerprint(policy: ForecastEvaluationPolicy) -> str:
    """Hash every scoring, calibration, comparison, and precision assumption."""
    return _canonical_hash(
        {
            "policy": policy.model_dump(mode="json"),
            "evaluation_unit": "one_designated_home_bernoulli_observation_per_event",
            "brier_formula": "(home_win_probability-home_won_indicator)^2",
            "accuracy": "home_if_p_gt_0.5_away_if_p_lt_0.5_abstain_if_equal",
            "calibration_bins": "min(floor(p*bin_count),bin_count-1)",
            "ece": "sum(abs(bin_home_wins-bin_probability_sum))/sample_size",
            "mce": "max(abs(bin_home_wins-bin_probability_sum)/bin_sample_size)",
            "comparison": "paired_event_intersection_with_identical_outcome_fingerprint",
            "metric_precision": str(_METRIC_QUANTUM),
            "metric_rounding": "ROUND_HALF_UP",
        }
    )


def effective_forecast_evaluation_policy_version(policy: ForecastEvaluationPolicy) -> str:
    """Return a readable code version bound to the effective policy fingerprint."""
    fingerprint = forecast_evaluation_policy_fingerprint(policy)
    return f"{policy.code_version}+cfg.{fingerprint[:12]}"


def forecast_outcome_fingerprint(source: ForecastEvaluationInput) -> str:
    """Hash semantic final-result fields while excluding repeated observation time."""
    return _canonical_hash(
        {
            "sports_event_id": str(source.sports_event_id),
            "provider_name": source.result_provider_name,
            "league": source.result_league,
            "status": source.result_status,
            "postponed": source.result_postponed,
            "event_date": source.result_event_date.isoformat(),
            "scheduled_start_time": source.result_scheduled_start_time.isoformat(),
            "home_team_id": str(source.result_home_team_id),
            "away_team_id": str(source.result_away_team_id),
            "home_score": source.result_home_score,
            "away_score": source.result_away_score,
        }
    )


def forecast_evaluation_input_fingerprint(
    source: ForecastEvaluationInput,
    policy: ForecastEvaluationPolicy,
) -> str:
    """Hash the exact forecast, semantic outcome, and effective scoring policy."""
    return _canonical_hash(
        {
            "forecast_id": str(source.forecast_id),
            "sports_event_id": str(source.sports_event_id),
            "model_version_id": str(source.model_version_id),
            "model_name": source.model_name,
            "model_version": source.model_version,
            "purpose": source.purpose.value,
            "forecast_input_fingerprint": source.forecast_input_fingerprint,
            "model_configuration_fingerprint": (source.model_configuration_fingerprint),
            "home_team_id": str(source.home_team_id),
            "away_team_id": str(source.away_team_id),
            "home_win_probability": str(source.home_win_probability),
            "forecast_as_of": source.forecast_as_of.isoformat(),
            "forecast_generated_at": source.forecast_generated_at.isoformat(),
            "outcome_fingerprint": forecast_outcome_fingerprint(source),
            "policy_fingerprint": forecast_evaluation_policy_fingerprint(policy),
        }
    )


def _quantize_metric(value: Decimal) -> Decimal:
    return value.quantize(_METRIC_QUANTUM, rounding=ROUND_HALF_UP)


class DeterministicForecastEvaluationEngine:
    """Pure binary scoring, calibration, summary, and paired comparison engine."""

    def __init__(self, policy: ForecastEvaluationPolicy | None = None) -> None:
        self.policy = policy or ForecastEvaluationPolicy()
        self.policy_fingerprint = forecast_evaluation_policy_fingerprint(self.policy)
        self.policy_version = effective_forecast_evaluation_policy_version(self.policy)

    def evaluate(self, source: ForecastEvaluationInput) -> ForecastEvaluation:
        """Score one completed forecast without persistence or external calls."""
        home_won = source.result_home_score > source.result_away_score
        outcome = Decimal("1") if home_won else Decimal("0")
        brier = (source.home_win_probability - outcome) ** 2
        predicted_home = (
            None
            if source.home_win_probability == Decimal("0.5")
            else source.home_win_probability > Decimal("0.5")
        )
        prediction_correct = None if predicted_home is None else predicted_home is home_won
        outcome_fingerprint = forecast_outcome_fingerprint(source)
        input_fingerprint = forecast_evaluation_input_fingerprint(source, self.policy)
        audit_snapshot: dict[str, JsonValue] = {
            "forecast": {
                "id": str(source.forecast_id),
                "sports_event_id": str(source.sports_event_id),
                "model_version_id": str(source.model_version_id),
                "model_name": source.model_name,
                "model_version": source.model_version,
                "purpose": source.purpose.value,
                "input_fingerprint": source.forecast_input_fingerprint,
                "configuration_fingerprint": source.model_configuration_fingerprint,
                "home_team_id": str(source.home_team_id),
                "away_team_id": str(source.away_team_id),
                "home_win_probability": str(source.home_win_probability),
                "forecast_as_of": source.forecast_as_of.isoformat(),
                "generated_at": source.forecast_generated_at.isoformat(),
            },
            "outcome": {
                "provider_name": source.result_provider_name,
                "league": source.result_league,
                "status": source.result_status,
                "postponed": source.result_postponed,
                "event_date": source.result_event_date.isoformat(),
                "scheduled_start_time": (source.result_scheduled_start_time.isoformat()),
                "home_team_id": str(source.result_home_team_id),
                "away_team_id": str(source.result_away_team_id),
                "home_score": source.result_home_score,
                "away_score": source.result_away_score,
                "source_last_seen_at": source.result_source_last_seen_at.isoformat(),
                "fingerprint": outcome_fingerprint,
            },
            "score": {
                "home_won": home_won,
                "brier_score": str(brier),
                "predicted_home_win": predicted_home,
                "prediction_correct": prediction_correct,
            },
            "policy": self.policy.model_dump(mode="json"),
        }
        return ForecastEvaluation(
            forecast_id=source.forecast_id,
            sports_event_id=source.sports_event_id,
            model_version_id=source.model_version_id,
            model_name=source.model_name,
            model_version=source.model_version,
            purpose=source.purpose,
            home_win_probability=source.home_win_probability,
            home_won=home_won,
            result_home_score=source.result_home_score,
            result_away_score=source.result_away_score,
            brier_score=brier,
            predicted_home_win=predicted_home,
            prediction_correct=prediction_correct,
            result_scheduled_start_time=source.result_scheduled_start_time,
            result_source_last_seen_at=source.result_source_last_seen_at,
            outcome_fingerprint=outcome_fingerprint,
            policy_name=self.policy.policy_name,
            policy_version=self.policy_version,
            policy_fingerprint=self.policy_fingerprint,
            input_fingerprint=input_fingerprint,
            evaluated_at=source.evaluated_at,
            audit_snapshot=audit_snapshot,
        )

    def evaluate_many(
        self,
        sources: Sequence[ForecastEvaluationInput],
    ) -> tuple[ForecastEvaluation, ...]:
        """Score a deterministic input sequence without changing its order."""
        return tuple(self.evaluate(source) for source in sources)

    def calibrate(
        self,
        evaluations: Sequence[ForecastEvaluation],
    ) -> ForecastCalibrationReport:
        """Build fixed-width reliability bins for one model-version/purpose group."""
        values = tuple(evaluations)
        self._validate_policy(values)
        self._require_unique_events(values)
        if values:
            group_identity = {
                (
                    item.model_version_id,
                    item.model_name,
                    item.model_version,
                    item.purpose,
                )
                for item in values
            }
            if len(group_identity) != 1:
                raise ValueError("calibration requires exactly one model version and purpose")
            model_id, model_name, model_version, purpose = next(iter(group_identity))
        else:
            model_id = None
            model_name = None
            model_version = None
            purpose = None

        bins: list[list[ForecastEvaluation]] = [
            [] for _ in range(self.policy.calibration_bin_count)
        ]
        for item in values:
            index = min(
                int(item.home_win_probability * self.policy.calibration_bin_count),
                self.policy.calibration_bin_count - 1,
            )
            bins[index].append(item)

        bin_models = tuple(
            self._calibration_bin(index=index, evaluations=tuple(items))
            for index, items in enumerate(bins)
        )
        if values:
            with localcontext() as context:
                context.prec = 40
                sample_size = Decimal(len(values))
                mean_brier = _quantize_metric(
                    sum((item.brier_score for item in values), Decimal("0")) / sample_size
                )
                ece_numerator = sum(
                    (
                        abs(
                            sum(
                                (item.home_win_probability for item in items),
                                Decimal("0"),
                            )
                            - sum(Decimal(int(item.home_won)) for item in items)
                        )
                        for items in bins
                        if items
                    ),
                    Decimal("0"),
                )
                ece = _quantize_metric(ece_numerator / sample_size)
                mce = _quantize_metric(
                    max(
                        abs(
                            sum(
                                (item.home_win_probability for item in items),
                                Decimal("0"),
                            )
                            - sum(Decimal(int(item.home_won)) for item in items)
                        )
                        / Decimal(len(items))
                        for items in bins
                        if items
                    )
                )
        else:
            mean_brier = None
            ece = None
            mce = None
        return ForecastCalibrationReport(
            model_version_id=model_id,
            model_name=model_name,
            model_version=model_version,
            purpose=purpose,
            sample_size=len(values),
            bin_count=self.policy.calibration_bin_count,
            mean_brier_score=mean_brier,
            expected_calibration_error=ece,
            maximum_calibration_error=mce,
            bins=bin_models,
            policy_version=self.policy_version,
            policy_fingerprint=self.policy_fingerprint,
        )

    def summarize_models(
        self,
        evaluations: Sequence[ForecastEvaluation],
    ) -> tuple[ModelEvaluationSummary, ...]:
        """Return one deterministic summary per model-version and purpose group."""
        values = tuple(evaluations)
        self._validate_policy(values)
        groups: dict[
            tuple[UUID, str, str, ForecastPurpose],
            list[ForecastEvaluation],
        ] = defaultdict(list)
        for item in values:
            groups[
                (
                    item.model_version_id,
                    item.model_name,
                    item.model_version,
                    item.purpose,
                )
            ].append(item)

        summaries: list[ModelEvaluationSummary] = []
        for identity in sorted(groups, key=lambda item: (str(item[0]), item[3].value)):
            group = tuple(groups[identity])
            self._require_unique_events(group)
            calibration = self.calibrate(group)
            decisive = tuple(item for item in group if item.prediction_correct is not None)
            correct = sum(item.prediction_correct is True for item in decisive)
            accuracy = (
                None
                if not decisive
                else _quantize_metric(Decimal(correct) / Decimal(len(decisive)))
            )
            assert calibration.mean_brier_score is not None
            assert calibration.expected_calibration_error is not None
            assert calibration.maximum_calibration_error is not None
            summaries.append(
                ModelEvaluationSummary(
                    model_version_id=identity[0],
                    model_name=identity[1],
                    model_version=identity[2],
                    purpose=identity[3],
                    sample_size=len(group),
                    home_wins=sum(item.home_won for item in group),
                    decisive_prediction_count=len(decisive),
                    correct_prediction_count=correct,
                    mean_brier_score=calibration.mean_brier_score,
                    prediction_accuracy=accuracy,
                    expected_calibration_error=(calibration.expected_calibration_error),
                    maximum_calibration_error=(calibration.maximum_calibration_error),
                    policy_version=self.policy_version,
                    policy_fingerprint=self.policy_fingerprint,
                )
            )
        return tuple(summaries)

    def compare_models(
        self,
        evaluations: Sequence[ForecastEvaluation],
        *,
        model_a_version_id: UUID,
        model_b_version_id: UUID,
        purpose: ForecastPurpose,
    ) -> PairedModelComparison:
        """Compare two model versions only on identical event/outcome pairs."""
        if model_a_version_id == model_b_version_id:
            raise ValueError("paired comparison requires distinct model versions")
        selected = tuple(
            item
            for item in evaluations
            if item.purpose is purpose
            and item.model_version_id in {model_a_version_id, model_b_version_id}
        )
        self._validate_policy(selected)
        model_a = self._event_index(
            tuple(item for item in selected if item.model_version_id == model_a_version_id)
        )
        model_b = self._event_index(
            tuple(item for item in selected if item.model_version_id == model_b_version_id)
        )
        common_ids = set(model_a) & set(model_b)
        mismatch_count = sum(
            model_a[event_id].outcome_fingerprint != model_b[event_id].outcome_fingerprint
            for event_id in common_ids
        )
        paired_ids = tuple(
            sorted(
                (
                    event_id
                    for event_id in common_ids
                    if model_a[event_id].outcome_fingerprint
                    == model_b[event_id].outcome_fingerprint
                ),
                key=str,
            )
        )
        if paired_ids:
            with localcontext() as context:
                context.prec = 40
                count = Decimal(len(paired_ids))
                mean_a = _quantize_metric(
                    sum(
                        (model_a[event_id].brier_score for event_id in paired_ids),
                        Decimal("0"),
                    )
                    / count
                )
                mean_b = _quantize_metric(
                    sum(
                        (model_b[event_id].brier_score for event_id in paired_ids),
                        Decimal("0"),
                    )
                    / count
                )
                mean_delta = _quantize_metric(
                    sum(
                        (
                            model_a[event_id].brier_score - model_b[event_id].brier_score
                            for event_id in paired_ids
                        ),
                        Decimal("0"),
                    )
                    / count
                )
            a_lower = sum(
                model_a[event_id].brier_score < model_b[event_id].brier_score
                for event_id in paired_ids
            )
            b_lower = sum(
                model_b[event_id].brier_score < model_a[event_id].brier_score
                for event_id in paired_ids
            )
            equal = len(paired_ids) - a_lower - b_lower
        else:
            mean_a = None
            mean_b = None
            mean_delta = None
            a_lower = 0
            b_lower = 0
            equal = 0
        return PairedModelComparison(
            model_a_version_id=model_a_version_id,
            model_b_version_id=model_b_version_id,
            purpose=purpose,
            model_a_sample_size=len(model_a),
            model_b_sample_size=len(model_b),
            paired_sample_size=len(paired_ids),
            model_a_unpaired_count=len(model_a) - len(paired_ids),
            model_b_unpaired_count=len(model_b) - len(paired_ids),
            outcome_mismatch_count=mismatch_count,
            model_a_mean_brier=mean_a,
            model_b_mean_brier=mean_b,
            mean_brier_delta_a_minus_b=mean_delta,
            model_a_lower_brier_count=a_lower,
            model_b_lower_brier_count=b_lower,
            equal_brier_count=equal,
            paired_event_ids=paired_ids,
            policy_version=self.policy_version,
            policy_fingerprint=self.policy_fingerprint,
        )

    def _calibration_bin(
        self,
        *,
        index: int,
        evaluations: tuple[ForecastEvaluation, ...],
    ) -> ForecastCalibrationBin:
        with localcontext() as context:
            context.prec = 40
            denominator = Decimal(self.policy.calibration_bin_count)
            lower = _quantize_metric(Decimal(index) / denominator)
            upper = _quantize_metric(Decimal(index + 1) / denominator)
            if evaluations:
                count = Decimal(len(evaluations))
                probability_sum = sum(
                    (item.home_win_probability for item in evaluations),
                    Decimal("0"),
                )
                wins = sum(item.home_won for item in evaluations)
                mean_prediction = _quantize_metric(probability_sum / count)
                observed = _quantize_metric(Decimal(wins) / count)
                raw_gap = (Decimal(wins) - probability_sum) / count
                signed_gap = _quantize_metric(raw_gap)
                absolute_gap = _quantize_metric(abs(raw_gap))
                mean_brier = _quantize_metric(
                    sum(
                        (item.brier_score for item in evaluations),
                        Decimal("0"),
                    )
                    / count
                )
            else:
                wins = 0
                mean_prediction = None
                observed = None
                signed_gap = None
                absolute_gap = None
                mean_brier = None
        return ForecastCalibrationBin(
            index=index,
            lower_bound=lower,
            upper_bound=upper,
            upper_bound_inclusive=index == self.policy.calibration_bin_count - 1,
            sample_size=len(evaluations),
            home_wins=wins,
            mean_prediction=mean_prediction,
            observed_frequency=observed,
            signed_calibration_gap=signed_gap,
            absolute_calibration_gap=absolute_gap,
            mean_brier_score=mean_brier,
        )

    def _validate_policy(self, evaluations: Sequence[ForecastEvaluation]) -> None:
        if any(item.policy_fingerprint != self.policy_fingerprint for item in evaluations):
            raise ValueError("evaluation policy does not match the active engine policy")

    @staticmethod
    def _require_unique_events(evaluations: Sequence[ForecastEvaluation]) -> None:
        event_ids = [item.sports_event_id for item in evaluations]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("one selected evaluation per event is required")

    @classmethod
    def _event_index(
        cls,
        evaluations: Sequence[ForecastEvaluation],
    ) -> dict[UUID, ForecastEvaluation]:
        cls._require_unique_events(evaluations)
        return {item.sports_event_id: item for item in evaluations}
