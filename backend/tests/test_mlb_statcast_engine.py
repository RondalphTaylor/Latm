from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from app.domain.mlb_lineups import MlbLineupEntry, MlbProbablePitcher
from app.domain.mlb_statcast import (
    MlbStatcastFeatureInput,
    MlbStatcastFeaturePolicy,
    MlbStatcastObservationBasis,
    MlbStatcastPitchObservation,
    MlbStatcastPlayerRole,
)
from app.services.mlb_statcast.engine import DeterministicMlbStatcastFeatureEngine

EVENT_ID = UUID("2d79504d-e791-5dc8-af53-ee31d1c1ece3")
LINEUP_ID = UUID("9e248fe9-9e77-4e25-8347-ff5a39b5798c")
START = datetime(2026, 8, 22, 17, 35, tzinfo=UTC)


def lineup(prefix: int) -> tuple[MlbLineupEntry, ...]:
    return tuple(
        MlbLineupEntry(
            batting_order=order,
            provider_player_id=str(prefix + order),
            full_name=f"Player {prefix + order}",
            position="CF",
            bat_side="R",
        )
        for order in range(1, 10)
    )


def observation(
    *,
    role: MlbStatcastPlayerRole,
    pitcher_id: str = "677960",
    batter_id: str = "1001",
    pitch_number: int = 1,
    game_date: date = date(2026, 8, 10),
    event: str | None = "single",
    result_type: str = "X",
    release_speed: Decimal | None = Decimal("95"),
    spin_rate: Decimal | None = Decimal("2400"),
    launch_speed: Decimal | None = Decimal("100"),
    launch_speed_angle: int | None = 6,
    expected_woba: Decimal | None = Decimal("0.7"),
    woba_value: Decimal | None = Decimal("0.9"),
    woba_denom: Decimal | None = Decimal("1"),
) -> MlbStatcastPitchObservation:
    return MlbStatcastPitchObservation(
        query_role=role,
        game_pk=823000,
        game_date=game_date,
        game_type="R",
        batter_id=batter_id,
        pitcher_id=pitcher_id,
        at_bat_number=1,
        pitch_number=pitch_number,
        event=event,
        description="hit_into_play" if result_type == "X" else "called_strike",
        result_type=result_type,
        release_speed_mph=release_speed,
        release_spin_rate_rpm=spin_rate,
        launch_speed_mph=launch_speed,
        launch_angle_degrees=Decimal("25") if launch_speed is not None else None,
        launch_speed_angle=launch_speed_angle,
        estimated_woba_on_contact=expected_woba,
        woba_value=woba_value,
        woba_denom=woba_denom,
    )


def feature_input(
    *,
    source_retrieved_at: datetime = datetime(2026, 8, 22, 16, tzinfo=UTC),
    pitcher_rows: tuple[MlbStatcastPitchObservation, ...] | None = None,
    batter_rows: tuple[MlbStatcastPitchObservation, ...] | None = None,
    policy: MlbStatcastFeaturePolicy | None = None,
) -> MlbStatcastFeatureInput:
    return MlbStatcastFeatureInput(
        sports_event_id=EVENT_ID,
        lineup_snapshot_id=LINEUP_ID,
        provider_event_id="823509",
        target_event_date=date(2026, 8, 22),
        scheduled_start_time=START,
        lineup_input_fingerprint="a" * 64,
        home_probable_pitcher=MlbProbablePitcher(
            provider_player_id="677960",
            full_name="Ryan Weathers",
            pitch_hand="L",
        ),
        away_probable_pitcher=MlbProbablePitcher(
            provider_player_id="656302",
            full_name="Dylan Cease",
            pitch_hand="R",
        ),
        home_lineup=lineup(1000),
        away_lineup=lineup(2000),
        pitcher_rows=(
            pitcher_rows
            if pitcher_rows is not None
            else (
                observation(role=MlbStatcastPlayerRole.PITCHER),
                observation(
                    role=MlbStatcastPlayerRole.PITCHER,
                    pitch_number=2,
                    event=None,
                    result_type="S",
                    release_speed=Decimal("97"),
                    spin_rate=Decimal("2600"),
                    launch_speed=None,
                    launch_speed_angle=None,
                    expected_woba=None,
                    woba_value=None,
                    woba_denom=None,
                ),
            )
        ),
        batter_rows=(
            batter_rows
            if batter_rows is not None
            else (observation(role=MlbStatcastPlayerRole.BATTER),)
        ),
        pitcher_response_sha256="b" * 64,
        batter_response_sha256="c" * 64,
        source_retrieved_at=source_retrieved_at,
        policy=policy or MlbStatcastFeaturePolicy(),
    )


def test_engine_produces_exact_player_metrics_and_zero_sample_profiles() -> None:
    snapshot = DeterministicMlbStatcastFeatureEngine().evaluate(feature_input())

    pitcher = snapshot.home_starting_pitcher
    assert pitcher.pitch_count == 2
    assert pitcher.plate_appearance_count == 1
    assert pitcher.average_release_speed_mph == Decimal("96.000000")
    assert pitcher.average_release_spin_rate_rpm == Decimal("2500.000000")
    assert pitcher.average_exit_velocity_mph == Decimal("100.000000")
    assert pitcher.hard_hit_count == 1
    assert pitcher.hard_hit_rate == Decimal("1.000000")
    assert pitcher.barrel_rate == Decimal("1.000000")
    assert pitcher.average_estimated_woba_on_contact == Decimal("0.700000")
    assert pitcher.complete_woba_sample_size == 1
    assert pitcher.incomplete_woba_sample_size == 0
    assert pitcher.observed_woba == Decimal("0.900000")

    batter = snapshot.home_batters[0]
    assert batter.pitch_count == 1
    assert batter.release_speed_sample_size == 0
    assert batter.average_release_speed_mph is None
    assert batter.hard_hit_rate == Decimal("1.000000")
    assert snapshot.away_starting_pitcher.pitch_count == 0
    assert snapshot.away_starting_pitcher.observed_woba is None
    assert snapshot.home_batters[1].pitch_count == 0
    assert snapshot.window_start_date == date(2026, 7, 23)
    assert snapshot.window_end_date == date(2026, 8, 21)
    assert snapshot.observation_basis is MlbStatcastObservationBasis.OPERATIONAL_PREGAME
    assert snapshot.operational_pregame_eligible is True
    assert len(snapshot.source_rows) == 3


