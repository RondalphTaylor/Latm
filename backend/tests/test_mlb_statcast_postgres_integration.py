from __future__ import annotations

import asyncio
import os
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.domain.mlb_statcast import MlbStatcastFeaturePolicy, MlbStatcastPlayerRole
from app.models.markets import Provider
from app.models.mlb import MlbLineupSnapshotRecord, MlbStatcastFeatureSnapshotRecord
from app.models.sports import SportsEventRecord, TeamRecord
from app.providers.sports.savant import BaseballSavantQueryBatch
from app.services.mlb_statcast.engine import DeterministicMlbStatcastFeatureEngine
from app.services.mlb_statcast.repository import MlbStatcastRepository
from app.services.mlb_statcast.service import MlbStatcastService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION_TESTS") != "1",
    reason="set RUN_DATABASE_INTEGRATION_TESTS=1 against a migrated test database",
)

EVENT_ID = UUID("5574051a-d9a9-40f3-b13f-9f8c1c06ed51")
OTHER_EVENT_ID = UUID("9b7e802a-f3a2-49d6-8c6d-d66100c14421")
LINEUP_ID = UUID("b1793bf5-9c83-4ed5-a3bc-d39575d3eaea")
RETROSPECTIVE_LINEUP_ID = UUID("b1793bf5-9c83-4ed5-a3bc-d39575d3eaeb")
HOME_ID = UUID("68aa4703-01dd-4a87-829e-9cf210b1254e")
AWAY_ID = UUID("0d207c65-05ea-4526-83b2-b2510169fd28")
START = datetime(2030, 8, 22, 17, 35, tzinfo=UTC)
OBSERVED = datetime(2030, 8, 22, 16, tzinfo=UTC)


def _team(team_id: UUID, provider_id: str, abbreviation: str) -> TeamRecord:
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


def _event(event_id: UUID, provider_event_id: str) -> SportsEventRecord:
    return SportsEventRecord(
        id=event_id,
        provider_name="mlb",
        provider_event_id=provider_event_id,
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
    )


def _lineup_entries(prefix: int) -> list[dict[str, object]]:
    return [
        {
            "batting_order": order,
            "provider_player_id": str(prefix + order),
            "full_name": f"Player {prefix + order}",
            "position": "CF",
            "bat_side": "R",
        }
        for order in range(1, 10)
    ]


class EmptySavantProvider:
    """Deterministic read-only provider fixture for service/repository integration."""

    def __init__(self, retrieved_at: datetime = OBSERVED) -> None:
        self.calls: list[tuple[MlbStatcastPlayerRole, tuple[str, ...], date, date]] = []
        self.retrieved_at = retrieved_at

    async def get_player_rows(
        self,
        *,
        role: MlbStatcastPlayerRole,
        player_ids: tuple[str, ...],
        window_start_date: date,
        window_end_date: date,
    ) -> BaseballSavantQueryBatch:
        self.calls.append((role, player_ids, window_start_date, window_end_date))
        return BaseballSavantQueryBatch(
            role=role,
            requested_player_ids=tuple(sorted(player_ids, key=int)),
            window_start_date=window_start_date,
            window_end_date=window_end_date,
            rows=(),
            retrieved_at=self.retrieved_at,
            response_sha256=("b" if role is MlbStatcastPlayerRole.PITCHER else "c") * 64,
        )


