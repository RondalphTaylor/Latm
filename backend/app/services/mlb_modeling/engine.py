from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from datetime import datetime
from decimal import Decimal

from app.domain.mlb_modeling import (
    SELECTED_MLB_FEATURES,
    MlbChronologicalDatasetPolicy,
    MlbDatasetReadinessAssessment,
    MlbDatasetReadinessInput,
    MlbDatasetReadinessPolicy,
    MlbDatasetSplit,
    MlbFeatureSelectionPolicy,
    MlbGameFeatureVector,
    MlbLabeledFeatureExample,
    MlbLineupModelMetrics,
    MlbMatchupFeatureCoverage,
    MlbMatchupSourceMetrics,
    MlbModelFeatureInput,
    MlbOfficialOutcomeInput,
    MlbSelectedFeatureValues,
    MlbSideFeatureCoverage,
    MlbStartingPitcherModelMetrics,
)
from app.domain.mlb_statcast import (
    MlbStatcastObservationBasis,
    MlbStatcastPlayerFeatures,
    quantize_statcast_metric,
)

_FORMULA_SPEC = {
    "lineup": "pooled numerator / pooled denominator; home minus away",
    "starter": "away allowed minus home allowed",
    "rounding": "0.000001 ROUND_HALF_EVEN",
    "missing": "no imputation; all nine batters required per lineup metric",
}


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def mlb_feature_selection_policy_fingerprint(policy: MlbFeatureSelectionPolicy) -> str:
    return _hash({"policy": policy.model_dump(mode="json"), "formulas": _FORMULA_SPEC})


def mlb_chronological_split_policy_fingerprint(
    policy: MlbChronologicalDatasetPolicy,
) -> str:
    return _hash(policy.model_dump(mode="json"))


def mlb_dataset_readiness_policy_fingerprint(policy: MlbDatasetReadinessPolicy) -> str:
    return _hash(policy.model_dump(mode="json"))


class DeterministicMlbDatasetReadinessEngine:
    """Evaluate approved minimums without fitting a model or emitting probabilities."""

    def evaluate(self, source: MlbDatasetReadinessInput) -> MlbDatasetReadinessAssessment:
        expected_split_fingerprint = mlb_chronological_split_policy_fingerprint(
            source.policy.split_policy
        )
        if source.split_policy_fingerprint != expected_split_fingerprint:
            raise ValueError("MLB readiness counts use a different chronological split policy")

        minimums = {
            MlbDatasetSplit.TRAIN: source.policy.minimum_train_examples,
            MlbDatasetSplit.VALIDATION: source.policy.minimum_validation_examples,
            MlbDatasetSplit.TEST: source.policy.minimum_test_examples,
            MlbDatasetSplit.PROSPECTIVE_HOLDOUT: (
                source.policy.minimum_prospective_holdout_examples
            ),
        }
        eligible: dict[MlbDatasetSplit, int] = {}
        for split in MlbDatasetSplit:
            operational = source.operational_split_counts.get(split, 0)
            retrospective = source.retrospective_split_counts.get(split, 0)
            eligible[split] = (
                operational
                if split is MlbDatasetSplit.PROSPECTIVE_HOLDOUT
                else operational + retrospective
            )
        shortfalls = {split: max(minimums[split] - eligible[split], 0) for split in MlbDatasetSplit}
        exploratory_ready = all(
            shortfalls[split] == 0
            for split in (
                MlbDatasetSplit.TRAIN,
                MlbDatasetSplit.VALIDATION,
                MlbDatasetSplit.TEST,
            )
        )
        prospective_ready = exploratory_ready and all(
            shortfall == 0 for shortfall in shortfalls.values()
        )
        blockers = tuple(
            f"{split.value}_shortfall:{shortfalls[split]}"
            for split in MlbDatasetSplit
            if shortfalls[split] > 0
        )
        return MlbDatasetReadinessAssessment(
            policy_name=source.policy.policy_name,
            policy_version=source.policy.policy_version,
            policy_fingerprint=mlb_dataset_readiness_policy_fingerprint(source.policy),
            split_policy_fingerprint=expected_split_fingerprint,
            minimum_split_counts=minimums,
            eligible_split_counts=eligible,
            shortfall_by_split=shortfalls,
            exploratory_fit_data_ready=exploratory_ready,
            prospective_evaluation_data_ready=prospective_ready,
            blockers=blockers,
        )


