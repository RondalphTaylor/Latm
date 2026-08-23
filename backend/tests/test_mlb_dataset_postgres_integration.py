from __future__ import annotations

import asyncio
import os
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.domain.mlb_modeling import MlbChronologicalDatasetPolicy, MlbFeatureSelectionPolicy
from app.models.markets import Provider
from app.models.mlb import (
    MlbGameFeatureVectorRecord,
    MlbLabeledFeatureExampleRecord,
    MlbLineupSnapshotRecord,
    MlbStatcastFeatureSnapshotRecord,
)
from app.models.sports import SportsEventRecord, TeamRecord
from app.services.mlb_modeling.engine import DeterministicMlbGameFeatureEngine
from app.services.mlb_modeling.repository import MlbGameFeatureRepository
from app.services.mlb_modeling.service import MlbGameFeatureService

EVENT_ID = UUID("71000000-0000-0000-0000-000000000001")
HOME_ID = UUID("71000000-0000-0000-0000-000000000002")
AWAY_ID = UUID("71000000-0000-0000-0000-000000000003")
LINEUP_ID = UUID("71000000-0000-0000-0000-000000000004")
STATCAST_ID = UUID("71000000-0000-0000-0000-000000000005")
VECTOR_ID = UUID("71000000-0000-0000-0000-000000000006")
START = datetime(2020, 8, 22, 17, 35, tzinfo=UTC)


def _coverage() -> dict[str, int]:
    return {
        "lineup_player_count": 9,
        "lineup_players_with_observed_woba": 9,
        "lineup_players_with_expected_woba_contact": 9,
        "lineup_players_with_hard_hit_rate": 9,
        "lineup_players_with_barrel_rate": 9,
        "lineup_plate_appearance_count": 90,
        "lineup_complete_woba_sample_size": 90,
        "lineup_incomplete_woba_sample_size": 0,
        "lineup_expected_woba_contact_sample_size": 90,
        "lineup_exit_velocity_sample_size": 90,
        "lineup_launch_quality_sample_size": 90,
        "starting_pitcher_pitch_count": 100,
        "starting_pitcher_plate_appearance_count": 25,
        "starting_pitcher_complete_woba_sample_size": 25,
        "starting_pitcher_incomplete_woba_sample_size": 0,
        "starting_pitcher_expected_woba_contact_sample_size": 20,
        "starting_pitcher_exit_velocity_sample_size": 20,
        "starting_pitcher_launch_quality_sample_size": 20,
    }


