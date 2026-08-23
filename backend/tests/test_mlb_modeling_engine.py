from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain.mlb_modeling import (
    MlbChronologicalDatasetPolicy,
    MlbDatasetSplit,
    MlbFeatureSelectionPolicy,
    MlbModelFeatureInput,
    MlbOfficialOutcomeInput,
    MlbSelectedFeatureName,
)
from app.domain.mlb_statcast import (
    MlbStatcastObservationBasis,
    MlbStatcastPlayerFeatures,
    MlbStatcastPlayerRole,
    quantize_statcast_metric,
)
from app.services.mlb_modeling.engine import (
    DeterministicMlbDatasetContract,
    DeterministicMlbGameFeatureEngine,
)

EVENT_ID = UUID("10000000-0000-0000-0000-000000000001")
LINEUP_ID = UUID("20000000-0000-0000-0000-000000000002")
STATCAST_ID = UUID("30000000-0000-0000-0000-000000000003")
HOME_ID = UUID("40000000-0000-0000-0000-000000000004")
AWAY_ID = UUID("50000000-0000-0000-0000-000000000005")
START = datetime(2026, 8, 23, 23, 10, tzinfo=UTC)


def profile(
    player_id: int,
    *,
    role: MlbStatcastPlayerRole = MlbStatcastPlayerRole.BATTER,
    weight: int = 10,
    woba: Decimal = Decimal("0.300000"),
    expected: Decimal | None = Decimal("0.320000"),
    hard_hits: int = 4,
    barrels: int = 1,
) -> MlbStatcastPlayerFeatures:
    return MlbStatcastPlayerFeatures(
        role=role,
        provider_player_id=str(player_id),
        full_name=f"Player {player_id}",
        pitch_count=weight,
        plate_appearance_count=weight,
        batted_ball_event_count=weight,
        source_game_count=1,
        first_game_date=date(2026, 8, 1),
        last_game_date=date(2026, 8, 20),
        release_speed_sample_size=weight if role is MlbStatcastPlayerRole.PITCHER else 0,
        average_release_speed_mph=(
            Decimal("94.000000") if role is MlbStatcastPlayerRole.PITCHER else None
        ),
        spin_rate_sample_size=weight if role is MlbStatcastPlayerRole.PITCHER else 0,
        average_release_spin_rate_rpm=(
            Decimal("2300.000000") if role is MlbStatcastPlayerRole.PITCHER else None
        ),
        exit_velocity_sample_size=weight,
        average_exit_velocity_mph=Decimal("90.000000"),
        hard_hit_count=hard_hits,
        hard_hit_rate=quantize_statcast_metric(Decimal(hard_hits) / Decimal(weight)),
        launch_quality_sample_size=weight,
        barrel_count=barrels,
        barrel_rate=quantize_statcast_metric(Decimal(barrels) / Decimal(weight)),
        estimated_woba_contact_sample_size=weight if expected is not None else 0,
        average_estimated_woba_on_contact=expected,
        complete_woba_sample_size=weight,
        incomplete_woba_sample_size=0,
        woba_numerator=woba * Decimal(weight),
        woba_denominator=Decimal(weight),
        observed_woba=woba,
    )


def feature_input(
    *,
    retrieved_at: datetime = START - timedelta(minutes=20),
    built_at: datetime = START - timedelta(minutes=10),
    home_batters: tuple[MlbStatcastPlayerFeatures, ...] | None = None,
) -> MlbModelFeatureInput:
    return MlbModelFeatureInput(
        sports_event_id=EVENT_ID,
        lineup_snapshot_id=LINEUP_ID,
        statcast_snapshot_id=STATCAST_ID,
        provider_event_id="823509",
        target_event_date=START.date(),
        scheduled_start_time=START,
        home_team_id=HOME_ID,
        away_team_id=AWAY_ID,
        source_retrieved_at=retrieved_at,
        source_observation_basis=(
            MlbStatcastObservationBasis.OPERATIONAL_PREGAME
            if retrieved_at < START
            else MlbStatcastObservationBasis.RETROSPECTIVE
        ),
        source_operational_pregame_eligible=retrieved_at < START,
        statcast_policy_fingerprint="a" * 64,
        statcast_source_fingerprint="b" * 64,
        statcast_input_fingerprint="c" * 64,
        home_starting_pitcher=profile(
            1,
            role=MlbStatcastPlayerRole.PITCHER,
            woba=Decimal("0.250000"),
            expected=Decimal("0.280000"),
            hard_hits=3,
        ),
        away_starting_pitcher=profile(
            2,
            role=MlbStatcastPlayerRole.PITCHER,
            woba=Decimal("0.350000"),
            expected=Decimal("0.360000"),
            hard_hits=5,
            barrels=2,
        ),
        home_batters=home_batters
        or tuple(profile(index + 10, weight=10, woba=Decimal("0.340000")) for index in range(9)),
        away_batters=tuple(
            profile(index + 20, weight=10, woba=Decimal("0.300000"), hard_hits=3)
            for index in range(9)
        ),
        built_at=built_at,
        policy=MlbFeatureSelectionPolicy(),
    )


