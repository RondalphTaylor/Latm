from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from uuid import UUID

from app.domain.mlb_dataset_quality import (
    MlbDatasetNumericSummary,
    MlbDatasetQualityExample,
    MlbDatasetQualityInput,
    MlbDatasetQualityIssue,
    MlbDatasetQualityPolicy,
    MlbDatasetQualityReport,
    MlbDatasetQualitySeverity,
    MlbFeatureQualitySummary,
    MlbSplitQualitySummary,
    MlbTeamCoverageSummary,
)
from app.domain.mlb_modeling import (
    SELECTED_MLB_FEATURES,
    MlbDatasetSplit,
    MlbSelectedFeatureName,
)
from app.domain.mlb_statcast import MlbStatcastObservationBasis
from app.services.mlb_modeling.engine import (
    DeterministicMlbDatasetContract,
    mlb_chronological_split_policy_fingerprint,
)

_SOURCE_SUPPORT_FIELDS = (
    "lineup_plate_appearance_count",
    "lineup_complete_woba_sample_size",
    "lineup_expected_woba_contact_sample_size",
    "lineup_exit_velocity_sample_size",
    "lineup_launch_quality_sample_size",
    "starting_pitcher_pitch_count",
    "starting_pitcher_plate_appearance_count",
    "starting_pitcher_complete_woba_sample_size",
    "starting_pitcher_expected_woba_contact_sample_size",
    "starting_pitcher_exit_velocity_sample_size",
    "starting_pitcher_launch_quality_sample_size",
)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def mlb_dataset_quality_policy_fingerprint(policy: MlbDatasetQualityPolicy) -> str:
    return _hash(policy.model_dump(mode="json"))


def _quantum(scale: int) -> Decimal:
    return Decimal(1).scaleb(-scale)


def _quantize(value: Decimal, scale: int) -> Decimal:
    return value.quantize(_quantum(scale), rounding=ROUND_HALF_EVEN)


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal(2)


def _numeric_summary(values: list[Decimal], scale: int) -> MlbDatasetNumericSummary:
    if not values:
        return MlbDatasetNumericSummary(count=0)
    return MlbDatasetNumericSummary(
        count=len(values),
        minimum=min(values),
        median=_quantize(_median(values), scale),
        mean=_quantize(sum(values, Decimal(0)) / Decimal(len(values)), scale),
        maximum=max(values),
    )