async def _run_integration() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.connect() as connection:
        outer = await connection.begin()
        try:
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as session:
                for name, display in (
                    ("mlb", "MLB Stats API"),
                    ("baseball_savant", "Baseball Savant / Statcast"),
                ):
                    await session.execute(
                        insert(Provider)
                        .values(name=name, display_name=display, is_read_only=True)
                        .on_conflict_do_nothing(index_elements=[Provider.name])
                    )
                session.add_all(
                    [
                        TeamRecord(
                            id=HOME_ID,
                            provider_name="mlb",
                            provider_team_id="dataset-home",
                            league="mlb",
                            abbreviation="HOM",
                            city="Home",
                            name="Home",
                            full_name="Home Club",
                            conference=None,
                            division="Test",
                            raw_data={},
                            first_seen_at=START - timedelta(days=1),
                            last_seen_at=START + timedelta(hours=4),
                        ),
                        TeamRecord(
                            id=AWAY_ID,
                            provider_name="mlb",
                            provider_team_id="dataset-away",
                            league="mlb",
                            abbreviation="AWY",
                            city="Away",
                            name="Away",
                            full_name="Away Club",
                            conference=None,
                            division="Test",
                            raw_data={},
                            first_seen_at=START - timedelta(days=1),
                            last_seen_at=START + timedelta(hours=4),
                        ),
                    ]
                )
                await session.flush()
                session.add(
                    SportsEventRecord(
                        id=EVENT_ID,
                        provider_name="mlb",
                        provider_event_id="dataset-game",
                        league="mlb",
                        season=2020,
                        event_date=START.date(),
                        scheduled_start_time=START,
                        status="final",
                        status_detail="Final",
                        period=9,
                        clock=None,
                        postseason=False,
                        postponed=False,
                        tournament_stage=None,
                        home_team_id=HOME_ID,
                        away_team_id=AWAY_ID,
                        home_score=5,
                        away_score=3,
                        venue="Test Park",
                        raw_data={"gamePk": "dataset-game", "status": "Final"},
                        first_seen_at=START - timedelta(days=1),
                        last_seen_at=START + timedelta(hours=4),
                    )
                )
                await session.flush()
                session.add(
                    MlbLineupSnapshotRecord(
                        id=LINEUP_ID,
                        sports_event_id=EVENT_ID,
                        provider_name="mlb",
                        provider_event_id="dataset-game",
                        home_team_id=HOME_ID,
                        away_team_id=AWAY_ID,
                        scheduled_start_time=START,
                        source_updated_at=START - timedelta(hours=1),
                        retrieved_at=START - timedelta(hours=1),
                        source_abstract_state="Preview",
                        source_detailed_state="Scheduled",
                        observation_phase="pregame",
                        home_probable_pitcher={"provider_player_id": "1"},
                        away_probable_pitcher={"provider_player_id": "2"},
                        home_lineup_state="posted",
                        away_lineup_state="posted",
                        home_lineup=[{"provider_player_id": str(i)} for i in range(10, 19)],
                        away_lineup=[{"provider_player_id": str(i)} for i in range(20, 29)],
                        complete_for_pregame_model=True,
                        input_fingerprint="1" * 64,
                        source_snapshot={"gamePk": "dataset-game"},
                    )
                )
                await session.flush()
                session.add(
                    MlbStatcastFeatureSnapshotRecord(
                        id=STATCAST_ID,
                        sports_event_id=EVENT_ID,
                        lineup_snapshot_id=LINEUP_ID,
                        provider_name="baseball_savant",
                        provider_event_id="dataset-game",
                        target_event_date=START.date(),
                        scheduled_start_time=START,
                        window_start_date=date(2020, 7, 23),
                        window_end_date=date(2020, 8, 21),
                        lookback_days=30,
                        source_retrieved_at=START - timedelta(minutes=30),
                        observation_basis="operational_pregame",
                        operational_pregame_eligible=True,
                        policy_name="mlb_statcast_pregame_features",
                        policy_version="v1",
                        policy_fingerprint="2" * 64,
                        home_starting_pitcher={},
                        away_starting_pitcher={},
                        home_batters=[{} for _ in range(9)],
                        away_batters=[{} for _ in range(9)],
                        source_fingerprint="3" * 64,
                        input_fingerprint="4" * 64,
                        source_manifest={},
                        source_rows=[],
                    )
                )
                await session.flush()
                lineup_metrics = {
                    "observed_woba": "0.320000",
                    "average_expected_woba_on_contact": "0.330000",
                    "hard_hit_rate": "0.400000",
                    "barrel_rate": "0.100000",
                }
                pitcher_metrics = {
                    "observed_woba_allowed": "0.300000",
                    "average_expected_woba_on_contact_allowed": "0.310000",
                    "hard_hit_rate_allowed": "0.380000",
                    "barrel_rate_allowed": "0.090000",
                }
                feature_values = {
                    "lineup_observed_woba_difference": "0.010000",
                    "lineup_expected_woba_contact_difference": "0.010000",
                    "lineup_hard_hit_rate_difference": "0.010000",
                    "lineup_barrel_rate_difference": "0.010000",
                    "starting_pitcher_observed_woba_allowed_difference": "0.010000",
                    "starting_pitcher_expected_woba_contact_allowed_difference": "0.010000",
                    "starting_pitcher_hard_hit_rate_allowed_difference": "0.010000",
                    "starting_pitcher_barrel_rate_allowed_difference": "0.010000",
                }
                session.add(
                    MlbGameFeatureVectorRecord(
                        id=VECTOR_ID,
                        sports_event_id=EVENT_ID,
                        lineup_snapshot_id=LINEUP_ID,
                        statcast_snapshot_id=STATCAST_ID,
                        provider_event_id="dataset-game",
                        target_event_date=START.date(),
                        scheduled_start_time=START,
                        home_team_id=HOME_ID,
                        away_team_id=AWAY_ID,
                        source_retrieved_at=START - timedelta(minutes=30),
                        source_observation_basis="operational_pregame",
                        built_at=START - timedelta(minutes=10),
                        feature_availability_basis="operational_pregame",
                        policy_name="mlb_pregame_feature_selection",
                        policy_version="v1",
                        model_candidate_name="mlb_pregame_regularized_logistic",
                        policy_fingerprint="5" * 64,
                        source_metrics={
                            "home_lineup": lineup_metrics,
                            "away_lineup": lineup_metrics,
                            "home_starting_pitcher": pitcher_metrics,
                            "away_starting_pitcher": pitcher_metrics,
                        },
                        coverage={"home": _coverage(), "away": _coverage()},
                        feature_values=feature_values,
                        missing_features=[],
                        complete_feature_vector=True,
                        operational_model_input_eligible=True,
                        research_only=True,
                        probability_generated=False,
                        automatic_trading_eligible=False,
                        source_fingerprint="3" * 64,
                        input_fingerprint="6" * 64,
                    )
                )
                await session.commit()

                repository = MlbGameFeatureRepository(session)
                service = MlbGameFeatureService(
                    repository=repository,
                    engine=DeterministicMlbGameFeatureEngine(),
                    policy=MlbFeatureSelectionPolicy(),
                )
                split_policy = MlbChronologicalDatasetPolicy(
                    validation_start=datetime(2019, 1, 1, tzinfo=UTC),
                    test_start=datetime(2020, 1, 1, tzinfo=UTC),
                    prospective_holdout_start=datetime(2021, 1, 1, tzinfo=UTC),
                )
                first = await service.label(vector_id=VECTOR_ID, split_policy=split_policy)
                replay = await service.label(vector_id=VECTOR_ID, split_policy=split_policy)
                inventory = await service.inventory(first.example.split_policy_fingerprint)

                assert first.created is True
                assert replay.created is False
                assert replay.example.id == first.example.id
                assert first.example.home_won is True
                assert first.example.split == "test"
                assert inventory.example_count == 1
                assert inventory.operational_example_count == 1
                assert inventory.retrospective_example_count == 0

                with pytest.raises(IntegrityError):
                    async with session.begin_nested():
                        await session.execute(
                            update(MlbLabeledFeatureExampleRecord)
                            .where(MlbLabeledFeatureExampleRecord.id == first.example.id)
                            .values(automatic_trading_eligible=True)
                        )
                        await session.flush()
        finally:
            await outer.rollback()
    await engine.dispose()


@pytest.mark.integration
def test_mlb_dataset_label_replay_inventory_and_safety_constraints() -> None:
    if os.environ.get("RUN_DATABASE_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_DATABASE_INTEGRATION_TESTS=1 against a migrated test database")
    asyncio.run(_run_integration())
