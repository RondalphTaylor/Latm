from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest

from app.models.mlb import (
    MlbGameFeatureVectorRecord,
    MlbLabeledFeatureExampleRecord,
    MlbLineupSnapshotRecord,
    MlbStatcastFeatureSnapshotRecord,
)
from app.services.mlb_collection import (
    MlbProspectiveCollectionService,
    MlbRetrospectiveBackfillService,
)
from app.services.mlb_lineups.service import MlbLineupIngestionResult, MlbLineupService
from app.services.mlb_modeling.service import (
    MlbDatasetLabelResult,
    MlbGameFeatureBuildResult,
    MlbGameFeatureService,
)
from app.services.mlb_statcast.service import MlbStatcastIngestionResult, MlbStatcastService
from app.services.sports.ingestion import EventIngestionResult, SportsIngestionService
from app.services.sports.repository import SportsRepository

NOW = datetime(2026, 8, 22, 12, tzinfo=UTC)
FUTURE_ID = UUID("81000000-0000-0000-0000-000000000001")
INCOMPLETE_ID = UUID("81000000-0000-0000-0000-000000000002")
PAST_ID = UUID("81000000-0000-0000-0000-000000000003")
FINAL_ID = UUID("81000000-0000-0000-0000-000000000004")


@dataclass(frozen=True)
class FakeEvent:
    id: UUID
    provider_event_id: str
    scheduled_start_time: datetime
    status: str = "scheduled"
    postponed: bool = False
    raw_data: dict[str, object] = field(default_factory=lambda: {"gameType": "R"})


class FakeSportsIngestion:
    async def ingest_events(self, *, start_date: date, end_date: date) -> EventIngestionResult:
        return EventIngestionResult(
            provider="mlb",
            start_date=start_date,
            end_date=end_date,
            fetched=4,
            teams_persisted=2,
            events_persisted=4,
            scheduled=3,
            in_progress=0,
            final=1,
            postponed=0,
            canceled=0,
            unknown=0,
        )


class FakeSportsRepository:
    async def list_events(self, **_: object) -> list[FakeEvent]:
        return [
            FakeEvent(FUTURE_ID, "future", NOW + timedelta(hours=2)),
            FakeEvent(INCOMPLETE_ID, "incomplete", NOW + timedelta(hours=3)),
            FakeEvent(PAST_ID, "past", NOW),
            FakeEvent(FINAL_ID, "final", NOW - timedelta(hours=4), status="final"),
        ]


class FakeLineupService:
    calls: list[UUID]

    def __init__(self) -> None:
        self.calls = []

    async def ingest(self, event_id: UUID) -> MlbLineupIngestionResult:
        self.calls.append(event_id)
        snapshot = cast(
            MlbLineupSnapshotRecord,
            SimpleNamespace(
                id=UUID(int=event_id.int + 100),
                complete_for_pregame_model=event_id == FUTURE_ID,
            ),
        )
        return MlbLineupIngestionResult(created=True, snapshot=snapshot)


class FakeStatcastService:
    calls: list[tuple[UUID, UUID]]

    def __init__(self) -> None:
        self.calls = []

    async def ingest(
        self, *, event_id: UUID, lineup_snapshot_id: UUID
    ) -> MlbStatcastIngestionResult:
        self.calls.append((event_id, lineup_snapshot_id))
        snapshot = cast(
            MlbStatcastFeatureSnapshotRecord,
            SimpleNamespace(id=UUID(int=event_id.int + 200)),
        )
        return MlbStatcastIngestionResult(created=True, snapshot=snapshot)


class FakeFeatureService:
    calls: list[UUID]

    def __init__(self) -> None:
        self.calls = []

    async def build(self, statcast_snapshot_id: UUID) -> MlbGameFeatureBuildResult:
        self.calls.append(statcast_snapshot_id)
        vector = cast(
            MlbGameFeatureVectorRecord,
            SimpleNamespace(
                id=UUID(int=statcast_snapshot_id.int + 300),
                operational_model_input_eligible=True,
            ),
        )
        return MlbGameFeatureBuildResult(created=True, vector=vector)


async def _run_collection() -> None:
    lineup = FakeLineupService()
    statcast = FakeStatcastService()
    features = FakeFeatureService()
    service = MlbProspectiveCollectionService(
        sports_ingestion=cast(SportsIngestionService, FakeSportsIngestion()),
        sports_repository=cast(SportsRepository, FakeSportsRepository()),
        lineup_service=cast(MlbLineupService, lineup),
        statcast_service=cast(MlbStatcastService, statcast),
        feature_service=cast(MlbGameFeatureService, features),
        clock=lambda: NOW,
    )

    result = await service.run(start_date=NOW.date(), end_date=NOW.date(), limit=25, offset=0)

    assert lineup.calls == [FUTURE_ID, INCOMPLETE_ID]
    assert len(statcast.calls) == 1
    assert len(features.calls) == 1
    assert result.events_refreshed == 4
    assert result.examined == 4
    assert result.lineup_observed == 2
    assert result.complete_lineups == 1
    assert result.feature_vectors_built == 1
    assert result.operational_feature_vectors == 1
    assert result.result_counts == {
        "first_pitch_reached": 1,
        "lineup_incomplete": 1,
        "not_scheduled": 1,
        "operational_feature_ready": 1,
    }
    assert result.probability_generated is False
    assert result.automatic_trading_eligible is False


def test_collection_advances_only_upcoming_complete_lineups() -> None:
    asyncio.run(_run_collection())