class DeterministicMlbDatasetQualityEngine:
    """Audit canonical MLB examples without fitting or producing a probability."""

    def evaluate(self, source: MlbDatasetQualityInput) -> MlbDatasetQualityReport:
        expected_split_fingerprint = mlb_chronological_split_policy_fingerprint(source.split_policy)
        if source.split_policy_fingerprint != expected_split_fingerprint:
            raise ValueError("MLB quality input uses a different chronological split policy")

        examples = tuple(
            sorted(
                source.examples,
                key=lambda item: (item.scheduled_start_time, item.sports_event_id, item.example_id),
            )
        )
        policy_fingerprint = mlb_dataset_quality_policy_fingerprint(source.policy)
        manifest = [
            {
                "ordinal": ordinal,
                "example_id": str(example.example_id),
                "game_feature_vector_id": str(example.game_feature_vector_id),
                "sports_event_id": str(example.sports_event_id),
                "scheduled_start_time": example.scheduled_start_time.isoformat(),
                "split": example.split.value,
                "availability_basis": example.availability_basis.value,
                "feature_vector_input_fingerprint": (example.feature_vector_input_fingerprint),
                "outcome_fingerprint": example.outcome_fingerprint,
                "example_fingerprint": example.example_fingerprint,
            }
            for ordinal, example in enumerate(examples)
        ]
        source_data_fingerprint = _hash(manifest)
        input_fingerprint = _hash(
            {
                "policy_fingerprint": policy_fingerprint,
                "split_policy_fingerprint": source.split_policy_fingerprint,
                "feature_policy_fingerprint": source.feature_policy_fingerprint,
                "source_data_fingerprint": source_data_fingerprint,
            }
        )

        issues: list[MlbDatasetQualityIssue] = []

        def issue(
            severity: MlbDatasetQualitySeverity,
            code: str,
            message: str,
            *,
            example_id: UUID | None = None,
            sports_event_id: UUID | None = None,
            split: MlbDatasetSplit | None = None,
            feature: MlbSelectedFeatureName | None = None,
        ) -> None:
            issues.append(
                MlbDatasetQualityIssue(
                    severity=severity,
                    code=code,
                    message=message,
                    example_id=example_id,
                    sports_event_id=sports_event_id,
                    split=split,
                    feature=feature,
                )
            )

        def example_issue(
            severity: MlbDatasetQualitySeverity,
            code: str,
            message: str,
            example: MlbDatasetQualityExample,
            *,
            feature: MlbSelectedFeatureName | None = None,
        ) -> None:
            issue(
                severity,
                code,
                message,
                example_id=example.example_id,
                sports_event_id=example.sports_event_id,
                split=example.split,
                feature=feature,
            )

        if not examples:
            issue(
                MlbDatasetQualitySeverity.WARNING,
                "empty_canonical_dataset",
                "the approved canonical dataset contains no labeled examples",
            )

        identity_fields: dict[str, list[UUID | str]] = {
            "duplicate_example_id": [item.example_id for item in examples],
            "duplicate_event_id": [item.sports_event_id for item in examples],
            "duplicate_vector_id": [item.game_feature_vector_id for item in examples],
            "duplicate_vector_input_fingerprint": [
                item.feature_vector_input_fingerprint for item in examples
            ],
            "duplicate_example_fingerprint": [item.example_fingerprint for item in examples],
        }
        for code, identity_values in identity_fields.items():
            duplicates = sorted(
                (str(key) for key, count in Counter(identity_values).items() if count > 1)
            )
            if duplicates:
                issue(
                    MlbDatasetQualitySeverity.ERROR,
                    code,
                    f"canonical selection contains duplicate identities: {', '.join(duplicates)}",
                )

        for example in examples:
            expected_split = DeterministicMlbDatasetContract.assign_split(
                example.scheduled_start_time, source.split_policy
            )
            if example.split is not expected_split:
                example_issue(
                    MlbDatasetQualitySeverity.ERROR,
                    "split_assignment_mismatch",
                    f"stored split {example.split.value} should be {expected_split.value}",
                    example,
                )
            if example.feature_policy_fingerprint != source.feature_policy_fingerprint:
                example_issue(
                    MlbDatasetQualitySeverity.ERROR,
                    "feature_policy_mismatch",
                    "canonical example uses a different feature-selection policy",
                    example,
                )
            if example.home_team_id == example.away_team_id:
                example_issue(
                    MlbDatasetQualitySeverity.ERROR,
                    "identical_teams",
                    "canonical example has the same home and away team",
                    example,
                )
            if not example.complete_feature_vector:
                example_issue(
                    MlbDatasetQualitySeverity.ERROR,
                    "incomplete_feature_vector",
                    "a labeled canonical example references an incomplete feature vector",
                    example,
                )
            if expected_split is MlbDatasetSplit.PROSPECTIVE_HOLDOUT and (
                example.availability_basis is not MlbStatcastObservationBasis.OPERATIONAL_PREGAME
            ):
                example_issue(
                    MlbDatasetQualitySeverity.ERROR,
                    "retrospective_prospective_holdout",
                    "prospective holdout contains retrospective evidence",
                    example,
                )
            expected_operational = (
                example.complete_feature_vector
                and example.availability_basis is MlbStatcastObservationBasis.OPERATIONAL_PREGAME
                and example.source_retrieved_at < example.scheduled_start_time
                and example.vector_built_at < example.scheduled_start_time
            )
            if example.operational_model_input_eligible != expected_operational:
                example_issue(
                    MlbDatasetQualitySeverity.ERROR,
                    "operational_eligibility_mismatch",
                    "stored operational eligibility is inconsistent with source timing",
                    example,
                )
            if example.availability_basis is MlbStatcastObservationBasis.OPERATIONAL_PREGAME and (
                example.source_retrieved_at >= example.scheduled_start_time
                or example.vector_built_at >= example.scheduled_start_time
            ):
                example_issue(
                    MlbDatasetQualitySeverity.ERROR,
                    "operational_timing_violation",
                    "operational evidence was retrieved or built at/after first pitch",
                    example,
                )
            if example.outcome_source_last_seen_at < example.scheduled_start_time:
                example_issue(
                    MlbDatasetQualitySeverity.ERROR,
                    "outcome_timing_violation",
                    "official outcome observation predates first pitch",
                    example,
                )
            if example.labeled_at < example.outcome_source_last_seen_at:
                example_issue(
                    MlbDatasetQualitySeverity.ERROR,
                    "label_timing_violation",
                    "label time predates its official outcome observation",
                    example,
                )
            if (
                not example.vector_research_only
                or example.vector_probability_generated
                or example.vector_automatic_trading_eligible
                or not example.research_only
                or example.probability_generated
                or example.automatic_trading_eligible
            ):
                example_issue(
                    MlbDatasetQualitySeverity.ERROR,
                    "safety_flag_violation",
                    "canonical example violates the research-only safety boundary",
                    example,
                )
            for feature, value in zip(
                SELECTED_MLB_FEATURES,
                example.feature_values.ordered_values(),
                strict=True,
            ):
                if value is None:
                    example_issue(
                        MlbDatasetQualitySeverity.ERROR,
                        "missing_selected_feature",
                        "canonical labeled example has a missing selected feature",
                        example,
                        feature=feature,
                    )

        split_summaries: dict[MlbDatasetSplit, MlbSplitQualitySummary] = {}
        for split in MlbDatasetSplit:
            members = [example for example in examples if example.split is split]
            home_wins = sum(item.home_won for item in members)
            operational = sum(
                item.availability_basis is MlbStatcastObservationBasis.OPERATIONAL_PREGAME
                for item in members
            )
            teams = {team for item in members for team in (item.home_team_id, item.away_team_id)}
            split_summaries[split] = MlbSplitQualitySummary(
                split=split,
                example_count=len(members),
                operational_example_count=operational,
                retrospective_example_count=len(members) - operational,
                home_win_count=home_wins,
                away_win_count=len(members) - home_wins,
                home_win_rate=(
                    _quantize(
                        Decimal(home_wins) / Decimal(len(members)),
                        source.policy.feature_statistic_scale,
                    )
                    if members
                    else None
                ),
                unique_team_count=len(teams),
                first_scheduled_start_time=(members[0].scheduled_start_time if members else None),
                last_scheduled_start_time=(members[-1].scheduled_start_time if members else None),
            )
            if len(members) > 1 and home_wins in (0, len(members)):
                issue(
                    MlbDatasetQualitySeverity.WARNING,
                    "single_class_split",
                    f"{split.value} contains only one observed outcome class",
                    split=split,
                )

        feature_summaries: dict[MlbSelectedFeatureName, MlbFeatureQualitySummary] = {}
        with localcontext() as context:
            context.prec = 50
            for feature in SELECTED_MLB_FEATURES:
                feature_values = [
                    value
                    for example in examples
                    if (value := getattr(example.feature_values, feature.value)) is not None
                ]
                mean = (
                    sum(feature_values, Decimal(0)) / Decimal(len(feature_values))
                    if feature_values
                    else None
                )
                variance = (
                    sum(((value - mean) ** 2 for value in feature_values), Decimal(0))
                    / Decimal(len(feature_values))
                    if feature_values and mean is not None
                    else None
                )
                stddev = variance.sqrt() if variance is not None else None
                zero_variance = len(feature_values) > 1 and min(feature_values) == max(
                    feature_values
                )
                feature_summaries[feature] = MlbFeatureQualitySummary(
                    feature=feature,
                    example_count=len(examples),
                    available_count=len(feature_values),
                    missing_count=len(examples) - len(feature_values),
                    minimum=min(feature_values) if feature_values else None,
                    maximum=max(feature_values) if feature_values else None,
                    mean=(
                        _quantize(mean, source.policy.feature_statistic_scale)
                        if mean is not None
                        else None
                    ),
                    population_standard_deviation=(
                        _quantize(stddev, source.policy.feature_statistic_scale)
                        if stddev is not None
                        else None
                    ),
                    zero_variance=zero_variance,
                )
                if zero_variance:
                    issue(
                        MlbDatasetQualitySeverity.WARNING,
                        "zero_variance_feature",
                        f"{feature.value} has zero variance across canonical examples",
                        feature=feature,
                    )

        source_support: dict[str, MlbDatasetNumericSummary] = {}
        for field in _SOURCE_SUPPORT_FIELDS:
            support_values = [
                Decimal(
                    min(
                        getattr(example.coverage.home, field),
                        getattr(example.coverage.away, field),
                    )
                )
                for example in examples
            ]
            source_support[field] = _numeric_summary(
                support_values, source.policy.source_support_scale
            )

        home_counts: defaultdict[UUID, int] = defaultdict(int)
        away_counts: defaultdict[UUID, int] = defaultdict(int)
        for example in examples:
            home_counts[example.home_team_id] += 1
            away_counts[example.away_team_id] += 1
        team_ids = sorted(set(home_counts) | set(away_counts), key=str)
        team_coverage = tuple(
            MlbTeamCoverageSummary(
                team_id=team_id,
                appearance_count=home_counts[team_id] + away_counts[team_id],
                home_game_count=home_counts[team_id],
                away_game_count=away_counts[team_id],
            )
            for team_id in team_ids
        )

        home_wins = sum(item.home_won for item in examples)
        operational_count = sum(
            item.availability_basis is MlbStatcastObservationBasis.OPERATIONAL_PREGAME
            for item in examples
        )
        issues.sort(
            key=lambda item: (
                item.severity.value,
                item.code,
                str(item.sports_event_id or ""),
                str(item.example_id or ""),
                item.feature.value if item.feature is not None else "",
            )
        )
        error_count = sum(item.severity is MlbDatasetQualitySeverity.ERROR for item in issues)
        return MlbDatasetQualityReport(
            policy_name=source.policy.policy_name,
            policy_version=source.policy.policy_version,
            policy_fingerprint=policy_fingerprint,
            split_policy_fingerprint=source.split_policy_fingerprint,
            feature_policy_fingerprint=source.feature_policy_fingerprint,
            source_data_fingerprint=source_data_fingerprint,
            input_fingerprint=input_fingerprint,
            selected_example_count=len(examples),
            operational_example_count=operational_count,
            retrospective_example_count=len(examples) - operational_count,
            unique_event_count=len({item.sports_event_id for item in examples}),
            unique_team_count=len(team_coverage),
            home_win_count=home_wins,
            away_win_count=len(examples) - home_wins,
            home_win_rate=(
                _quantize(
                    Decimal(home_wins) / Decimal(len(examples)),
                    source.policy.feature_statistic_scale,
                )
                if examples
                else None
            ),
            first_scheduled_start_time=(examples[0].scheduled_start_time if examples else None),
            last_scheduled_start_time=(examples[-1].scheduled_start_time if examples else None),
            split_summaries=split_summaries,
            feature_summaries=feature_summaries,
            minimum_side_source_support=source_support,
            team_coverage=team_coverage,
            issues=tuple(issues),
            error_count=error_count,
            warning_count=len(issues) - error_count,
            quality_passed=error_count == 0,
        )
