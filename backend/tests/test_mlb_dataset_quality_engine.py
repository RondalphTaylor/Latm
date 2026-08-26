from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from app.domain.mlb_dataset_quality import (
    MlbDatasetQualityExample,
    MlbDatasetQualityInput,
    MlbDatasetQualityPolicy,
)
from app.domain.mlb_modeling import (
    SELECTED_MLB_FEATURES,
    MlbDatasetSplit,
    MlbFeatureSelectionPolicy,
    MlbMatchupFeatureCoverage,
    MlbSelectedFeatureValues,
    MlbSideFeatureCoverage,
    approved_mlb_dataset_readiness_policy,
)
from app.domain.mlb_statcast import MlbStatcastObservationBasis
from app.services.mlb_modeling.engine import (
    mlb_chronological_split_policy_fingerprint,
    mlb_feature_selection_policy_fingerprint,
)
from app.services.mlb_modeling.quality import (
    DeterministicMlbDatasetQualityEngine,
    mlb_dataset_quality_policy_fingerprint,
)


def _coverage(seed: int) -> MlbMatchupFeatureCoverage:
    def side(offset: int) -> MlbSideFeatureCoverage:
        sample = 80 + seed + offset
        return MlbSideFeatureCoverage(
            lineup_player_count=9,
            lineup_players_with_observed_woba=9,
            lineup_players_with_expected_woba_contact=9,
            lineup_players_with_hard_hit_rate=9,
            lineup_players_with_barrel_rate=9,
            lineup_plate_appearance_count=sample,
            lineup_complete_woba_sample_size=sample,
            lineup_incomplete_woba_sample_size=0,
            lineup_expected_woba_contact_sample_size=sample - 5,
            lineup_exit_velocity_sample_size=sample - 10,
            lineup_launch_quality_sample_size=sample - 12,
            starting_pitcher_pitch_count=95 + seed + offset,
            starting_pitcher_plate_appearance_count=24 + seed,
            starting_pitcher_complete_woba_sample_size=24 + seed,
            starting_pitcher_incomplete_woba_sample_size=0,
            starting_pitcher_expected_woba_contact_sample_size=20 + seed,
            starting_pitcher_exit_velocity_sample_size=19 + seed,
            starting_pitcher_launch_quality_sample_size=18 + seed,
        )

    return MlbMatchupFeatureCoverage(home=side(0), away=side(3))


def _features(seed: int, *, missing_first: bool = False) -> MlbSelectedFeatureValues:
    values: dict[str, Decimal | None] = {
        feature.value: (Decimal(seed + index + 1) / Decimal("1000"))
        for index, feature in enumerate(SELECTED_MLB_FEATURES)
    }
    if missing_first:
        values[SELECTED_MLB_FEATURES[0].value] = None
    return MlbSelectedFeatureValues.model_validate(values)


def _example(
    seed: int,
    *,
    start: datetime,
    split: MlbDatasetSplit,
    basis: MlbStatcastObservationBasis,
    missing_first: bool = False,
) -> MlbDatasetQualityExample:
    operational = basis is MlbStatcastObservationBasis.OPERATIONAL_PREGAME
    return MlbDatasetQualityExample(
        example_id=UUID(int=seed + 1),
        game_feature_vector_id=UUID(int=1_000 + seed),
        sports_event_id=UUID(int=2_000 + seed),
        scheduled_start_time=start,
        home_team_id=UUID(int=10 + (seed % 4)),
        away_team_id=UUID(int=20 + (seed % 4)),
        split=split,
        availability_basis=basis,
        home_won=seed % 2 == 0,
        feature_values=_features(seed, missing_first=missing_first),
        coverage=_coverage(seed),
        feature_policy_fingerprint=mlb_feature_selection_policy_fingerprint(
            MlbFeatureSelectionPolicy()
        ),
        feature_vector_input_fingerprint=f"{3_000 + seed:064x}",
        outcome_fingerprint=f"{4_000 + seed:064x}",
        example_fingerprint=f"{5_000 + seed:064x}",
        source_retrieved_at=(
            start - timedelta(minutes=30) if operational else start + timedelta(hours=3)
        ),
        vector_built_at=(
            start - timedelta(minutes=10) if operational else start + timedelta(hours=3)
        ),
        outcome_source_last_seen_at=start + timedelta(hours=4),
        labeled_at=start + timedelta(hours=5),
        complete_feature_vector=not missing_first,
        operational_model_input_eligible=operational and not missing_first,
        vector_research_only=True,
        vector_probability_generated=False,
        vector_automatic_trading_eligible=False,
        research_only=True,
        probability_generated=False,
        automatic_trading_eligible=False,
    )


def _input(examples: tuple[MlbDatasetQualityExample, ...]) -> MlbDatasetQualityInput:
    readiness = approved_mlb_dataset_readiness_policy()
    return MlbDatasetQualityInput(
        split_policy_fingerprint=mlb_chronological_split_policy_fingerprint(readiness.split_policy),
        split_policy=readiness.split_policy,
        feature_policy_fingerprint=mlb_feature_selection_policy_fingerprint(
            MlbFeatureSelectionPolicy()
        ),
        examples=examples,
        policy=MlbDatasetQualityPolicy(),
    )