def test_retrieval_at_first_pitch_is_retrospective_and_ineligible() -> None:
    snapshot = DeterministicMlbStatcastFeatureEngine().evaluate(
        feature_input(source_retrieved_at=START)
    )

    assert snapshot.observation_basis is MlbStatcastObservationBasis.RETROSPECTIVE
    assert snapshot.operational_pregame_eligible is False


def test_retrieval_time_does_not_change_semantic_identity_but_source_data_does() -> None:
    engine = DeterministicMlbStatcastFeatureEngine()
    first = engine.evaluate(feature_input())
    later = engine.evaluate(
        feature_input(source_retrieved_at=datetime(2026, 8, 22, 16, 30, tzinfo=UTC))
    )
    changed = engine.evaluate(
        feature_input(
            batter_rows=(
                observation(
                    role=MlbStatcastPlayerRole.BATTER,
                    launch_speed=Decimal("94"),
                ),
            )
        )
    )

    assert later.input_fingerprint == first.input_fingerprint
    assert later.source_fingerprint == first.source_fingerprint
    assert changed.source_fingerprint != first.source_fingerprint
    assert changed.input_fingerprint != first.input_fingerprint


def test_policy_change_changes_identity_and_hard_hit_classification() -> None:
    snapshot = DeterministicMlbStatcastFeatureEngine().evaluate(
        feature_input(policy=MlbStatcastFeaturePolicy(hard_hit_threshold_mph=Decimal("101")))
    )

    assert snapshot.home_batters[0].hard_hit_count == 0
    assert (
        snapshot.policy_fingerprint
        != DeterministicMlbStatcastFeatureEngine().evaluate(feature_input()).policy_fingerprint
    )


@pytest.mark.parametrize(
    ("pitcher_rows", "batter_rows", "message"),
    [
        (
            (observation(role=MlbStatcastPlayerRole.PITCHER, game_date=date(2026, 8, 22)),),
            (),
            "outside the exact lookback",
        ),
        (
            (observation(role=MlbStatcastPlayerRole.PITCHER, pitcher_id="999"),),
            (),
            "unrequested player",
        ),
        (
            (),
            (observation(role=MlbStatcastPlayerRole.BATTER, batter_id="999"),),
            "unrequested player",
        ),
    ],
)
def test_leakage_and_unrequested_player_rows_fail_closed(
    pitcher_rows: tuple[MlbStatcastPitchObservation, ...],
    batter_rows: tuple[MlbStatcastPitchObservation, ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        DeterministicMlbStatcastFeatureEngine().evaluate(
            feature_input(pitcher_rows=pitcher_rows, batter_rows=batter_rows)
        )


def test_duplicate_pitch_identity_fails_closed() -> None:
    row = observation(role=MlbStatcastPlayerRole.PITCHER)
    with pytest.raises(ValueError, match="duplicate pitch identity"):
        DeterministicMlbStatcastFeatureEngine().evaluate(
            feature_input(pitcher_rows=(row, row), batter_rows=())
        )


def test_incomplete_official_woba_pair_is_preserved_but_not_aggregated() -> None:
    incomplete = observation(
        role=MlbStatcastPlayerRole.BATTER,
        woba_value=Decimal("0"),
        woba_denom=None,
    )

    snapshot = DeterministicMlbStatcastFeatureEngine().evaluate(
        feature_input(pitcher_rows=(), batter_rows=(incomplete,))
    )

    profile = snapshot.home_batters[0]
    assert snapshot.source_rows[0].woba_value == Decimal("0")
    assert snapshot.source_rows[0].woba_denom is None
    assert profile.complete_woba_sample_size == 0
    assert profile.incomplete_woba_sample_size == 1
    assert profile.woba_numerator == Decimal("0.000000")
    assert profile.woba_denominator == Decimal("0.000000")
    assert profile.observed_woba is None
    assert snapshot.source_manifest["incomplete_woba_row_count"] == 1


def test_expected_woba_contact_excludes_non_contact_source_values() -> None:
    contact = observation(role=MlbStatcastPlayerRole.BATTER)
    walk = observation(
        role=MlbStatcastPlayerRole.BATTER,
        pitch_number=2,
        event="walk",
        result_type="B",
        launch_speed=None,
        launch_speed_angle=None,
        expected_woba=Decimal("0.700"),
        woba_value=Decimal("0.700"),
    )

    snapshot = DeterministicMlbStatcastFeatureEngine().evaluate(
        feature_input(pitcher_rows=(), batter_rows=(contact, walk))
    )

    profile = snapshot.home_batters[0]
    assert profile.estimated_woba_contact_sample_size == 1
    assert profile.average_estimated_woba_on_contact == Decimal("0.700000")
    assert profile.complete_woba_sample_size == 2
