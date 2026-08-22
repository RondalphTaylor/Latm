from __future__ import annotations

import asyncio
import os
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.domain.mlb_lineups import (
    MlbLineupEntry,
    MlbLineupSnapshot,
    MlbLineupState,
    MlbObservationPhase,
    MlbProbablePitcher,
)
from app.models.markets import Provider
from app.models.mlb import MlbLineupSnapshotRecord
from app.models.sports import SportsEventRecord, TeamRecord
from app.services.mlb_lineups.repository import (
    MlbLineupRepository,
    MlbLineupSourceConflictError,
)

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION_TESTS") != "1",
    reason="set RUN_DATABASE_INTEGRATION_TESTS=1 against a migrated test database",
)

EVENT_ID = UUID("c3b93fa9-5c7c-4341-a3a1-4b589c6eea2c")
HOME_ID = UUID("e8ff2fe1-ad32-46dd-8ec4-e87d5aac7cd6")
AWAY_ID = UUID("8139d52e-7160-42bc-ab0a-6d4fca046c8b")
START = datetime(2030, 8, 22, 17, 35, tzinfo=UTC)
OBSERVED = datetime(2030, 8, 22, 16, tzinfo=UTC)


def team_record(team_id: UUID, provider_id: str, abbreviation: str) -> TeamRecord:
    return TeamRecord(
        id=team_id,
        provider_name="mlb",
        provider_team_id=provider_id,
        league="mlb",
        abbreviation=abbreviation,
        city=abbreviation,
        name=abbreviation,
        full_name=abbreviation,
        conference="Major League Baseball",
        division="Test",
        raw_data={},
        first_seen_at=OBSERVED,
        last_seen_at=OBSERVED,
    )


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


def snapshot(*, home_provider_team_id: str = "phase-lineup-home") -> MlbLineupSnapshot:
    return MlbLineupSnapshot(
        provider_name="mlb",
        provider_event_id="phase-mlb-lineup-event",
        home_provider_team_id=home_provider_team_id,
        away_provider_team_id="phase-lineup-away",
        scheduled_start_time=START,
        source_updated_at=OBSERVED,
        retrieved_at=OBSERVED,
        source_abstract_state="Preview",
        source_detailed_state="Scheduled",
        observation_phase=MlbObservationPhase.PREGAME,
        home_probable_pitcher=MlbProbablePitcher(
            provider_player_id="10", full_name="Home Pitcher", pitch_hand="L"
        ),
        away_probable_pitcher=MlbProbablePitcher(
            provider_player_id="20", full_name="Away Pitcher", pitch_hand="R"
        ),
        home_lineup_state=MlbLineupState.POSTED,
        away_lineup_state=MlbLineupState.POSTED,
        home_lineup=lineup(1000),
        away_lineup=lineup(2000),
        complete_for_pregame_model=True,
        input_fingerprint="a" * 64,
        source_snapshot={"provider": "mlb", "gamePk": "phase-mlb-lineup-event"},
    )


async def _run_integration() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.connect() as connection:
        outer_transaction = await connection.begin()
        try:
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as session:
                await session.execute(
                    insert(Provider)
                    .values(name="mlb", display_name="MLB Stats API", is_read_only=True)
                    .on_conflict_do_nothing(index_elements=[Provider.name])
                )
                session.add_all(
                    [
                        team_record(HOME_ID, "phase-lineup-home", "NYY"),
                        team_record(AWAY_ID, "phase-lineup-away", "TOR"),
                        SportsEventRecord(
                            id=EVENT_ID,
                            provider_name="mlb",
                            provider_event_id="phase-mlb-lineup-event",
                            league="mlb",
                            season=2030,
                            event_date=date(2030, 8, 22),
                            scheduled_start_time=START,
                            status="scheduled",
                            status_detail="Scheduled",
                            period=0,
                            clock=None,
                            postseason=False,
                            postponed=False,
                            tournament_stage="Regular Season",
                            home_team_id=HOME_ID,
                            away_team_id=AWAY_ID,
                            home_score=None,
                            away_score=None,
                            venue="Test Park",
                            raw_data={},
                            first_seen_at=OBSERVED,
                            last_seen_at=OBSERVED,
                        ),
                    ]
                )
                await session.flush()

                repository = MlbLineupRepository(session)
                created_record, created = await repository.persist_snapshot(
                    event_id=EVENT_ID,
                    snapshot=snapshot(),
                )
                replay_record, replay_created = await repository.persist_snapshot(
                    event_id=EVENT_ID,
                    snapshot=snapshot(),
                )
                records = await repository.list_snapshots(
                    event_id=EVENT_ID,
                    observation_phase="pregame",
                    complete_for_pregame_model=True,
                    limit=10,
                    offset=0,
                )

                assert created is True
                assert replay_created is False
                assert replay_record.id == created_record.id
                assert len(records) == 1
                assert records[0].home_lineup_state == "posted"
                assert records[0].complete_for_pregame_model is True

                with pytest.raises(MlbLineupSourceConflictError, match="home-team identity"):
                    await repository.persist_snapshot(
                        event_id=EVENT_ID,
                        snapshot=snapshot(home_provider_team_id="999"),
                    )

                invalid = snapshot().model_copy(
                    update={"input_fingerprint": "b" * 64, "complete_for_pregame_model": False}
                )
                with pytest.raises(IntegrityError):
                    async with session.begin_nested():
                        session.add(
                            MlbLineupSnapshotRecord(
                                id=UUID("15324f92-0a75-4875-8a62-ee589bf6ad6a"),
                                sports_event_id=EVENT_ID,
                                provider_name="mlb",
                                provider_event_id=invalid.provider_event_id,
                                home_team_id=HOME_ID,
                                away_team_id=AWAY_ID,
                                scheduled_start_time=invalid.scheduled_start_time,
                                source_updated_at=invalid.source_updated_at,
                                retrieved_at=invalid.retrieved_at,
                                source_abstract_state=invalid.source_abstract_state,
                                source_detailed_state=invalid.source_detailed_state,
                                observation_phase=invalid.observation_phase.value,
                                home_probable_pitcher={"provider_player_id": "10"},
                                away_probable_pitcher={"provider_player_id": "20"},
                                home_lineup_state="posted",
                                away_lineup_state="posted",
                                home_lineup=[
                                    entry.model_dump(mode="json") for entry in invalid.home_lineup
                                ],
                                away_lineup=[
                                    entry.model_dump(mode="json") for entry in invalid.away_lineup
                                ],
                                complete_for_pregame_model=False,
                                input_fingerprint=invalid.input_fingerprint,
                                source_snapshot=invalid.source_snapshot,
                            )
                        )
                        await session.flush()
        finally:
            await outer_transaction.rollback()
    await engine.dispose()


def test_mlb_lineup_repository_replays_and_reconciles_official_identity() -> None:
    asyncio.run(_run_integration())