def test_quality_audit_reports_balances_features_support_and_team_coverage() -> None:
    examples = (
        _example(
            0,
            start=datetime(2026, 5, 1, tzinfo=UTC),
            split=MlbDatasetSplit.TRAIN,
            basis=MlbStatcastObservationBasis.RETROSPECTIVE,
        ),
        _example(
            1,
            start=datetime(2026, 6, 10, tzinfo=UTC),
            split=MlbDatasetSplit.VALIDATION,
            basis=MlbStatcastObservationBasis.RETROSPECTIVE,
        ),
        _example(
            2,
            start=datetime(2026, 7, 10, tzinfo=UTC),
            split=MlbDatasetSplit.TEST,
            basis=MlbStatcastObservationBasis.RETROSPECTIVE,
        ),
        _example(
            3,
            start=datetime(2026, 8, 24, tzinfo=UTC),
            split=MlbDatasetSplit.PROSPECTIVE_HOLDOUT,
            basis=MlbStatcastObservationBasis.OPERATIONAL_PREGAME,
        ),
    )

    result = DeterministicMlbDatasetQualityEngine().evaluate(_input(examples))

    assert result.selected_example_count == 4
    assert result.operational_example_count == 1
    assert result.retrospective_example_count == 3
    assert result.unique_event_count == 4
    assert result.unique_team_count == 8
    assert result.home_win_count == 2
    assert result.home_win_rate == Decimal("0.500000000000")
    assert result.split_summaries[MlbDatasetSplit.TEST].example_count == 1
    first_feature = result.feature_summaries[SELECTED_MLB_FEATURES[0]]
    assert first_feature.missing_count == 0
    assert first_feature.minimum == Decimal("0.001")
    assert first_feature.maximum == Decimal("0.004")
    assert first_feature.zero_variance is False
    support = result.minimum_side_source_support["lineup_plate_appearance_count"]
    assert support.minimum == Decimal(80)
    assert support.maximum == Decimal(83)
    assert support.median == Decimal("81.500000")
    assert result.error_count == 0
    assert result.quality_passed is True
    assert result.probability_generation_enabled is False
    assert result.automatic_trading_enabled is False


def test_quality_audit_fails_closed_on_leakage_missingness_and_duplicate_event() -> None:
    first = _example(
        10,
        start=datetime(2026, 8, 24, tzinfo=UTC),
        split=MlbDatasetSplit.TEST,
        basis=MlbStatcastObservationBasis.RETROSPECTIVE,
        missing_first=True,
    )
    duplicate_event = _example(
        11,
        start=datetime(2026, 8, 25, tzinfo=UTC),
        split=MlbDatasetSplit.PROSPECTIVE_HOLDOUT,
        basis=MlbStatcastObservationBasis.OPERATIONAL_PREGAME,
    ).model_copy(update={"sports_event_id": first.sports_event_id})

    result = DeterministicMlbDatasetQualityEngine().evaluate(_input((first, duplicate_event)))
    codes = {issue.code for issue in result.issues}

    assert {
        "duplicate_event_id",
        "split_assignment_mismatch",
        "retrospective_prospective_holdout",
        "incomplete_feature_vector",
        "missing_selected_feature",
    } <= codes
    assert result.error_count >= 5
    assert result.quality_passed is False


def test_quality_fingerprint_is_order_independent_and_changes_with_source() -> None:
    first = _example(
        20,
        start=datetime(2026, 5, 10, tzinfo=UTC),
        split=MlbDatasetSplit.TRAIN,
        basis=MlbStatcastObservationBasis.RETROSPECTIVE,
    )
    second = _example(
        21,
        start=datetime(2026, 6, 10, tzinfo=UTC),
        split=MlbDatasetSplit.VALIDATION,
        basis=MlbStatcastObservationBasis.RETROSPECTIVE,
    )
    engine = DeterministicMlbDatasetQualityEngine()

    ordered = engine.evaluate(_input((first, second)))
    reversed_result = engine.evaluate(_input((second, first)))
    changed = engine.evaluate(
        _input((first, second.model_copy(update={"outcome_fingerprint": "f" * 64})))
    )

    assert ordered.input_fingerprint == reversed_result.input_fingerprint
    assert ordered.source_data_fingerprint == reversed_result.source_data_fingerprint
    assert changed.input_fingerprint != ordered.input_fingerprint
    assert len(mlb_dataset_quality_policy_fingerprint(MlbDatasetQualityPolicy())) == 64


def test_empty_quality_audit_is_explicit_and_non_operational() -> None:
    result = DeterministicMlbDatasetQualityEngine().evaluate(_input(()))

    assert result.selected_example_count == 0
    assert result.home_win_rate is None
    assert result.first_scheduled_start_time is None
    assert result.error_count == 0
    assert result.warning_count == 1
    assert result.issues[0].code == "empty_canonical_dataset"
    assert result.quality_passed is True
