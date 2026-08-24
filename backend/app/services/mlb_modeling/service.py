from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.domain.mlb_modeling import (
    MlbChronologicalDatasetPolicy,
    MlbDatasetReadinessAssessment,
    MlbDatasetReadinessInput,
    MlbDatasetSplit,
    MlbFeatureSelectionPolicy,
    MlbFittedResearchModel,
    MlbGameFeatureVector,
    MlbLogisticTrainingExample,
    MlbMatchupFeatureCoverage,
    MlbMatchupSourceMetrics,
    MlbModelFeatureInput,
    MlbOfficialOutcomeInput,
    MlbSelectedFeatureName,
    MlbSelectedFeatureValues,
    approved_mlb_dataset_readiness_policy,
)
from app.domain.mlb_statcast import MlbStatcastObservationBasis, MlbStatcastPlayerFeatures
from app.models.mlb import (
    MlbFittedResearchModelRecord,
    MlbGameFeatureVectorRecord,
    MlbLabeledFeatureExampleRecord,
)
from app.services.mlb_modeling.engine import (
    DeterministicMlbDatasetContract,
    DeterministicMlbDatasetReadinessEngine,
    DeterministicMlbGameFeatureEngine,
    mlb_chronological_split_policy_fingerprint,
)
from app.services.mlb_modeling.fitting import DeterministicMlbRegularizedLogisticEngine
from app.services.mlb_modeling.repository import (
    MlbCanonicalDatasetSelection,
    MlbDatasetInventory,
    MlbGameFeatureRepository,
)


@dataclass(frozen=True)
class MlbGameFeatureBuildResult:
    created: bool
    vector: MlbGameFeatureVectorRecord


@dataclass(frozen=True)
class MlbDatasetLabelResult:
    created: bool
    example: MlbLabeledFeatureExampleRecord


@dataclass(frozen=True)
class MlbResearchModelFitResult:
    created: bool
    model: MlbFittedResearchModelRecord


class MlbModelFittingBlockedError(RuntimeError):
    """Approved sample gates are not ready for research fitting."""

    def __init__(self, assessment: MlbDatasetReadinessAssessment) -> None:
        super().__init__("MLB exploratory fitting data thresholds are not met")
        self.assessment = assessment


