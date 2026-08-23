from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.mlb_modeling import (
    SELECTED_MLB_FEATURES,
    MlbDatasetReadinessAssessment,
    MlbDatasetSplit,
    MlbMatchupFeatureCoverage,
    MlbMatchupSourceMetrics,
    MlbSelectedFeatureName,
    MlbSelectedFeatureValues,
    approved_mlb_dataset_readiness_policy,
)
from app.models.mlb import MlbGameFeatureVectorRecord, MlbLabeledFeatureExampleRecord
from app.services.mlb_modeling.repository import (
    MlbCanonicalDatasetSelection,
    MlbDatasetInventory,
)


class MlbGameFeatureVectorResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    sports_event_id: UUID
    lineup_snapshot_id: UUID
    statcast_snapshot_id: UUID
    provider_event_id: str
    target_event_date: date
    scheduled_start_time: datetime
    home_team_id: UUID
    away_team_id: UUID
    source_retrieved_at: datetime
    source_observation_basis: str
    built_at: datetime
    feature_availability_basis: str
    policy_name: str
    policy_version: str
    model_candidate_name: str
    policy_fingerprint: str
    source_metrics: MlbMatchupSourceMetrics
    coverage: MlbMatchupFeatureCoverage
    feature_values: MlbSelectedFeatureValues
    missing_features: tuple[MlbSelectedFeatureName, ...]
    complete_feature_vector: bool
    operational_model_input_eligible: bool
    research_only: Literal[True]
    probability_generated: Literal[False]
    automatic_trading_eligible: Literal[False]
    source_fingerprint: str
    input_fingerprint: str

    @classmethod
    def from_record(cls, record: MlbGameFeatureVectorRecord) -> MlbGameFeatureVectorResponse:
        return cls(
            id=record.id,
            sports_event_id=record.sports_event_id,
            lineup_snapshot_id=record.lineup_snapshot_id,
            statcast_snapshot_id=record.statcast_snapshot_id,
            provider_event_id=record.provider_event_id,
            target_event_date=record.target_event_date,
            scheduled_start_time=record.scheduled_start_time,
            home_team_id=record.home_team_id,
            away_team_id=record.away_team_id,
            source_retrieved_at=record.source_retrieved_at,
            source_observation_basis=record.source_observation_basis,
            built_at=record.built_at,
            feature_availability_basis=record.feature_availability_basis,
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


class MlbGameFeatureBuildResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    created: bool
    vector: MlbGameFeatureVectorResponse


class MlbModelDesignResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidate_name: Literal["mlb_pregame_regularized_logistic"]
    target: Literal["official_final_home_win"]
    selected_features: tuple[MlbSelectedFeatureName, ...]
    feature_orientation: Literal["positive_favors_home"]
    pooling_policy: Literal["sample_weighted"]
    missing_value_policy: Literal["no_imputation"]
    validation_strategy: Literal["chronological_train_validation_test_prospective_holdout"]
    random_shuffle: Literal[False]
    fitted_model_available: Literal[False]
    probability_generation_enabled: Literal[False]
    automatic_trading_enabled: Literal[False]

    @classmethod
    def current(cls) -> MlbModelDesignResponse:
        return cls(
            candidate_name="mlb_pregame_regularized_logistic",
            target="official_final_home_win",
            selected_features=SELECTED_MLB_FEATURES,
            feature_orientation="positive_favors_home",
            pooling_policy="sample_weighted",
            missing_value_policy="no_imputation",
            validation_strategy="chronological_train_validation_test_prospective_holdout",
            random_shuffle=False,
            fitted_model_available=False,
            probability_generation_enabled=False,
            automatic_trading_enabled=False,
        )


class MlbLabeledFeatureExampleResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    game_feature_vector_id: UUID
    sports_event_id: UUID
    feature_vector_input_fingerprint: str
    feature_policy_fingerprint: str
    availability_basis: str
    scheduled_start_time: datetime
    outcome_status: Literal["final"]
    home_score: int
    away_score: int
    home_won: bool
    outcome_source_last_seen_at: datetime
    outcome_source_snapshot: dict[str, Any]
    split: MlbDatasetSplit
    split_policy_name: str
    split_policy_version: str
    validation_start: datetime
    test_start: datetime
    prospective_holdout_start: datetime
    split_policy_fingerprint: str
    outcome_fingerprint: str
    example_fingerprint: str
    labeled_at: datetime
    research_only: Literal[True]
    probability_generated: Literal[False]
    automatic_trading_eligible: Literal[False]

    @classmethod
    def from_record(
        cls, record: MlbLabeledFeatureExampleRecord
    ) -> MlbLabeledFeatureExampleResponse:
        return cls(
            id=record.id,
            game_feature_vector_id=record.game_feature_vector_id,
            sports_event_id=record.sports_event_id,
            feature_vector_input_fingerprint=record.feature_vector_input_fingerprint,
            feature_policy_fingerprint=record.feature_policy_fingerprint,
            availability_basis=record.availability_basis,
            scheduled_start_time=record.scheduled_start_time,
            outcome_status=record.outcome_status,
            home_score=record.home_score,
            away_score=record.away_score,
            home_won=record.home_won,
            outcome_source_last_seen_at=record.outcome_source_last_seen_at,
            outcome_source_snapshot=record.outcome_source_snapshot,
            split=MlbDatasetSplit(record.split),
            split_policy_name=record.split_policy_name,
            split_policy_version=record.split_policy_version,
            validation_start=record.validation_start,
            test_start=record.test_start,
            prospective_holdout_start=record.prospective_holdout_start,
            split_policy_fingerprint=record.split_policy_fingerprint,
            outcome_fingerprint=record.outcome_fingerprint,
            example_fingerprint=record.example_fingerprint,
            labeled_at=record.labeled_at,
            research_only=record.research_only,
            probability_generated=record.probability_generated,
            automatic_trading_eligible=record.automatic_trading_eligible,
        )


class MlbDatasetLabelResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    created: bool
    example: MlbLabeledFeatureExampleResponse


class MlbDatasetInventoryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    split_policy_fingerprint: str
    example_count: int
    unique_event_count: int
    duplicate_event_example_count: int
    operational_example_count: int
    retrospective_example_count: int
    split_counts: dict[str, int]
    operational_split_counts: dict[str, int]
    retrospective_split_counts: dict[str, int]
    canonical_training_dataset_available: Literal[False]
    model_fitting_enabled: Literal[False]
    probability_generation_enabled: Literal[False]
    automatic_trading_enabled: Literal[False]
    warnings: tuple[str, ...]

    @classmethod
    def from_inventory(cls, inventory: MlbDatasetInventory) -> MlbDatasetInventoryResponse:
        warnings = [
            "inventory counts immutable examples before canonical one-vector-per-event selection",
            "use /mlb-canonical-dataset for the deterministic modeling view",
            "no minimum sample threshold or fitted MLB model has been approved",
        ]
        if inventory.retrospective_example_count:
            warnings.append(
                "retrospective examples are reported separately and cannot establish live pregame performance"
            )
        return cls(
            split_policy_fingerprint=inventory.split_policy_fingerprint,
            example_count=inventory.example_count,
            unique_event_count=inventory.unique_event_count,
            duplicate_event_example_count=(inventory.example_count - inventory.unique_event_count),
            operational_example_count=inventory.operational_example_count,
            retrospective_example_count=inventory.retrospective_example_count,
            split_counts=inventory.split_counts,
            operational_split_counts=inventory.operational_split_counts,
            retrospective_split_counts=inventory.retrospective_split_counts,
            canonical_training_dataset_available=False,
            model_fitting_enabled=False,
            probability_generation_enabled=False,
            automatic_trading_enabled=False,
            warnings=tuple(warnings),
        )


class MlbCanonicalDatasetResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    split_policy_fingerprint: str
    include_retrospective_research: bool
    selected_example_count: int
    returned_example_count: int
    operational_example_count: int
    retrospective_example_count: int
    split_counts: dict[str, int]
    operational_split_counts: dict[str, int]
    retrospective_split_counts: dict[str, int]
    examples: tuple[MlbLabeledFeatureExampleResponse, ...]
    canonical_selection_policy: Literal[
        "one_per_event_prefer_operational_then_latest_vector_and_outcome"
    ]
    minimum_sample_threshold_approved: Literal[True]
    model_fitting_enabled: Literal[False]
    probability_generation_enabled: Literal[False]
    automatic_trading_enabled: Literal[False]
    warnings: tuple[str, ...]

    @classmethod
    def from_selection(cls, selection: MlbCanonicalDatasetSelection) -> MlbCanonicalDatasetResponse:
        warnings = [
            "approved V1 thresholds are evaluated by /mlb-approved-dataset-readiness",
            "no fitted MLB model or probability output exists",
        ]
        if selection.include_retrospective_research:
            warnings.append(
                "retrospective fallback examples are research-only and cannot establish live performance"
            )
        return cls(
            split_policy_fingerprint=selection.split_policy_fingerprint,
            include_retrospective_research=selection.include_retrospective_research,
            selected_example_count=selection.selected_example_count,
            returned_example_count=len(selection.examples),
            operational_example_count=selection.operational_example_count,
            retrospective_example_count=selection.retrospective_example_count,
            split_counts=selection.split_counts,
            operational_split_counts=selection.operational_split_counts,
            retrospective_split_counts=selection.retrospective_split_counts,
            examples=tuple(
                MlbLabeledFeatureExampleResponse.from_record(record)
                for record in selection.examples
            ),
            canonical_selection_policy=(
                "one_per_event_prefer_operational_then_latest_vector_and_outcome"
            ),
            minimum_sample_threshold_approved=True,
            model_fitting_enabled=False,
            probability_generation_enabled=False,
            automatic_trading_enabled=False,
            warnings=tuple(warnings),
        )


class MlbApprovedDatasetReadinessResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy_name: str
    policy_version: str
    policy_fingerprint: str
    split_policy_fingerprint: str
    validation_start: datetime
    test_start: datetime
    prospective_holdout_start: datetime
    minimum_split_counts: dict[MlbDatasetSplit, int]
    eligible_split_counts: dict[MlbDatasetSplit, int]
    shortfall_by_split: dict[MlbDatasetSplit, int]
    exploratory_fit_data_ready: bool
    prospective_evaluation_data_ready: bool
    retrospective_allowed_for_exploratory_splits: Literal[True]
    prospective_holdout_requires_operational_pregame: Literal[True]
    model_fitting_enabled: Literal[False]
    probability_generation_enabled: Literal[False]
    automatic_trading_enabled: Literal[False]
    blockers: tuple[str, ...]

    @classmethod
    def from_assessment(
        cls, assessment: MlbDatasetReadinessAssessment
    ) -> MlbApprovedDatasetReadinessResponse:
        policy = approved_mlb_dataset_readiness_policy()
        return cls(
            policy_name=assessment.policy_name,
            policy_version=assessment.policy_version,
            policy_fingerprint=assessment.policy_fingerprint,
            split_policy_fingerprint=assessment.split_policy_fingerprint,
            validation_start=policy.split_policy.validation_start,
            test_start=policy.split_policy.test_start,
            prospective_holdout_start=policy.split_policy.prospective_holdout_start,
            minimum_split_counts=assessment.minimum_split_counts,
            eligible_split_counts=assessment.eligible_split_counts,
            shortfall_by_split=assessment.shortfall_by_split,
            exploratory_fit_data_ready=assessment.exploratory_fit_data_ready,
            prospective_evaluation_data_ready=assessment.prospective_evaluation_data_ready,
            retrospective_allowed_for_exploratory_splits=True,
            prospective_holdout_requires_operational_pregame=True,
            model_fitting_enabled=False,
            probability_generation_enabled=False,
            automatic_trading_enabled=False,
            blockers=assessment.blockers,
        )