def _invalid_record(
    source: MlbStatcastFeatureSnapshotRecord,
    *,
    sports_event_id: UUID = EVENT_ID,
    input_fingerprint: str,
    observation_basis: str = "operational_pregame",
    operational_pregame_eligible: bool = True,
) -> MlbStatcastFeatureSnapshotRecord:
    return MlbStatcastFeatureSnapshotRecord(
        id=uuid4(),
        sports_event_id=sports_event_id,
        lineup_snapshot_id=source.lineup_snapshot_id,
        provider_name=source.provider_name,
        provider_event_id=source.provider_event_id,
        target_event_date=source.target_event_date,
        scheduled_start_time=source.scheduled_start_time,
        window_start_date=source.window_start_date,
        window_end_date=source.window_end_date,
        lookback_days=source.lookback_days,
        source_retrieved_at=source.source_retrieved_at,
        observation_basis=observation_basis,
        operational_pregame_eligible=operational_pregame_eligible,
        policy_name=source.policy_name,
        policy_version=source.policy_version,
        policy_fingerprint=source.policy_fingerprint,
        home_starting_pitcher=source.home_starting_pitcher,
        away_starting_pitcher=source.away_starting_pitcher,
        home_batters=source.home_batters,
        away_batters=source.away_batters,
        source_fingerprint=source.source_fingerprint,
        input_fingerprint=input_fingerprint,
        source_manifest=source.source_manifest,
        source_rows=source.source_rows,
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
                        _team(HOME_ID, "statcast-home", "HOM"),
                        _team(AWAY_ID, "statcast-away", "AWY"),
                        _event(EVENT_ID, "statcast-event"),
                        _event(OTHER_EVENT_ID, "statcast-other-event"),
                    ]
                )
                await session.flush()
                session.add(
                    MlbLineupSnapshotRecord(
                        id=LINEUP_ID,
                        sports_event_id=EVENT_ID,
                        provider_name="mlb",
                        provider_event_id="statcast-event",
                        home_team_id=HOME_ID,
                        away_team_id=AWAY_ID,
                        scheduled_start_time=START,
                        source_updated_at=OBSERVED,
                        retrieved_at=OBSERVED,
                        source_abstract_state="Preview",
                        source_detailed_state="Scheduled",
                        observation_phase="pregame",
                        home_probable_pitcher={
                            "provider_player_id": "10",
                            "full_name": "Home Pitcher",
                            "pitch_hand": "L",
                        },
                        away_probable_pitcher={
                            "provider_player_id": "20",
                            "full_name": "Away Pitcher",
                            "pitch_hand": "R",
                        },
                        home_lineup_state="posted",
                        away_lineup_state="posted",
                        home_lineup=_lineup_entries(1000),
                        away_lineup=_lineup_entries(2000),
                        complete_for_pregame_model=True,
                        input_fingerprint="a" * 64,
                        source_snapshot={"provider": "mlb", "gamePk": "statcast-event"},
                    )
                )
                session.add(
                    MlbLineupSnapshotRecord(
                        id=RETROSPECTIVE_LINEUP_ID,
                        sports_event_id=EVENT_ID,
                        provider_name="mlb",
                        provider_event_id="statcast-event",
                        home_team_id=HOME_ID,
                        away_team_id=AWAY_ID,
                        scheduled_start_time=START,
                        source_updated_at=START + timedelta(hours=3),
                        retrieved_at=START + timedelta(hours=4),
                        source_abstract_state="Final",
                        source_detailed_state="Final",
                        observation_phase="postgame",
                        home_probable_pitcher={
                            "provider_player_id": "10",
                            "full_name": "Home Pitcher",
                            "pitch_hand": "L",
                        },
                        away_probable_pitcher={
                            "provider_player_id": "20",
                            "full_name": "Away Pitcher",
                            "pitch_hand": "R",
                        },
                        home_lineup_state="posted",
                        away_lineup_state="posted",
                        home_lineup=_lineup_entries(1000),
                        away_lineup=_lineup_entries(2000),
                        complete_for_pregame_model=False,
                        input_fingerprint="f" * 64,
                        source_snapshot={"provider": "mlb", "gamePk": "statcast-event"},
                    )
                )
                await session.commit()

                repository = MlbStatcastRepository(session)
                provider = EmptySavantProvider()
                service = MlbStatcastService(
                    provider=provider,
                    repository=repository,
                    engine=DeterministicMlbStatcastFeatureEngine(),
                    policy=MlbStatcastFeaturePolicy(),
                )
                first = await service.ingest(event_id=EVENT_ID, lineup_snapshot_id=LINEUP_ID)
                replay = await service.ingest(event_id=EVENT_ID, lineup_snapshot_id=LINEUP_ID)
                records = await repository.list_snapshots(
                    event_id=EVENT_ID,
                    lineup_snapshot_id=LINEUP_ID,
                    operational_pregame_eligible=True,
                    limit=10,
                    offset=0,
                )

                assert first.created is True
                assert replay.created is False
                assert replay.snapshot.id == first.snapshot.id
                assert len(records) == 1
                assert len(provider.calls) == 4
                assert provider.calls[0] == (
                    MlbStatcastPlayerRole.PITCHER,
                    ("10", "20"),
                    date(2030, 7, 23),
                    date(2030, 8, 21),
                )
                assert len(provider.calls[1][1]) == 18
                assert records[0].source_rows == []
                assert records[0].observation_basis == "operational_pregame"
                assert records[0].home_starting_pitcher["pitch_count"] == 0

                retrospective_service = MlbStatcastService(
                    provider=EmptySavantProvider(START + timedelta(hours=4)),
                    repository=repository,
                    engine=DeterministicMlbStatcastFeatureEngine(),
                    policy=MlbStatcastFeaturePolicy(),
                )
                retrospective = await retrospective_service.ingest(
                    event_id=EVENT_ID,
                    lineup_snapshot_id=RETROSPECTIVE_LINEUP_ID,
                )
                assert retrospective.snapshot.observation_basis == "retrospective"
                assert retrospective.snapshot.operational_pregame_eligible is False

                with pytest.raises(IntegrityError):
                    async with session.begin_nested():
                        session.add(
                            _invalid_record(
                                first.snapshot,
                                input_fingerprint="d" * 64,
                                observation_basis="retrospective",
                                operational_pregame_eligible=False,
                            )
                        )
                        await session.flush()

                with pytest.raises(IntegrityError):
                    async with session.begin_nested():
                        session.add(
                            _invalid_record(
                                first.snapshot,
                                sports_event_id=OTHER_EVENT_ID,
                                input_fingerprint="e" * 64,
                            )
                        )
                        await session.flush()
        finally:
            await outer_transaction.rollback()
    await engine.dispose()


def test_statcast_service_replays_and_database_enforces_lineage() -> None:
    asyncio.run(_run_integration())
