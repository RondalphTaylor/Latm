from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal

from app.domain.mlb_lineups import MlbLineupEntry, MlbProbablePitcher
from app.domain.mlb_statcast import (
    MlbStatcastFeatureInput,
    MlbStatcastFeaturePolicy,
    MlbStatcastFeatureSnapshot,
    MlbStatcastObservationBasis,
    MlbStatcastPitchObservation,
    MlbStatcastPlayerFeatures,
    MlbStatcastPlayerRole,
    quantize_statcast_metric,
)

_AGGREGATION_SPEC = {
    "name": "mlb_statcast_features_v1",
    "rounding": "decimal_half_even_0.000001",
    "pitch_identity": (
        "query_role",
        "game_date",
        "game_pk",
        "at_bat_number",
        "pitch_number",
        "pitcher_id",
        "batter_id",
    ),
    "plate_appearance": "event_is_not_null",
    "batted_ball_event": "result_type_equals_X",
    "barrel": "launch_speed_angle_equals_6",
    "expected_woba_contact": "result_type_X_and_launch_speed_present",
    "observed_woba": "complete_value_and_denom_pairs_only",
}


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def mlb_statcast_policy_fingerprint(policy: MlbStatcastFeaturePolicy) -> str:
    """Hash the exact rolling-window and aggregation policy."""
    return _canonical_hash(
        {
            "configuration": policy.model_dump(mode="json"),
            "aggregation_spec": _AGGREGATION_SPEC,
        }
    )