def _weighted(
    profiles: Iterable[MlbStatcastPlayerFeatures],
    value: Callable[[MlbStatcastPlayerFeatures], Decimal | None],
    weight: Callable[[MlbStatcastPlayerFeatures], int | Decimal],
) -> Decimal | None:
    numerator = Decimal(0)
    denominator = Decimal(0)
    for profile in profiles:
        metric = value(profile)
        sample = Decimal(weight(profile))
        if metric is not None and sample > 0:
            numerator += metric * sample
            denominator += sample
    return None if denominator == 0 else quantize_statcast_metric(numerator / denominator)


def _lineup_metrics(
    profiles: tuple[MlbStatcastPlayerFeatures, ...], required: int
) -> MlbLineupModelMetrics:
    def enough(attribute: str) -> bool:
        return sum(getattr(profile, attribute) is not None for profile in profiles) == required

    observed = (
        quantize_statcast_metric(
            sum((p.woba_numerator for p in profiles), Decimal(0))
            / sum((p.woba_denominator for p in profiles), Decimal(0))
        )
        if enough("observed_woba") and sum((p.woba_denominator for p in profiles), Decimal(0)) > 0
        else None
    )
    expected = (
        _weighted(
            profiles,
            lambda p: p.average_estimated_woba_on_contact,
            lambda p: p.estimated_woba_contact_sample_size,
        )
        if enough("average_estimated_woba_on_contact")
        else None
    )
    hard_hit = (
        quantize_statcast_metric(
            Decimal(sum(p.hard_hit_count for p in profiles))
            / Decimal(sum(p.exit_velocity_sample_size for p in profiles))
        )
        if enough("hard_hit_rate") and sum(p.exit_velocity_sample_size for p in profiles) > 0
        else None
    )
    barrel = (
        quantize_statcast_metric(
            Decimal(sum(p.barrel_count for p in profiles))
            / Decimal(sum(p.launch_quality_sample_size for p in profiles))
        )
        if enough("barrel_rate") and sum(p.launch_quality_sample_size for p in profiles) > 0
        else None
    )
    return MlbLineupModelMetrics(
        observed_woba=observed,
        average_expected_woba_on_contact=expected,
        hard_hit_rate=hard_hit,
        barrel_rate=barrel,
    )


def _pitcher_metrics(profile: MlbStatcastPlayerFeatures) -> MlbStartingPitcherModelMetrics:
    return MlbStartingPitcherModelMetrics(
        observed_woba_allowed=profile.observed_woba,
        average_expected_woba_on_contact_allowed=(profile.average_estimated_woba_on_contact),
        hard_hit_rate_allowed=profile.hard_hit_rate,
        barrel_rate_allowed=profile.barrel_rate,
    )


def _coverage(
    batters: tuple[MlbStatcastPlayerFeatures, ...], pitcher: MlbStatcastPlayerFeatures
) -> MlbSideFeatureCoverage:
    return MlbSideFeatureCoverage(
        lineup_player_count=len(batters),
        lineup_players_with_observed_woba=sum(p.observed_woba is not None for p in batters),
        lineup_players_with_expected_woba_contact=sum(
            p.average_estimated_woba_on_contact is not None for p in batters
        ),
        lineup_players_with_hard_hit_rate=sum(p.hard_hit_rate is not None for p in batters),
        lineup_players_with_barrel_rate=sum(p.barrel_rate is not None for p in batters),
        lineup_plate_appearance_count=sum(p.plate_appearance_count for p in batters),
        lineup_complete_woba_sample_size=sum(p.complete_woba_sample_size for p in batters),
        lineup_incomplete_woba_sample_size=sum(p.incomplete_woba_sample_size for p in batters),
        lineup_expected_woba_contact_sample_size=sum(
            p.estimated_woba_contact_sample_size for p in batters
        ),
        lineup_exit_velocity_sample_size=sum(p.exit_velocity_sample_size for p in batters),
        lineup_launch_quality_sample_size=sum(p.launch_quality_sample_size for p in batters),
        starting_pitcher_pitch_count=pitcher.pitch_count,
        starting_pitcher_plate_appearance_count=pitcher.plate_appearance_count,
        starting_pitcher_complete_woba_sample_size=pitcher.complete_woba_sample_size,
        starting_pitcher_incomplete_woba_sample_size=pitcher.incomplete_woba_sample_size,
        starting_pitcher_expected_woba_contact_sample_size=(
            pitcher.estimated_woba_contact_sample_size
        ),
        starting_pitcher_exit_velocity_sample_size=pitcher.exit_velocity_sample_size,
        starting_pitcher_launch_quality_sample_size=pitcher.launch_quality_sample_size,
    )