def test_selects_weighted_home_oriented_features_without_probability() -> None:
    vector = DeterministicMlbGameFeatureEngine().evaluate(feature_input())

    assert vector.feature_values.lineup_observed_woba_difference == Decimal("0.040000")
    assert vector.feature_values.starting_pitcher_observed_woba_allowed_difference == Decimal(
        "0.100000"
    )
    assert vector.complete_feature_vector is True
    assert vector.operational_model_input_eligible is True
    assert vector.probability_generated is False
    assert vector.automatic_trading_eligible is False
    assert vector.research_only is True


def test_lineup_pooling_uses_samples_instead_of_unweighted_player_means() -> None:
    batters = [profile(index + 10) for index in range(9)]
    batters[0] = profile(10, weight=90, woba=Decimal("0.500000"))
    vector = DeterministicMlbGameFeatureEngine().evaluate(
        feature_input(home_batters=tuple(batters))
    )

    assert vector.source_metrics.home_lineup.observed_woba == Decimal("0.405882")


def test_missing_one_batter_metric_preserves_missingness_and_blocks_eligibility() -> None:
    batters = [profile(index + 10) for index in range(9)]
    batters[0] = profile(10, expected=None)
    vector = DeterministicMlbGameFeatureEngine().evaluate(
        feature_input(home_batters=tuple(batters))
    )

    assert vector.complete_feature_vector is False
    assert vector.operational_model_input_eligible is False
    assert vector.missing_features == (
        MlbSelectedFeatureName.LINEUP_EXPECTED_WOBA_CONTACT_DIFFERENCE,
    )
    assert vector.coverage.home.lineup_players_with_expected_woba_contact == 8


def test_post_start_build_is_retrospective_even_with_pregame_source() -> None:
    vector = DeterministicMlbGameFeatureEngine().evaluate(feature_input(built_at=START))
    assert vector.feature_availability_basis is MlbStatcastObservationBasis.RETROSPECTIVE
    assert vector.operational_model_input_eligible is False


def test_semantic_replay_fingerprint_ignores_build_clock() -> None:
    engine = DeterministicMlbGameFeatureEngine()
    first = engine.evaluate(feature_input())
    second = engine.evaluate(feature_input(built_at=START - timedelta(minutes=5)))
    assert first.input_fingerprint == second.input_fingerprint


def split_policy() -> MlbChronologicalDatasetPolicy:
    return MlbChronologicalDatasetPolicy(
        validation_start=datetime(2025, 7, 1, tzinfo=UTC),
        test_start=datetime(2026, 4, 1, tzinfo=UTC),
        prospective_holdout_start=datetime(2026, 7, 1, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        (datetime(2025, 6, 30, tzinfo=UTC), MlbDatasetSplit.TRAIN),
        (datetime(2025, 7, 1, tzinfo=UTC), MlbDatasetSplit.VALIDATION),
        (datetime(2026, 4, 1, tzinfo=UTC), MlbDatasetSplit.TEST),
        (datetime(2026, 7, 1, tzinfo=UTC), MlbDatasetSplit.PROSPECTIVE_HOLDOUT),
    ],
)
def test_chronological_split_boundaries(when: datetime, expected: MlbDatasetSplit) -> None:
    assert DeterministicMlbDatasetContract.assign_split(when, split_policy()) is expected


def test_labels_only_from_exact_official_final_result() -> None:
    vector = DeterministicMlbGameFeatureEngine().evaluate(
        feature_input(retrieved_at=START + timedelta(hours=1), built_at=START + timedelta(hours=2))
    )
    labeled = DeterministicMlbDatasetContract().label(
        vector,
        MlbOfficialOutcomeInput(
            sports_event_id=EVENT_ID,
            scheduled_start_time=START,
            status="final",
            home_score=5,
            away_score=3,
            source_last_seen_at=START + timedelta(hours=4),
        ),
        split_policy(),
    )
    assert labeled.home_won is True
    assert labeled.split is MlbDatasetSplit.PROSPECTIVE_HOLDOUT
    assert labeled.availability_basis is MlbStatcastObservationBasis.RETROSPECTIVE


def test_rejects_nonfinal_or_tied_outcome() -> None:
    vector = DeterministicMlbGameFeatureEngine().evaluate(feature_input())
    with pytest.raises(ValueError, match="official final"):
        DeterministicMlbDatasetContract().label(
            vector,
            MlbOfficialOutcomeInput(
                sports_event_id=EVENT_ID,
                scheduled_start_time=START,
                status="scheduled",
                source_last_seen_at=START + timedelta(hours=1),
            ),
            split_policy(),
        )


def test_split_policy_requires_strict_aware_boundaries() -> None:
    with pytest.raises(ValidationError):
        MlbChronologicalDatasetPolicy(
            validation_start=datetime(2025, 1, 1),
            test_start=datetime(2025, 2, 1, tzinfo=UTC),
            prospective_holdout_start=datetime(2025, 3, 1, tzinfo=UTC),
        )