def _mean(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    return quantize_statcast_metric(sum(values, Decimal("0")) / Decimal(len(values)))


def _rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator == 0:
        return None
    return quantize_statcast_metric(Decimal(numerator) / Decimal(denominator))


def _profile(
    *,
    role: MlbStatcastPlayerRole,
    provider_player_id: str,
    full_name: str,
    rows: Sequence[MlbStatcastPitchObservation],
    hard_hit_threshold_mph: Decimal,
) -> MlbStatcastPlayerFeatures:
    game_dates = [row.game_date for row in rows]
    release_speeds = (
        [row.release_speed_mph for row in rows if row.release_speed_mph is not None]
        if role is MlbStatcastPlayerRole.PITCHER
        else []
    )
    spin_rates = (
        [row.release_spin_rate_rpm for row in rows if row.release_spin_rate_rpm is not None]
        if role is MlbStatcastPlayerRole.PITCHER
        else []
    )
    exit_velocities = [row.launch_speed_mph for row in rows if row.launch_speed_mph is not None]
    launch_qualities = [
        row.launch_speed_angle for row in rows if row.launch_speed_angle is not None
    ]
    expected_woba = [
        row.estimated_woba_on_contact
        for row in rows
        if row.result_type == "X"
        and row.launch_speed_mph is not None
        and row.estimated_woba_on_contact is not None
    ]
    woba_rows = [row for row in rows if row.woba_value is not None and row.woba_denom is not None]
    incomplete_woba_rows = [
        row for row in rows if (row.woba_value is None) != (row.woba_denom is None)
    ]
    woba_numerator = quantize_statcast_metric(
        sum((row.woba_value for row in woba_rows if row.woba_value is not None), Decimal("0"))
    )
    woba_denominator = quantize_statcast_metric(
        sum((row.woba_denom for row in woba_rows if row.woba_denom is not None), Decimal("0"))
    )
    return MlbStatcastPlayerFeatures(
        role=role,
        provider_player_id=provider_player_id,
        full_name=full_name,
        pitch_count=len(rows),
        plate_appearance_count=sum(row.event is not None for row in rows),
        batted_ball_event_count=sum(row.result_type == "X" for row in rows),
        source_game_count=len({row.game_pk for row in rows}),
        first_game_date=min(game_dates) if game_dates else None,
        last_game_date=max(game_dates) if game_dates else None,
        release_speed_sample_size=len(release_speeds),
        average_release_speed_mph=_mean(release_speeds),
        spin_rate_sample_size=len(spin_rates),
        average_release_spin_rate_rpm=_mean(spin_rates),
        exit_velocity_sample_size=len(exit_velocities),
        average_exit_velocity_mph=_mean(exit_velocities),
        hard_hit_count=sum(value >= hard_hit_threshold_mph for value in exit_velocities),
        hard_hit_rate=_rate(
            sum(value >= hard_hit_threshold_mph for value in exit_velocities),
            len(exit_velocities),
        ),
        launch_quality_sample_size=len(launch_qualities),
        barrel_count=sum(value == 6 for value in launch_qualities),
        barrel_rate=_rate(sum(value == 6 for value in launch_qualities), len(launch_qualities)),
        estimated_woba_contact_sample_size=len(expected_woba),
        average_estimated_woba_on_contact=_mean(expected_woba),
        complete_woba_sample_size=len(woba_rows),
        incomplete_woba_sample_size=len(incomplete_woba_rows),
        woba_numerator=woba_numerator,
        woba_denominator=woba_denominator,
        observed_woba=(
            None
            if woba_denominator == 0
            else quantize_statcast_metric(woba_numerator / woba_denominator)
        ),
    )


def _row_key(row: MlbStatcastPitchObservation) -> tuple[object, ...]:
    return (
        row.query_role.value,
        row.game_date,
        row.game_pk,
        row.at_bat_number,
        row.pitch_number,
        row.pitcher_id,
        row.batter_id,
    )


class DeterministicMlbStatcastFeatureEngine:
    """Aggregate exact official pitch rows into leakage-safe player features."""

    def evaluate(self, source: MlbStatcastFeatureInput) -> MlbStatcastFeatureSnapshot:
        """Build one deterministic event snapshot without generating a win probability."""
        policy = source.policy
        window_end_date = source.target_event_date - timedelta(days=1)
        window_start_date = source.target_event_date - timedelta(days=policy.lookback_days)
        pitcher_ids = {
            source.home_probable_pitcher.provider_player_id,
            source.away_probable_pitcher.provider_player_id,
        }
        batter_ids = {
            entry.provider_player_id for entry in (*source.home_lineup, *source.away_lineup)
        }
        if len(pitcher_ids) != 2:
            raise ValueError("Statcast snapshots require two distinct probable pitchers")
        if len(batter_ids) != 18:
            raise ValueError("Statcast snapshots require 18 distinct lineup batters")

        seen: set[tuple[object, ...]] = set()
        for row in (*source.pitcher_rows, *source.batter_rows):
            key = _row_key(row)
            if key in seen:
                raise ValueError("Statcast source rows contain a duplicate pitch identity")
            seen.add(key)
            if not window_start_date <= row.game_date <= window_end_date:
                raise ValueError("Statcast source row falls outside the exact lookback window")
            if row.game_type not in policy.allowed_game_types:
                raise ValueError("Statcast source row has an unsupported game type")
            selected_id = (
                row.pitcher_id if row.query_role is MlbStatcastPlayerRole.PITCHER else row.batter_id
            )
            expected_ids = (
                pitcher_ids if row.query_role is MlbStatcastPlayerRole.PITCHER else batter_ids
            )
            if selected_id not in expected_ids:
                raise ValueError("Statcast source returned an unrequested player identity")

        pitcher_rows_by_id = {
            player_id: [row for row in source.pitcher_rows if row.pitcher_id == player_id]
            for player_id in pitcher_ids
        }
        batter_rows_by_id = {
            player_id: [row for row in source.batter_rows if row.batter_id == player_id]
            for player_id in batter_ids
        }

        def pitcher_profile(person: MlbProbablePitcher) -> MlbStatcastPlayerFeatures:
            return _profile(
                role=MlbStatcastPlayerRole.PITCHER,
                provider_player_id=person.provider_player_id,
                full_name=person.full_name,
                rows=pitcher_rows_by_id[person.provider_player_id],
                hard_hit_threshold_mph=policy.hard_hit_threshold_mph,
            )

        def batter_profiles(
            lineup: tuple[MlbLineupEntry, ...],
        ) -> tuple[MlbStatcastPlayerFeatures, ...]:
            return tuple(
                _profile(
                    role=MlbStatcastPlayerRole.BATTER,
                    provider_player_id=entry.provider_player_id,
                    full_name=entry.full_name,
                    rows=batter_rows_by_id[entry.provider_player_id],
                    hard_hit_threshold_mph=policy.hard_hit_threshold_mph,
                )
                for entry in lineup
            )

        sorted_rows = tuple(sorted((*source.pitcher_rows, *source.batter_rows), key=_row_key))
        source_fingerprint = _canonical_hash([row.model_dump(mode="json") for row in sorted_rows])
        policy_fingerprint = mlb_statcast_policy_fingerprint(policy)
        input_fingerprint = _canonical_hash(
            {
                "sports_event_id": str(source.sports_event_id),
                "lineup_snapshot_id": str(source.lineup_snapshot_id),
                "provider_event_id": source.provider_event_id,
                "target_event_date": source.target_event_date.isoformat(),
                "scheduled_start_time": source.scheduled_start_time.isoformat(),
                "lineup_input_fingerprint": source.lineup_input_fingerprint,
                "window_start_date": window_start_date.isoformat(),
                "window_end_date": window_end_date.isoformat(),
                "policy_fingerprint": policy_fingerprint,
                "source_fingerprint": source_fingerprint,
            }
        )
        observation_basis = (
            MlbStatcastObservationBasis.OPERATIONAL_PREGAME
            if source.source_retrieved_at < source.scheduled_start_time
            else MlbStatcastObservationBasis.RETROSPECTIVE
        )
        manifest = {
            "source": "official_baseball_savant_statcast_search_csv",
            "window_start_date": window_start_date.isoformat(),
            "window_end_date": window_end_date.isoformat(),
            "pitcher_ids": sorted(pitcher_ids),
            "batter_ids": sorted(batter_ids),
            "pitcher_row_count": len(source.pitcher_rows),
            "batter_row_count": len(source.batter_rows),
            "incomplete_woba_row_count": sum(
                (row.woba_value is None) != (row.woba_denom is None) for row in sorted_rows
            ),
            "pitcher_response_sha256": source.pitcher_response_sha256,
            "batter_response_sha256": source.batter_response_sha256,
            "source_fingerprint": source_fingerprint,
            "retrieved_at": source.source_retrieved_at.isoformat(),
        }
        return MlbStatcastFeatureSnapshot(
            sports_event_id=source.sports_event_id,
            lineup_snapshot_id=source.lineup_snapshot_id,
            provider_name="baseball_savant",
            provider_event_id=source.provider_event_id,
            target_event_date=source.target_event_date,
            scheduled_start_time=source.scheduled_start_time,
            window_start_date=window_start_date,
            window_end_date=window_end_date,
            lookback_days=policy.lookback_days,
            source_retrieved_at=source.source_retrieved_at,
            observation_basis=observation_basis,
            operational_pregame_eligible=(
                observation_basis is MlbStatcastObservationBasis.OPERATIONAL_PREGAME
            ),
            policy_name=policy.policy_name,
            policy_version=policy.policy_version,
            policy_fingerprint=policy_fingerprint,
            home_starting_pitcher=pitcher_profile(source.home_probable_pitcher),
            away_starting_pitcher=pitcher_profile(source.away_probable_pitcher),
            home_batters=batter_profiles(source.home_lineup),
            away_batters=batter_profiles(source.away_lineup),
            source_fingerprint=source_fingerprint,
            input_fingerprint=input_fingerprint,
            source_manifest=manifest,
            source_rows=sorted_rows,
        )
