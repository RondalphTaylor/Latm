from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

from app.domain.mlb_modeling import (
    SELECTED_MLB_FEATURES,
    MlbBinaryModelMetrics,
    MlbDatasetSplit,
    MlbFittedResearchModel,
    MlbLogisticTrainingExample,
    MlbRegularizationCandidateResult,
    MlbRegularizedLogisticPolicy,
    MlbSelectedFeatureValues,
)

_TWELVE_PLACES = Decimal("0.000000000001")


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def mlb_logistic_fitting_policy_fingerprint(policy: MlbRegularizedLogisticPolicy) -> str:
    return _hash(policy.model_dump(mode="json"))


def _decimal(value: float) -> Decimal:
    return Decimal(str(value)).quantize(_TWELVE_PLACES, rounding=ROUND_HALF_EVEN)


def _sigmoid(value: float) -> float:
    if value >= 0:
        inverse = math.exp(-value)
        return 1.0 / (1.0 + inverse)
    exponent = math.exp(value)
    return exponent / (1.0 + exponent)


def _solve(matrix: list[list[float]], values: list[float]) -> list[float]:
    size = len(values)
    augmented = [row[:] + [values[index]] for index, row in enumerate(matrix)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-14:
            raise ValueError("MLB logistic Hessian is singular")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        pivot_value = augmented[column][column]
        augmented[column] = [item / pivot_value for item in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor == 0:
                continue
            augmented[row] = [
                current - factor * pivot_item
                for current, pivot_item in zip(augmented[row], augmented[column], strict=True)
            ]
    return [augmented[row][-1] for row in range(size)]


@dataclass(frozen=True)
class _PreparedRows:
    matrix: tuple[tuple[float, ...], ...]
    outcomes: tuple[float, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]


@dataclass(frozen=True)
class _FitResult:
    coefficients: tuple[float, ...]
    converged: bool
    iterations: int


class DeterministicMlbRegularizedLogisticEngine:
    """Dependency-free L2 logistic fitter for bounded, canonical MLB research data."""

    def __init__(self, policy: MlbRegularizedLogisticPolicy | None = None) -> None:
        self.policy = policy or MlbRegularizedLogisticPolicy()
        self.policy_fingerprint = mlb_logistic_fitting_policy_fingerprint(self.policy)

    @staticmethod
    def _sort_examples(
        examples: tuple[MlbLogisticTrainingExample, ...],
    ) -> tuple[MlbLogisticTrainingExample, ...]:
        ordered = tuple(
            sorted(examples, key=lambda item: (item.scheduled_start_time, item.sports_event_id))
        )
        event_ids = [item.sports_event_id for item in ordered]
        example_ids = [item.example_id for item in ordered]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("MLB fitting data must contain one canonical example per event")
        if len(example_ids) != len(set(example_ids)):
            raise ValueError("MLB fitting example identities must be unique")
        if any(item.split is MlbDatasetSplit.PROSPECTIVE_HOLDOUT for item in ordered):
            raise ValueError("prospective holdout examples cannot enter model fitting")
        return ordered

    @staticmethod
    def _raw_values(example: MlbLogisticTrainingExample) -> tuple[float, ...]:
        values = example.feature_values.ordered_values()
        if any(value is None for value in values):
            raise ValueError("MLB fitting examples require complete feature values")
        return tuple(float(value) for value in values if value is not None)

    def _prepare_fit(self, examples: tuple[MlbLogisticTrainingExample, ...]) -> _PreparedRows:
        raw = tuple(self._raw_values(example) for example in examples)
        means = tuple(
            math.fsum(row[index] for row in raw) / len(raw)
            for index in range(len(SELECTED_MLB_FEATURES))
        )
        scales = tuple(
            math.sqrt(math.fsum((row[index] - means[index]) ** 2 for row in raw) / len(raw))
            for index in range(len(SELECTED_MLB_FEATURES))
        )
        safe_scales = tuple(scale if scale > 1e-12 else 1.0 for scale in scales)
        matrix = tuple(
            (1.0,)
            + tuple(
                (row[index] - means[index]) / safe_scales[index]
                for index in range(len(SELECTED_MLB_FEATURES))
            )
            for row in raw
        )
        return _PreparedRows(
            matrix=matrix,
            outcomes=tuple(1.0 if example.home_won else 0.0 for example in examples),
            means=means,
            scales=safe_scales,
        )

    def _transform(
        self,
        examples: tuple[MlbLogisticTrainingExample, ...],
        *,
        means: tuple[float, ...],
        scales: tuple[float, ...],
    ) -> _PreparedRows:
        raw = tuple(self._raw_values(example) for example in examples)
        return _PreparedRows(
            matrix=tuple(
                (1.0,)
                + tuple(
                    (row[index] - means[index]) / scales[index]
                    for index in range(len(SELECTED_MLB_FEATURES))
                )
                for row in raw
            ),
            outcomes=tuple(1.0 if example.home_won else 0.0 for example in examples),
            means=means,
            scales=scales,
        )

    @staticmethod
    def _loss(rows: _PreparedRows, beta: list[float], regularization: float) -> float:
        total = 0.0
        for row, outcome in zip(rows.matrix, rows.outcomes, strict=True):
            probability = min(
                max(
                    _sigmoid(math.fsum(a * b for a, b in zip(row, beta, strict=True))),
                    1e-15,
                ),
                1 - 1e-15,
            )
            total += -(outcome * math.log(probability) + (1 - outcome) * math.log(1 - probability))
        return (
            total / len(rows.matrix)
            + regularization * math.fsum(coefficient * coefficient for coefficient in beta[1:]) / 2
        )

    def _fit(self, rows: _PreparedRows, regularization: float) -> _FitResult:
        dimension = len(SELECTED_MLB_FEATURES) + 1
        beta = [0.0] * dimension
        tolerance = float(self.policy.convergence_tolerance)
        for iteration in range(1, self.policy.maximum_iterations + 1):
            probabilities = [
                _sigmoid(
                    math.fsum(
                        value * coefficient for value, coefficient in zip(row, beta, strict=True)
                    )
                )
                for row in rows.matrix
            ]
            gradient = [0.0] * dimension
            hessian = [[0.0] * dimension for _ in range(dimension)]
            for row, outcome, probability in zip(
                rows.matrix, rows.outcomes, probabilities, strict=True
            ):
                residual = probability - outcome
                weight = probability * (1.0 - probability)
                for left in range(dimension):
                    gradient[left] += residual * row[left] / len(rows.matrix)
                    for right in range(dimension):
                        hessian[left][right] += weight * row[left] * row[right] / len(rows.matrix)
            for index in range(1, dimension):
                gradient[index] += regularization * beta[index]
                hessian[index][index] += regularization
            hessian[0][0] += 1e-12
            step = _solve(hessian, gradient)
            current_loss = self._loss(rows, beta, regularization)
            multiplier = 1.0
            candidate = [
                coefficient - multiplier * adjustment
                for coefficient, adjustment in zip(beta, step, strict=True)
            ]
            while (
                self._loss(rows, candidate, regularization) > current_loss and multiplier > 1 / 1024
            ):
                multiplier /= 2
                candidate = [
                    coefficient - multiplier * adjustment
                    for coefficient, adjustment in zip(beta, step, strict=True)
                ]
            change = max(abs(left - right) for left, right in zip(candidate, beta, strict=True))
            beta = candidate
            if change <= tolerance:
                return _FitResult(tuple(beta), True, iteration)
        return _FitResult(tuple(beta), False, self.policy.maximum_iterations)

    def _metrics(
        self,
        rows: _PreparedRows,
        coefficients: tuple[float, ...],
    ) -> MlbBinaryModelMetrics:
        clip = float(self.policy.probability_clip)
        probabilities = tuple(
            min(
                max(
                    _sigmoid(
                        math.fsum(
                            value * coefficient
                            for value, coefficient in zip(row, coefficients, strict=True)
                        )
                    ),
                    clip,
                ),
                1 - clip,
            )
            for row in rows.matrix
        )
        brier = math.fsum(
            (probability - outcome) ** 2
            for probability, outcome in zip(probabilities, rows.outcomes, strict=True)
        ) / len(probabilities)
        log_loss = math.fsum(
            -(outcome * math.log(probability) + (1 - outcome) * math.log(1 - probability))
            for probability, outcome in zip(probabilities, rows.outcomes, strict=True)
        ) / len(probabilities)
        decisive = sum(probability != 0.5 for probability in probabilities)
        correct = sum(
            (probability > 0.5 and outcome == 1.0) or (probability < 0.5 and outcome == 0.0)
            for probability, outcome in zip(probabilities, rows.outcomes, strict=True)
        )
        return MlbBinaryModelMetrics(
            sample_size=len(probabilities),
            home_win_count=sum(outcome == 1.0 for outcome in rows.outcomes),
            decisive_prediction_count=decisive,
            correct_prediction_count=correct,
            mean_brier_score=_decimal(brier),
            mean_log_loss=_decimal(log_loss),
            prediction_accuracy=(_decimal(correct / decisive) if decisive else None),
        )

    def fit(self, examples: tuple[MlbLogisticTrainingExample, ...]) -> MlbFittedResearchModel:
        ordered = self._sort_examples(examples)
        train = tuple(item for item in ordered if item.split is MlbDatasetSplit.TRAIN)
        validation = tuple(item for item in ordered if item.split is MlbDatasetSplit.VALIDATION)
        test = tuple(item for item in ordered if item.split is MlbDatasetSplit.TEST)
        if not train or not validation or not test:
            raise ValueError("MLB fitting requires non-empty train, validation, and test splits")
        if len({item.home_won for item in train}) < 2:
            raise ValueError("MLB training split requires both outcomes")

        train_rows = self._prepare_fit(train)
        validation_rows = self._transform(
            validation, means=train_rows.means, scales=train_rows.scales
        )
        candidate_pairs: list[tuple[MlbRegularizationCandidateResult, _FitResult]] = []
        for strength in self.policy.regularization_candidates:
            fitted = self._fit(train_rows, float(strength))
            metrics = self._metrics(validation_rows, fitted.coefficients)
            candidate_pairs.append(
                (
                    MlbRegularizationCandidateResult(
                        regularization_strength=strength,
                        converged=fitted.converged,
                        iterations=fitted.iterations,
                        validation_metrics=metrics,
                    ),
                    fitted,
                )
            )
        converged = [item for item in candidate_pairs if item[0].converged]
        if not converged:
            raise ValueError("no MLB logistic regularization candidate converged")
        selected_result, _ = min(
            converged,
            key=lambda item: (
                item[0].validation_metrics.mean_brier_score,
                -item[0].regularization_strength,
            ),
        )

        fit_examples = tuple((*train, *validation))
        final_rows = self._prepare_fit(fit_examples)
        final_fit = self._fit(final_rows, float(selected_result.regularization_strength))
        if not final_fit.converged:
            raise ValueError("final MLB logistic refit did not converge")
        test_rows = self._transform(test, means=final_rows.means, scales=final_rows.scales)
        test_metrics = self._metrics(test_rows, final_fit.coefficients)
        training_data_fingerprint = _hash(
            {
                "ordered_examples": [item.example_fingerprint for item in ordered],
                "splits": [item.split.value for item in ordered],
            }
        )
        coefficients = {
            feature: _decimal(final_fit.coefficients[index + 1])
            for index, feature in enumerate(SELECTED_MLB_FEATURES)
        }
        means = {
            feature: _decimal(final_rows.means[index])
            for index, feature in enumerate(SELECTED_MLB_FEATURES)
        }
        scales = {
            feature: _decimal(final_rows.scales[index])
            for index, feature in enumerate(SELECTED_MLB_FEATURES)
        }
        model_payload = {
            "policy_fingerprint": self.policy_fingerprint,
            "training_data_fingerprint": training_data_fingerprint,
            "regularization": str(selected_result.regularization_strength),
            "intercept": str(_decimal(final_fit.coefficients[0])),
            "coefficients": {key.value: str(value) for key, value in coefficients.items()},
            "means": {key.value: str(value) for key, value in means.items()},
            "scales": {key.value: str(value) for key, value in scales.items()},
        }
        model_fingerprint = _hash(model_payload)
        return MlbFittedResearchModel(
            model_name=self.policy.model_name,
            effective_model_version=(
                f"{self.policy.policy_version}+cfg.{self.policy_fingerprint[:12]}"
                f".data.{training_data_fingerprint[:12]}"
            ),
            algorithm=self.policy.algorithm,
            fitting_policy_fingerprint=self.policy_fingerprint,
            training_data_fingerprint=training_data_fingerprint,
            model_fingerprint=model_fingerprint,
            selected_regularization_strength=selected_result.regularization_strength,
            standardized_intercept=_decimal(final_fit.coefficients[0]),
            standardized_coefficients=coefficients,
            feature_means=means,
            feature_scales=scales,
            train_example_count=len(train),
            validation_example_count=len(validation),
            test_example_count=len(test),
            validation_metrics=selected_result.validation_metrics,
            test_metrics=test_metrics,
            candidate_results=tuple(item[0] for item in candidate_pairs),
        )

    def predict(
        self,
        model: MlbFittedResearchModel,
        feature_values: MlbSelectedFeatureValues,
    ) -> Decimal:
        if model.fitting_policy_fingerprint != self.policy_fingerprint:
            raise ValueError("MLB fitted model uses a different fitting policy")
        values = feature_values.ordered_values()
        if any(value is None for value in values):
            raise ValueError("MLB probability preview requires complete feature values")
        score = float(model.standardized_intercept)
        for feature, raw_value in zip(SELECTED_MLB_FEATURES, values, strict=True):
            if raw_value is None:
                raise AssertionError("complete feature validation failed")
            standardized = (float(raw_value) - float(model.feature_means[feature])) / float(
                model.feature_scales[feature]
            )
            score += standardized * float(model.standardized_coefficients[feature])
        clip = float(self.policy.probability_clip)
        return _decimal(min(max(_sigmoid(score), clip), 1 - clip))
