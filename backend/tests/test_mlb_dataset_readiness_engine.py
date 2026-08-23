from __future__ import annotations

from app.domain.mlb_modeling import (
    MlbDatasetReadinessAssessment,
    MlbDatasetReadinessInput,
    MlbDatasetSplit,
    approved_mlb_dataset_readiness_policy,
)
from app.services.mlb_modeling.engine import (
    DeterministicMlbDatasetReadinessEngine,
    mlb_chronological_split_policy_fingerprint,
    mlb_dataset_readiness_policy_fingerprint,
)


def _evaluate(
    *,
    operational: dict[MlbDatasetSplit, int],
    retrospective: dict[MlbDatasetSplit, int],
) -> MlbDatasetReadinessAssessment:
    policy = approved_mlb_dataset_readiness_policy()
    return DeterministicMlbDatasetReadinessEngine().evaluate(
        MlbDatasetReadinessInput(
            split_policy_fingerprint=mlb_chronological_split_policy_fingerprint(
                policy.split_policy
            ),
            operational_split_counts=operational,
            retrospective_split_counts=retrospective,
            policy=policy,
        )
    )


def test_approved_policy_is_stable_and_exact() -> None:
    policy = approved_mlb_dataset_readiness_policy()

    assert policy.minimum_train_examples == 500
    assert policy.minimum_validation_examples == 150
    assert policy.minimum_test_examples == 150
    assert policy.minimum_prospective_holdout_examples == 200
    assert policy.split_policy.validation_start.isoformat() == "2026-06-01T00:00:00+00:00"
    assert policy.split_policy.test_start.isoformat() == "2026-07-01T00:00:00+00:00"
    assert policy.split_policy.prospective_holdout_start.isoformat() == "2026-08-23T00:00:00+00:00"
    assert len(mlb_dataset_readiness_policy_fingerprint(policy)) == 64


def test_retrospective_examples_count_only_for_exploratory_splits() -> None:
    result = _evaluate(
        operational={MlbDatasetSplit.PROSPECTIVE_HOLDOUT: 199},
        retrospective={
            MlbDatasetSplit.TRAIN: 500,
            MlbDatasetSplit.VALIDATION: 150,
            MlbDatasetSplit.TEST: 150,
            MlbDatasetSplit.PROSPECTIVE_HOLDOUT: 999,
        },
    )

    assert result.exploratory_fit_data_ready is True
    assert result.prospective_evaluation_data_ready is False
    assert result.eligible_split_counts[MlbDatasetSplit.PROSPECTIVE_HOLDOUT] == 199
    assert result.shortfall_by_split[MlbDatasetSplit.PROSPECTIVE_HOLDOUT] == 1
    assert result.blockers == ("prospective_holdout_shortfall:1",)


def test_exact_operational_holdout_threshold_completes_data_readiness() -> None:
    result = _evaluate(
        operational={MlbDatasetSplit.PROSPECTIVE_HOLDOUT: 200},
        retrospective={
            MlbDatasetSplit.TRAIN: 500,
            MlbDatasetSplit.VALIDATION: 150,
            MlbDatasetSplit.TEST: 150,
        },
    )

    assert result.exploratory_fit_data_ready is True
    assert result.prospective_evaluation_data_ready is True
    assert result.blockers == ()
    assert result.probability_generation_enabled is False
    assert result.automatic_trading_enabled is False
