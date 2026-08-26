from __future__ import annotations

from dataclasses import dataclass

from app.domain.mlb_dataset_quality import (
    MlbDatasetQualityExample,
    MlbDatasetQualityInput,
    MlbDatasetQualityPolicy,
)
from app.domain.mlb_modeling import (
    MlbDatasetReadinessInput,
    MlbDatasetSplit,
    MlbFeatureSelectionPolicy,
    MlbMatchupFeatureCoverage,
    MlbSelectedFeatureValues,
    approved_mlb_dataset_readiness_policy,
)
from app.domain.mlb_statcast import MlbStatcastObservationBasis
from app.models.mlb import MlbDatasetQualityAuditRecord, MlbLabeledFeatureExampleRecord
from app.services.mlb_modeling.engine import (
    DeterministicMlbDatasetReadinessEngine,
    mlb_chronological_split_policy_fingerprint,
    mlb_feature_selection_policy_fingerprint,
)
from app.services.mlb_modeling.quality import DeterministicMlbDatasetQualityEngine
from app.services.mlb_modeling.quality_repository import MlbDatasetQualityRepository
from app.services.mlb_modeling.repository import MlbGameFeatureRepository


@dataclass(frozen=True)
class MlbDatasetQualityAuditResult:
    created: bool
    audit: MlbDatasetQualityAuditRecord


class MlbDatasetQualityService:
    """Materialize an immutable quality report over the approved canonical dataset."""

    def __init__(
        self,
        *,
        feature_repository: MlbGameFeatureRepository,
        quality_repository: MlbDatasetQualityRepository,
        engine: DeterministicMlbDatasetQualityEngine | None = None,
        policy: MlbDatasetQualityPolicy | None = None,
    ) -> None:
        self._feature_repository = feature_repository
        self._quality_repository = quality_repository
        self._engine = engine or DeterministicMlbDatasetQualityEngine()
        self._policy = policy or MlbDatasetQualityPolicy()

    @staticmethod
    def _quality_example(record: MlbLabeledFeatureExampleRecord) -> MlbDatasetQualityExample:
        vector = record.feature_vector
        return MlbDatasetQualityExample(
            example_id=record.id,
            game_feature_vector_id=record.game_feature_vector_id,
            sports_event_id=record.sports_event_id,
            scheduled_start_time=record.scheduled_start_time,
            home_team_id=vector.home_team_id,
            away_team_id=vector.away_team_id,
            split=MlbDatasetSplit(record.split),
            availability_basis=MlbStatcastObservationBasis(record.availability_basis),
            home_won=record.home_won,
            feature_values=MlbSelectedFeatureValues.model_validate(vector.feature_values),
            coverage=MlbMatchupFeatureCoverage.model_validate(vector.coverage),
            feature_policy_fingerprint=record.feature_policy_fingerprint,
            feature_vector_input_fingerprint=record.feature_vector_input_fingerprint,
            outcome_fingerprint=record.outcome_fingerprint,
            example_fingerprint=record.example_fingerprint,
            source_retrieved_at=vector.source_retrieved_at,
            vector_built_at=vector.built_at,
            outcome_source_last_seen_at=record.outcome_source_last_seen_at,
            labeled_at=record.labeled_at,
            complete_feature_vector=vector.complete_feature_vector,
            operational_model_input_eligible=vector.operational_model_input_eligible,
            vector_research_only=vector.research_only,
            vector_probability_generated=vector.probability_generated,
            vector_automatic_trading_eligible=vector.automatic_trading_eligible,
            research_only=record.research_only,
            probability_generated=record.probability_generated,
            automatic_trading_eligible=record.automatic_trading_eligible,
        )

    async def run(self) -> MlbDatasetQualityAuditResult:
        readiness_policy = approved_mlb_dataset_readiness_policy()
        split_policy_fingerprint = mlb_chronological_split_policy_fingerprint(
            readiness_policy.split_policy
        )
        selection = await self._feature_repository.canonical_dataset(
            split_policy_fingerprint=split_policy_fingerprint,
            include_retrospective_research=True,
            limit=10_000,
            offset=0,
        )
        if len(selection.examples) != selection.selected_example_count:
            raise ValueError("canonical MLB quality selection exceeded its bounded audit read")
        examples = tuple(self._quality_example(record) for record in selection.examples)
        report = self._engine.evaluate(
            MlbDatasetQualityInput(
                split_policy_fingerprint=split_policy_fingerprint,
                split_policy=readiness_policy.split_policy,
                feature_policy_fingerprint=mlb_feature_selection_policy_fingerprint(
                    MlbFeatureSelectionPolicy()
                ),
                examples=examples,
                policy=self._policy,
            )
        )
        readiness = DeterministicMlbDatasetReadinessEngine().evaluate(
            MlbDatasetReadinessInput(
                split_policy_fingerprint=split_policy_fingerprint,
                operational_split_counts={
                    MlbDatasetSplit(split): count
                    for split, count in selection.operational_split_counts.items()
                },
                retrospective_split_counts={
                    MlbDatasetSplit(split): count
                    for split, count in selection.retrospective_split_counts.items()
                },
                policy=readiness_policy,
            )
        )
        evaluated_at = await self._quality_repository.database_time()
        record, created = await self._quality_repository.persist_audit(
            report=report,
            readiness=readiness,
            examples=examples,
            evaluated_at=evaluated_at,
        )
        return MlbDatasetQualityAuditResult(created=created, audit=record)
