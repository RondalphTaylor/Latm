from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import Table

from app.domain.mlb_modeling import (
    SELECTED_MLB_FEATURES,
    MlbDatasetReadinessAssessment,
    MlbDatasetReadinessInput,
    MlbDatasetSplit,
    MlbFeatureSelectionPolicy,
    MlbFittedResearchModel,
    MlbLogisticTrainingExample,
    approved_mlb_dataset_readiness_policy,
)
from app.domain.mlb_statcast import MlbStatcastObservationBasis
from app.models.mlb import (
    MlbFittedResearchModelExampleRecord,
    MlbFittedResearchModelRecord,
    MlbGameFeatureVectorRecord,
    MlbLabeledFeatureExampleRecord,
)
from app.schemas.mlb_modeling import MlbFittedResearchModelResponse
from app.services.mlb_modeling.engine import (
    DeterministicMlbDatasetReadinessEngine,
    DeterministicMlbGameFeatureEngine,
    mlb_chronological_split_policy_fingerprint,
)
from app.services.mlb_modeling.repository import (
    MlbCanonicalDatasetSelection,
    MlbGameFeatureRepository,
    mlb_fitted_research_model_example_record_id,
    mlb_fitted_research_model_record_id,
)
from app.services.mlb_modeling.service import MlbGameFeatureService

START = datetime(2026, 3, 25, tzinfo=UTC)


def _selected_values(index: int) -> dict[str, str]:
    primary = Decimal((index % 17) - 8) / Decimal("10")
    secondary = Decimal(((index * 7) % 13) - 6) / Decimal("20")
    return {
        feature.value: str(
            primary
            if feature_index == 0
            else (secondary / (feature_index + 1)).quantize(Decimal("0.000001"))
        )
        for feature_index, feature in enumerate(SELECTED_MLB_FEATURES)
    }


def _example(index: int, split: MlbDatasetSplit) -> MlbLabeledFeatureExampleRecord:
    values = _selected_values(index)
    primary = Decimal(values[SELECTED_MLB_FEATURES[0].value])
    secondary = Decimal(values[SELECTED_MLB_FEATURES[1].value])
    record = MlbLabeledFeatureExampleRecord(
        id=UUID(int=index + 1),
        sports_event_id=UUID(int=10_000 + index),
        scheduled_start_time=START + timedelta(hours=index),
        split=split.value,
        availability_basis=MlbStatcastObservationBasis.RETROSPECTIVE.value,
        home_won=primary + secondary * Decimal("0.6") > 0,
        example_fingerprint=f"{index + 1:064x}",
    )
    record.feature_vector = MlbGameFeatureVectorRecord(feature_values=values)
    return record


def _examples() -> tuple[MlbLabeledFeatureExampleRecord, ...]:
    return tuple(
        _example(
            index,
            MlbDatasetSplit.TRAIN
            if index < 500
            else MlbDatasetSplit.VALIDATION
            if index < 650
            else MlbDatasetSplit.TEST,
        )
        for index in range(800)
    )


def _readiness() -> MlbDatasetReadinessAssessment:
    policy = approved_mlb_dataset_readiness_policy()
    split_fingerprint = mlb_chronological_split_policy_fingerprint(policy.split_policy)
    return DeterministicMlbDatasetReadinessEngine().evaluate(
        MlbDatasetReadinessInput(
            split_policy_fingerprint=split_fingerprint,
            operational_split_counts={},
            retrospective_split_counts={
                MlbDatasetSplit.TRAIN: 500,
                MlbDatasetSplit.VALIDATION: 150,
                MlbDatasetSplit.TEST: 150,
            },
            policy=policy,
        )
    )


