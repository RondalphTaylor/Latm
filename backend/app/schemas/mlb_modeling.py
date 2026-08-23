from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.mlb_modeling import (
    SELECTED_MLB_FEATURES,
    MlbMatchupFeatureCoverage,
    MlbMatchupSourceMetrics,
    MlbSelectedFeatureName,
    MlbSelectedFeatureValues,
)
from app.models.mlb import MlbGameFeatureVectorRecord


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