class MlbGameFeatureService:
    """Derive one vector from an exact persisted Statcast source, with no I/O provider."""

    def __init__(
        self,
        *,
        repository: MlbGameFeatureRepository,
        engine: DeterministicMlbGameFeatureEngine,
        policy: MlbFeatureSelectionPolicy,
        fitting_engine: DeterministicMlbRegularizedLogisticEngine | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._engine = engine
        self._policy = policy
        self._fitting_engine = fitting_engine or DeterministicMlbRegularizedLogisticEngine()
        self._clock = clock

    async def build(self, statcast_snapshot_id: UUID) -> MlbGameFeatureBuildResult:
        source = await self._repository.get_statcast_snapshot(statcast_snapshot_id)
        if source is None:
            raise LookupError("MLB Statcast snapshot not found")
        event = source.sports_event
        vector = self._engine.evaluate(
            MlbModelFeatureInput(
                sports_event_id=source.sports_event_id,
                lineup_snapshot_id=source.lineup_snapshot_id,
                statcast_snapshot_id=source.id,
                provider_event_id=source.provider_event_id,
                target_event_date=source.target_event_date,
                scheduled_start_time=source.scheduled_start_time,
                home_team_id=event.home_team_id,
                away_team_id=event.away_team_id,
                source_retrieved_at=source.source_retrieved_at,
                source_observation_basis=MlbStatcastObservationBasis(source.observation_basis),
                source_operational_pregame_eligible=source.operational_pregame_eligible,
                statcast_policy_fingerprint=source.policy_fingerprint,
                statcast_source_fingerprint=source.source_fingerprint,
                statcast_input_fingerprint=source.input_fingerprint,
                home_starting_pitcher=MlbStatcastPlayerFeatures.model_validate(
                    source.home_starting_pitcher
                ),
                away_starting_pitcher=MlbStatcastPlayerFeatures.model_validate(
                    source.away_starting_pitcher
                ),
                home_batters=tuple(
                    MlbStatcastPlayerFeatures.model_validate(item) for item in source.home_batters
                ),
                away_batters=tuple(
                    MlbStatcastPlayerFeatures.model_validate(item) for item in source.away_batters
                ),
                built_at=self._clock(),
                policy=self._policy,
            )
        )
        record, created = await self._repository.persist_vector(vector)
        return MlbGameFeatureBuildResult(created=created, vector=record)

    @staticmethod
    def _vector_domain(record: MlbGameFeatureVectorRecord) -> MlbGameFeatureVector:
        return MlbGameFeatureVector(
            sports_event_id=record.sports_event_id,
            lineup_snapshot_id=record.lineup_snapshot_id,
            statcast_snapshot_id=record.statcast_snapshot_id,
            provider_event_id=record.provider_event_id,
            target_event_date=record.target_event_date,
            scheduled_start_time=record.scheduled_start_time,
            home_team_id=record.home_team_id,
            away_team_id=record.away_team_id,
            source_retrieved_at=record.source_retrieved_at,
            source_observation_basis=MlbStatcastObservationBasis(record.source_observation_basis),
            built_at=record.built_at,
            feature_availability_basis=MlbStatcastObservationBasis(
                record.feature_availability_basis
            ),
            policy_name=record.policy_name,
            policy_version=record.policy_version,
            model_candidate_name=record.model_candidate_name,
            policy_fingerprint=record.policy_fingerprint,
            source_metrics=MlbMatchupSourceMetrics.model_validate(record.source_metrics),
            coverage=MlbMatchupFeatureCoverage.model_validate(record.coverage),
            feature_values=MlbSelectedFeatureValues.model_validate(record.feature_values),
            missing_features=tuple(
                MlbSelectedFeatureName(item) for item in record.missing_features
            ),
            complete_feature_vector=record.complete_feature_vector,
            operational_model_input_eligible=record.operational_model_input_eligible,
            research_only=record.research_only,
            probability_generated=record.probability_generated,
            automatic_trading_eligible=record.automatic_trading_eligible,
            source_fingerprint=record.source_fingerprint,
            input_fingerprint=record.input_fingerprint,
        )

    async def label(
        self,
        *,
        vector_id: UUID,
        split_policy: MlbChronologicalDatasetPolicy,
    ) -> MlbDatasetLabelResult:
        """Freeze one official final result against one exact candidate vector."""
        candidate = await self._repository.get_label_candidate(vector_id)
        if candidate is None:
            raise LookupError("MLB game feature vector not found")
        event = candidate.event
        vector_record = candidate.vector
        if event.provider_name != "mlb" or event.league != "mlb":
            raise ValueError("dataset labels require an official MLB event")
        if event.postponed:
            raise ValueError("postponed MLB events cannot be labeled")
        if (
            event.provider_event_id != vector_record.provider_event_id
            or event.event_date != vector_record.target_event_date
            or event.home_team_id != vector_record.home_team_id
            or event.away_team_id != vector_record.away_team_id
            or event.scheduled_start_time != vector_record.scheduled_start_time
        ):
            raise ValueError("official MLB event semantics changed after feature selection")
        labeled_at = await self._repository.database_time()
        example = DeterministicMlbDatasetContract().label(
            self._vector_domain(candidate.vector),
            MlbOfficialOutcomeInput(
                sports_event_id=event.id,
                scheduled_start_time=event.scheduled_start_time,
                status=event.status,
                home_score=event.home_score,
                away_score=event.away_score,
                source_last_seen_at=event.last_seen_at,
            ),
            split_policy,
        )
        record, created = await self._repository.persist_labeled_example(
            candidate=candidate,
            example=example,
            policy=split_policy,
            labeled_at=labeled_at,
        )
        return MlbDatasetLabelResult(created=created, example=record)

    async def inventory(self, split_policy_fingerprint: str) -> MlbDatasetInventory:
        return await self._repository.dataset_inventory(split_policy_fingerprint)

    async def canonical_dataset(
        self,
        *,
        split_policy_fingerprint: str,
        include_retrospective_research: bool,
        limit: int,
        offset: int,
    ) -> MlbCanonicalDatasetSelection:
        return await self._repository.canonical_dataset(
            split_policy_fingerprint=split_policy_fingerprint,
            include_retrospective_research=include_retrospective_research,
            limit=limit,
            offset=offset,
        )

    async def approved_dataset_readiness(self) -> MlbDatasetReadinessAssessment:
        policy = approved_mlb_dataset_readiness_policy()
        split_fingerprint = mlb_chronological_split_policy_fingerprint(policy.split_policy)
        selection = await self._repository.canonical_dataset(
            split_policy_fingerprint=split_fingerprint,
            include_retrospective_research=True,
            limit=1,
            offset=0,
        )
        return DeterministicMlbDatasetReadinessEngine().evaluate(
            MlbDatasetReadinessInput(
                split_policy_fingerprint=split_fingerprint,
                operational_split_counts={
                    MlbDatasetSplit(split): count
                    for split, count in selection.operational_split_counts.items()
                },
                retrospective_split_counts={
                    MlbDatasetSplit(split): count
                    for split, count in selection.retrospective_split_counts.items()
                },
                policy=policy,
            )
        )

    async def fit_research_preview(self) -> MlbFittedResearchModel:
        """Fit an unpersisted research artifact only after all exploratory data gates pass."""
        _, examples = await self._fitting_inputs()
        return self._fitting_engine.fit(examples)

    async def fit_and_persist_research_model(self) -> MlbResearchModelFitResult:
        """Persist one immutable research artifact; probability publication remains disabled."""
        assessment, examples = await self._fitting_inputs()
        model = self._fitting_engine.fit(examples)
        fitted_at = await self._repository.database_time()
        record, created = await self._repository.persist_fitted_research_model(
            model=model,
            readiness=assessment,
            examples=examples,
            fitted_at=fitted_at,
        )
        return MlbResearchModelFitResult(created=created, model=record)

    async def _fitting_inputs(
        self,
    ) -> tuple[MlbDatasetReadinessAssessment, tuple[MlbLogisticTrainingExample, ...]]:
        assessment = await self.approved_dataset_readiness()
        if not assessment.exploratory_fit_data_ready:
            raise MlbModelFittingBlockedError(assessment)
        selection = await self._repository.canonical_dataset(
            split_policy_fingerprint=assessment.split_policy_fingerprint,
            include_retrospective_research=True,
            limit=10_000,
            offset=0,
        )
        examples = tuple(
            MlbLogisticTrainingExample(
                example_id=record.id,
                sports_event_id=record.sports_event_id,
                scheduled_start_time=record.scheduled_start_time,
                split=MlbDatasetSplit(record.split),
                availability_basis=MlbStatcastObservationBasis(record.availability_basis),
                feature_values=MlbSelectedFeatureValues.model_validate(
                    record.feature_vector.feature_values
                ),
                home_won=record.home_won,
                example_fingerprint=record.example_fingerprint,
            )
            for record in selection.examples
            if record.split != MlbDatasetSplit.PROSPECTIVE_HOLDOUT.value
        )
        if len(examples) != (
            selection.split_counts.get(MlbDatasetSplit.TRAIN.value, 0)
            + selection.split_counts.get(MlbDatasetSplit.VALIDATION.value, 0)
            + selection.split_counts.get(MlbDatasetSplit.TEST.value, 0)
        ):
            raise ValueError("canonical MLB fitting selection is incomplete")
        return assessment, examples