class ReadyRepository:
    def __init__(self) -> None:
        self.examples = _examples()
        self.persisted_model: MlbFittedResearchModel | None = None
        self.persisted_readiness: MlbDatasetReadinessAssessment | None = None
        self.persisted_example_count = 0

    async def canonical_dataset(self, **kwargs: object) -> MlbCanonicalDatasetSelection:
        limit = cast(int, kwargs["limit"])
        records = self.examples if limit > 1 else self.examples[:1]
        return MlbCanonicalDatasetSelection(
            split_policy_fingerprint=str(kwargs["split_policy_fingerprint"]),
            include_retrospective_research=True,
            selected_example_count=800,
            operational_example_count=0,
            retrospective_example_count=800,
            split_counts={"train": 500, "validation": 150, "test": 150},
            operational_split_counts={},
            retrospective_split_counts={"train": 500, "validation": 150, "test": 150},
            examples=records,
        )

    async def database_time(self) -> datetime:
        return START + timedelta(days=365)

    async def persist_fitted_research_model(
        self,
        *,
        model: MlbFittedResearchModel,
        readiness: MlbDatasetReadinessAssessment,
        examples: tuple[MlbLogisticTrainingExample, ...],
        fitted_at: datetime,
    ) -> tuple[MlbFittedResearchModelRecord, bool]:
        self.persisted_model = model
        self.persisted_readiness = readiness
        self.persisted_example_count = len(examples)
        links = [
            MlbFittedResearchModelExampleRecord(
                id=UUID(int=20_000 + ordinal),
                model_id=UUID(int=9_999),
                example_id=example.example_id,
                ordinal=ordinal,
                split=example.split.value,
                availability_basis=example.availability_basis.value,
                example_fingerprint=example.example_fingerprint,
                research_only=True,
            )
            for ordinal, example in enumerate(examples)
        ]
        return (
            MlbFittedResearchModelRecord(
                id=UUID(int=9_999),
                model_name=model.model_name,
                effective_model_version=model.effective_model_version,
                algorithm=model.algorithm,
                fitting_policy_fingerprint=model.fitting_policy_fingerprint,
                readiness_policy_fingerprint=readiness.policy_fingerprint,
                split_policy_fingerprint=readiness.split_policy_fingerprint,
                training_data_fingerprint=model.training_data_fingerprint,
                model_fingerprint=model.model_fingerprint,
                input_fingerprint="f" * 64,
                selected_features=[feature.value for feature in SELECTED_MLB_FEATURES],
                selected_regularization_strength=model.selected_regularization_strength,
                standardized_intercept=model.standardized_intercept,
                standardized_coefficients={
                    key.value: str(value) for key, value in model.standardized_coefficients.items()
                },
                feature_means={key.value: str(value) for key, value in model.feature_means.items()},
                feature_scales={
                    key.value: str(value) for key, value in model.feature_scales.items()
                },
                train_example_count=model.train_example_count,
                validation_example_count=model.validation_example_count,
                test_example_count=model.test_example_count,
                validation_metrics=model.validation_metrics.model_dump(mode="json"),
                test_metrics=model.test_metrics.model_dump(mode="json"),
                candidate_results=[
                    item.model_dump(mode="json") for item in model.candidate_results
                ],
                readiness_snapshot=readiness.model_dump(mode="json"),
                source_manifest=[{} for _ in examples],
                fitted_at=fitted_at,
                research_only=True,
                operational_probability_enabled=False,
                automatic_trading_enabled=False,
                examples=links,
            ),
            True,
        )


def test_fitted_model_and_lineage_ids_are_stable() -> None:
    model_id = mlb_fitted_research_model_record_id("a" * 64)
    assert model_id == mlb_fitted_research_model_record_id("a" * 64)
    assert model_id != mlb_fitted_research_model_record_id("b" * 64)
    assert mlb_fitted_research_model_example_record_id(
        model_id, UUID(int=1)
    ) == mlb_fitted_research_model_example_record_id(model_id, UUID(int=1))


def test_fitted_model_tables_enforce_readiness_lineage_and_safety() -> None:
    model_table = cast(Table, MlbFittedResearchModelRecord.__table__)
    lineage_table = cast(Table, MlbFittedResearchModelExampleRecord.__table__)
    model_constraints = {item.name for item in model_table.constraints}
    lineage_constraints = {item.name for item in lineage_table.constraints}
    assert {
        "ck_mlb_fitted_research_models_readiness",
        "ck_mlb_fitted_research_models_manifest_count",
        "ck_mlb_fitted_research_models_safety",
        "uq_mlb_fitted_research_models_input",
    } <= model_constraints
    assert {
        "ck_mlb_fitted_model_examples_split",
        "ck_mlb_fitted_model_examples_safety",
        "uq_mlb_fitted_model_examples_example",
        "uq_mlb_fitted_model_examples_ordinal",
    } <= lineage_constraints


def test_ready_service_fits_persists_and_serializes_one_research_artifact() -> None:
    repository = ReadyRepository()
    service = MlbGameFeatureService(
        repository=cast(MlbGameFeatureRepository, repository),
        engine=DeterministicMlbGameFeatureEngine(),
        policy=MlbFeatureSelectionPolicy(),
    )

    result = asyncio.run(service.fit_and_persist_research_model())
    response = MlbFittedResearchModelResponse.from_record(result.model)

    assert result.created is True
    assert repository.persisted_readiness is not None
    assert repository.persisted_readiness.exploratory_fit_data_ready is True
    assert repository.persisted_example_count == 800
    assert repository.persisted_model is not None
    assert repository.persisted_model.train_example_count == 500
    assert repository.persisted_model.validation_example_count == 150
    assert repository.persisted_model.test_example_count == 150
    assert response.id == UUID(int=9_999)
    assert len(response.example_ids) == 800
    assert response.operational_probability_enabled is False
    assert response.automatic_trading_enabled is False
