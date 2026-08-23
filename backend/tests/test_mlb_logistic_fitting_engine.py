from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from app.domain.mlb_modeling import (
    SELECTED_MLB_FEATURES,
    MlbDatasetSplit,
    MlbLogisticTrainingExample,
    MlbSelectedFeatureValues,
)
from app.domain.mlb_statcast import MlbStatcastObservationBasis
from app.services.mlb_modeling.fitting import (
    DeterministicMlbRegularizedLogisticEngine,
)

START = datetime(2026, 4, 1, tzinfo=UTC)


def _example(index: int, split: MlbDatasetSplit) -> MlbLogisticTrainingExample:
    primary = Decimal((index % 17) - 8) / Decimal("10")
    secondary = Decimal(((index * 7) % 13) - 6) / Decimal("20")
    home_won = primary + secondary * Decimal("0.6") > Decimal("0")
    values = {
        feature.value: (
            primary
            if feature_index == 0
            else (secondary / (feature_index + 1)).quantize(Decimal("0.000001"))
        )
        for feature_index, feature in enumerate(SELECTED_MLB_FEATURES)
    }
    return MlbLogisticTrainingExample(
        example_id=UUID(int=index + 1),
        sports_event_id=UUID(int=10_000 + index),
        scheduled_start_time=START + timedelta(hours=index),
        split=split,
        availability_basis=MlbStatcastObservationBasis.RETROSPECTIVE,
        feature_values=MlbSelectedFeatureValues.model_validate(values),
        home_won=home_won,
        example_fingerprint=f"{index + 1:064x}",
    )


def _dataset() -> tuple[MlbLogisticTrainingExample, ...]:
    return tuple(
        _example(
            index,
            (
                MlbDatasetSplit.TRAIN
                if index < 120
                else MlbDatasetSplit.VALIDATION
                if index < 160
                else MlbDatasetSplit.TEST
            ),
        )
        for index in range(200)
    )


def test_regularized_logistic_fit_is_deterministic_and_out_of_sample() -> None:
    engine = DeterministicMlbRegularizedLogisticEngine()
    examples = _dataset()

    first = engine.fit(examples)
    replay = engine.fit(tuple(reversed(examples)))

    assert first == replay
    assert first.train_example_count == 120
    assert first.validation_example_count == 40
    assert first.test_example_count == 40
    assert first.test_metrics.mean_brier_score < Decimal("0.10")
    assert first.test_metrics.prediction_accuracy is not None
    assert first.test_metrics.prediction_accuracy > Decimal("0.90")
    assert first.standardized_coefficients[SELECTED_MLB_FEATURES[0]] > 0
    assert all(item.converged for item in first.candidate_results)
    assert first.operational_probability_enabled is False
    assert first.automatic_trading_enabled is False


def test_prediction_preview_uses_frozen_standardization_and_is_bounded() -> None:
    engine = DeterministicMlbRegularizedLogisticEngine()
    model = engine.fit(_dataset())

    high = engine.predict(model, _example(8, MlbDatasetSplit.TEST).feature_values)
    low = engine.predict(model, _example(0, MlbDatasetSplit.TEST).feature_values)

    assert Decimal("0") < low < high < Decimal("1")


def test_prospective_holdout_is_rejected_from_fitting() -> None:
    engine = DeterministicMlbRegularizedLogisticEngine()
    examples = (*_dataset(), _example(500, MlbDatasetSplit.PROSPECTIVE_HOLDOUT))

    with pytest.raises(ValueError, match="prospective holdout"):
        engine.fit(examples)