def _difference(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    return None if left is None or right is None else quantize_statcast_metric(left - right)


class DeterministicMlbGameFeatureEngine:
    """Select a fixed auditable feature vector without fitting or forecasting."""

    def evaluate(self, source: MlbModelFeatureInput) -> MlbGameFeatureVector:
        policy = source.policy
        home_lineup = _lineup_metrics(source.home_batters, policy.required_lineup_batter_coverage)
        away_lineup = _lineup_metrics(source.away_batters, policy.required_lineup_batter_coverage)
        home_pitcher = _pitcher_metrics(source.home_starting_pitcher)
        away_pitcher = _pitcher_metrics(source.away_starting_pitcher)
        source_metrics = MlbMatchupSourceMetrics(
            home_lineup=home_lineup,
            away_lineup=away_lineup,
            home_starting_pitcher=home_pitcher,
            away_starting_pitcher=away_pitcher,
        )
        values = MlbSelectedFeatureValues(
            lineup_observed_woba_difference=_difference(
                home_lineup.observed_woba, away_lineup.observed_woba
            ),
            lineup_expected_woba_contact_difference=_difference(
                home_lineup.average_expected_woba_on_contact,
                away_lineup.average_expected_woba_on_contact,
            ),
            lineup_hard_hit_rate_difference=_difference(
                home_lineup.hard_hit_rate, away_lineup.hard_hit_rate
            ),
            lineup_barrel_rate_difference=_difference(
                home_lineup.barrel_rate, away_lineup.barrel_rate
            ),
            starting_pitcher_observed_woba_allowed_difference=_difference(
                away_pitcher.observed_woba_allowed, home_pitcher.observed_woba_allowed
            ),
            starting_pitcher_expected_woba_contact_allowed_difference=_difference(
                away_pitcher.average_expected_woba_on_contact_allowed,
                home_pitcher.average_expected_woba_on_contact_allowed,
            ),
            starting_pitcher_hard_hit_rate_allowed_difference=_difference(
                away_pitcher.hard_hit_rate_allowed, home_pitcher.hard_hit_rate_allowed
            ),
            starting_pitcher_barrel_rate_allowed_difference=_difference(
                away_pitcher.barrel_rate_allowed, home_pitcher.barrel_rate_allowed
            ),
        )
        missing = tuple(
            feature
            for feature, value in zip(SELECTED_MLB_FEATURES, values.ordered_values(), strict=True)
            if value is None
        )
        policy_fp = mlb_feature_selection_policy_fingerprint(policy)
        input_fp = _hash(
            {
                "sports_event_id": str(source.sports_event_id),
                "lineup_snapshot_id": str(source.lineup_snapshot_id),
                "statcast_snapshot_id": str(source.statcast_snapshot_id),
                "statcast_policy_fingerprint": source.statcast_policy_fingerprint,
                "statcast_source_fingerprint": source.statcast_source_fingerprint,
                "statcast_input_fingerprint": source.statcast_input_fingerprint,
                "policy_fingerprint": policy_fp,
            }
        )
        basis = (
            MlbStatcastObservationBasis.OPERATIONAL_PREGAME
            if source.source_operational_pregame_eligible
            and source.built_at < source.scheduled_start_time
            else MlbStatcastObservationBasis.RETROSPECTIVE
        )
        complete = not missing
        return MlbGameFeatureVector(
            sports_event_id=source.sports_event_id,
            lineup_snapshot_id=source.lineup_snapshot_id,
            statcast_snapshot_id=source.statcast_snapshot_id,
            provider_event_id=source.provider_event_id,
            target_event_date=source.target_event_date,
            scheduled_start_time=source.scheduled_start_time,
            home_team_id=source.home_team_id,
            away_team_id=source.away_team_id,
            source_retrieved_at=source.source_retrieved_at,
            source_observation_basis=source.source_observation_basis,
            built_at=source.built_at,
            feature_availability_basis=basis,
            policy_name=policy.policy_name,
            policy_version=policy.policy_version,
            model_candidate_name=policy.model_candidate_name,
            policy_fingerprint=policy_fp,
            source_metrics=source_metrics,
            coverage=MlbMatchupFeatureCoverage(
                home=_coverage(source.home_batters, source.home_starting_pitcher),
                away=_coverage(source.away_batters, source.away_starting_pitcher),
            ),
            feature_values=values,
            missing_features=missing,
            complete_feature_vector=complete,
            operational_model_input_eligible=(
                complete and basis is MlbStatcastObservationBasis.OPERATIONAL_PREGAME
            ),
            source_fingerprint=source.statcast_source_fingerprint,
            input_fingerprint=input_fp,
        )


class DeterministicMlbDatasetContract:
    """Assign chronological partitions and official postgame labels without fitting."""

    @staticmethod
    def assign_split(
        scheduled_start_time: datetime, policy: MlbChronologicalDatasetPolicy
    ) -> MlbDatasetSplit:
        if scheduled_start_time.tzinfo is None or scheduled_start_time.utcoffset() is None:
            raise ValueError("scheduled_start_time must be timezone-aware")
        if scheduled_start_time < policy.validation_start:
            return MlbDatasetSplit.TRAIN
        if scheduled_start_time < policy.test_start:
            return MlbDatasetSplit.VALIDATION
        if scheduled_start_time < policy.prospective_holdout_start:
            return MlbDatasetSplit.TEST
        return MlbDatasetSplit.PROSPECTIVE_HOLDOUT

    def label(
        self,
        vector: MlbGameFeatureVector,
        outcome: MlbOfficialOutcomeInput,
        policy: MlbChronologicalDatasetPolicy,
    ) -> MlbLabeledFeatureExample:
        if vector.sports_event_id != outcome.sports_event_id:
            raise ValueError("outcome belongs to a different MLB event")
        if vector.scheduled_start_time != outcome.scheduled_start_time:
            raise ValueError("official scheduled start changed")
        if not vector.complete_feature_vector:
            raise ValueError("incomplete feature vectors cannot become labeled examples")
        if outcome.status != "final" or outcome.home_score is None or outcome.away_score is None:
            raise ValueError("an official final MLB result is required")
        if outcome.home_score == outcome.away_score:
            raise ValueError("MLB model outcomes must be decisive")
        if outcome.source_last_seen_at < outcome.scheduled_start_time:
            raise ValueError("official outcome observation cannot precede first pitch")
        policy_fp = mlb_chronological_split_policy_fingerprint(policy)
        outcome_fp = _hash(outcome.model_dump(mode="json"))
        split = self.assign_split(vector.scheduled_start_time, policy)
        example_fp = _hash(
            {
                "feature_vector_input_fingerprint": vector.input_fingerprint,
                "outcome_fingerprint": outcome_fp,
                "split_policy_fingerprint": policy_fp,
                "split": split.value,
            }
        )
        return MlbLabeledFeatureExample(
            sports_event_id=vector.sports_event_id,
            feature_vector_input_fingerprint=vector.input_fingerprint,
            feature_policy_fingerprint=vector.policy_fingerprint,
            availability_basis=vector.feature_availability_basis,
            scheduled_start_time=vector.scheduled_start_time,
            home_won=outcome.home_score > outcome.away_score,
            split=split,
            split_policy_fingerprint=policy_fp,
            outcome_fingerprint=outcome_fp,
            example_fingerprint=example_fp,
        )