async def _reject_range() -> None:
    service = MlbProspectiveCollectionService(
        sports_ingestion=cast(SportsIngestionService, FakeSportsIngestion()),
        sports_repository=cast(SportsRepository, FakeSportsRepository()),
        lineup_service=cast(MlbLineupService, FakeLineupService()),
        statcast_service=cast(MlbStatcastService, FakeStatcastService()),
        feature_service=cast(MlbGameFeatureService, FakeFeatureService()),
        clock=lambda: NOW,
    )
    with pytest.raises(ValueError, match="cannot exceed 7 days"):
        await service.run(
            start_date=NOW.date(), end_date=NOW.date() + timedelta(days=7), limit=25, offset=0
        )


def test_collection_rejects_range_over_seven_days_before_provider_call() -> None:
    asyncio.run(_reject_range())


class FakeFinalSportsRepository:
    async def list_events(self, **_: object) -> list[FakeEvent]:
        return [FakeEvent(FINAL_ID, "final", NOW - timedelta(days=1), status="final")]


class FakeHistoricalLineupService:
    async def ingest(self, event_id: UUID) -> MlbLineupIngestionResult:
        return MlbLineupIngestionResult(
            created=True,
            snapshot=cast(
                MlbLineupSnapshotRecord,
                SimpleNamespace(
                    id=UUID(int=event_id.int + 100),
                    complete_for_research_features=True,
                ),
            ),
        )


class FakeHistoricalFeatureService(FakeFeatureService):
    async def build(self, statcast_snapshot_id: UUID) -> MlbGameFeatureBuildResult:
        result = await super().build(statcast_snapshot_id)
        result.vector.feature_availability_basis = "retrospective"
        result.vector.complete_feature_vector = True
        return result

    async def label(self, **_: object) -> MlbDatasetLabelResult:
        return MlbDatasetLabelResult(
            created=True,
            example=cast(
                MlbLabeledFeatureExampleRecord,
                SimpleNamespace(
                    id=UUID("81000000-0000-0000-0000-000000000999"),
                    split="test",
                ),
            ),
        )


async def _run_backfill() -> None:
    service = MlbRetrospectiveBackfillService(
        sports_ingestion=cast(SportsIngestionService, FakeSportsIngestion()),
        sports_repository=cast(SportsRepository, FakeFinalSportsRepository()),
        lineup_service=cast(MlbLineupService, FakeHistoricalLineupService()),
        statcast_service=cast(MlbStatcastService, FakeStatcastService()),
        feature_service=cast(MlbGameFeatureService, FakeHistoricalFeatureService()),
        clock=lambda: NOW,
    )

    result = await service.run(start_date=NOW.date(), end_date=NOW.date(), limit=5, offset=0)

    assert result.examined == 1
    assert result.retrospective_vectors_built == 1
    assert result.examples_labeled == 1
    assert result.result_counts == {"retrospective_example_ready": 1}
    assert result.events[0].split == "test"
    assert result.events[0].dataset_example_created is True
    assert result.probability_generated is False
    assert result.automatic_trading_eligible is False


def test_backfill_labels_only_explicitly_retrospective_complete_examples() -> None:
    asyncio.run(_run_backfill())


class FakeExhibitionSportsRepository:
    async def list_events(self, **_: object) -> list[FakeEvent]:
        return [
            FakeEvent(
                FINAL_ID,
                "exhibition",
                NOW - timedelta(days=1),
                status="final",
                raw_data={"gameType": "S"},
            )
        ]


async def _skip_non_regular_game() -> None:
    lineup = FakeLineupService()
    service = MlbRetrospectiveBackfillService(
        sports_ingestion=cast(SportsIngestionService, FakeSportsIngestion()),
        sports_repository=cast(SportsRepository, FakeExhibitionSportsRepository()),
        lineup_service=cast(MlbLineupService, lineup),
        statcast_service=cast(MlbStatcastService, FakeStatcastService()),
        feature_service=cast(MlbGameFeatureService, FakeHistoricalFeatureService()),
        clock=lambda: NOW,
    )

    result = await service.run(start_date=NOW.date(), end_date=NOW.date(), limit=5, offset=0)

    assert result.result_counts == {"unsupported_game_type": 1}
    assert lineup.calls == []
    assert result.examples_labeled == 0


def test_backfill_skips_non_regular_season_games_before_lineup_retrieval() -> None:
    asyncio.run(_skip_non_regular_game())


class FakeHoldoutSportsRepository:
    async def list_events(self, **_: object) -> list[FakeEvent]:
        return [
            FakeEvent(
                FINAL_ID,
                "holdout",
                datetime(2026, 8, 23, 0, 10, tzinfo=UTC),
                status="final",
            )
        ]


async def _skip_retrospective_holdout_event() -> None:
    lineup = FakeLineupService()
    service = MlbRetrospectiveBackfillService(
        sports_ingestion=cast(SportsIngestionService, FakeSportsIngestion()),
        sports_repository=cast(SportsRepository, FakeHoldoutSportsRepository()),
        lineup_service=cast(MlbLineupService, lineup),
        statcast_service=cast(MlbStatcastService, FakeStatcastService()),
        feature_service=cast(MlbGameFeatureService, FakeHistoricalFeatureService()),
        clock=lambda: NOW,
    )

    result = await service.run(start_date=NOW.date(), end_date=NOW.date(), limit=5, offset=0)

    assert result.result_counts == {"prospective_holdout_requires_operational_pregame": 1}
    assert lineup.calls == []
    assert result.retrospective_vectors_built == 0
    assert result.examples_labeled == 0


def test_backfill_skips_holdout_games_before_lineup_retrieval() -> None:
    asyncio.run(_skip_retrospective_holdout_event())
