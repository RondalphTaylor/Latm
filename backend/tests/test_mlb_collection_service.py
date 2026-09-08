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
from app.services.mlb_lineups.repository import MlbLineupSourceConflictError
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


class ExpiringFakeEvent:
    """Mimic a request-scoped ORM event invalidated by a repository rollback."""

    def __init__(self, event_id: UUID, provider_event_id: str) -> None:
        self._id = event_id
        self._provider_event_id = provider_event_id
        self._scheduled_start_time = NOW - timedelta(days=1)
        self._expired = False

    def expire(self) -> None:
        self._expired = True

    def _require_active(self) -> None:
        if self._expired:
            raise RuntimeError("expired ORM attribute access")

    @property
    def id(self) -> UUID:
        self._require_active()
        return self._id

    @property
    def provider_event_id(self) -> str:
        self._require_active()
        return self._provider_event_id

    @property
    def scheduled_start_time(self) -> datetime:
        self._require_active()
        return self._scheduled_start_time

    @property
    def status(self) -> str:
        self._require_active()
        return "final"

    @property
    def postponed(self) -> bool:
        self._require_active()
        return False

    @property
    def raw_data(self) -> dict[str, object]:
        self._require_active()
        return {"gameType": "R"}


class ExpiringFinalSportsRepository:
    def __init__(self) -> None:
        self.events = [
            ExpiringFakeEvent(FINAL_ID, "conflict"),
            ExpiringFakeEvent(UUID(int=FINAL_ID.int + 1), "ready"),
        ]

    async def list_events(self, **_: object) -> list[ExpiringFakeEvent]:
        return self.events


class RollbackExpiringLineupService(FakeHistoricalLineupService):
    def __init__(self, events: list[ExpiringFakeEvent]) -> None:
        self._events = events
        self.calls: list[UUID] = []

    async def ingest(self, event_id: UUID) -> MlbLineupIngestionResult:
        self.calls.append(event_id)
        if len(self.calls) == 1:
            for event in self._events:
                event.expire()
            raise MlbLineupSourceConflictError("official feed schedule changed")
        return await super().ingest(event_id)


async def _continue_backfill_after_rollback_expires_loaded_events() -> None:
    sports_repository = ExpiringFinalSportsRepository()
    lineup = RollbackExpiringLineupService(sports_repository.events)
    service = MlbRetrospectiveBackfillService(
        sports_ingestion=cast(SportsIngestionService, FakeSportsIngestion()),
        sports_repository=cast(SportsRepository, sports_repository),
        lineup_service=cast(MlbLineupService, lineup),
        statcast_service=cast(MlbStatcastService, FakeStatcastService()),
        feature_service=cast(MlbGameFeatureService, FakeHistoricalFeatureService()),
        clock=lambda: NOW,
    )

    result = await service.run(start_date=NOW.date(), end_date=NOW.date(), limit=5, offset=0)

    assert lineup.calls == [FINAL_ID, UUID(int=FINAL_ID.int + 1)]
    assert result.examined == 2
    assert result.examples_labeled == 1
    assert result.result_counts == {
        "retrospective_example_ready": 1,
        "source_or_outcome_ineligible": 1,
    }
    assert result.events[0].event_id == FINAL_ID
    assert result.events[0].reason_code == "source_or_outcome_ineligible"
    assert result.events[1].reason_code == "retrospective_example_ready"


def test_backfill_continues_after_rollback_expires_loaded_events() -> None:
    asyncio.run(_continue_backfill_after_rollback_expires_loaded_events())


class ExpiringPipelineRecord:
    """Mimic a successful ORM result invalidated by a later transaction rollback."""

    def __init__(
        self,
        record_id: UUID,
        *,
        complete_for_research_features: bool | None = None,
        feature_availability_basis: str | None = None,
        complete_feature_vector: bool | None = None,
    ) -> None:
        self._id = record_id
        self._complete_for_research_features = complete_for_research_features
        self._feature_availability_basis = feature_availability_basis
        self._complete_feature_vector = complete_feature_vector
        self._expired = False

    def expire(self) -> None:
        self._expired = True

    def _value(self, value: object) -> object:
        if self._expired:
            raise RuntimeError("expired pipeline ORM attribute access")
        return value

    @property
    def id(self) -> UUID:
        return cast(UUID, self._value(self._id))

    @property
    def complete_for_research_features(self) -> bool:
        return cast(bool, self._value(self._complete_for_research_features))

    @property
    def feature_availability_basis(self) -> str:
        return cast(str, self._value(self._feature_availability_basis))

    @property
    def complete_feature_vector(self) -> bool:
        return cast(bool, self._value(self._complete_feature_vector))


class TrackingHistoricalLineupService:
    def __init__(self) -> None:
        self.snapshot = ExpiringPipelineRecord(
            UUID(int=FINAL_ID.int + 100),
            complete_for_research_features=True,
        )

    async def ingest(self, event_id: UUID) -> MlbLineupIngestionResult:
        assert event_id == FINAL_ID
        return MlbLineupIngestionResult(
            created=False,
            snapshot=cast(MlbLineupSnapshotRecord, self.snapshot),
        )


class TrackingStatcastService:
    def __init__(self) -> None:
        self.snapshot = ExpiringPipelineRecord(UUID(int=FINAL_ID.int + 200))

    async def ingest(
        self, *, event_id: UUID, lineup_snapshot_id: UUID
    ) -> MlbStatcastIngestionResult:
        assert event_id == FINAL_ID
        assert lineup_snapshot_id == UUID(int=FINAL_ID.int + 100)
        return MlbStatcastIngestionResult(
            created=False,
            snapshot=cast(MlbStatcastFeatureSnapshotRecord, self.snapshot),
        )


class RollbackAfterLabelFeatureService:
    def __init__(
        self,
        lineup_snapshot: ExpiringPipelineRecord,
        statcast_snapshot: ExpiringPipelineRecord,
    ) -> None:
        self._lineup_snapshot = lineup_snapshot
        self._statcast_snapshot = statcast_snapshot
        self.vector = ExpiringPipelineRecord(
            UUID(int=FINAL_ID.int + 300),
            feature_availability_basis="retrospective",
            complete_feature_vector=True,
        )

    async def build(self, statcast_snapshot_id: UUID) -> MlbGameFeatureBuildResult:
        assert statcast_snapshot_id == UUID(int=FINAL_ID.int + 200)
        return MlbGameFeatureBuildResult(
            created=False,
            vector=cast(MlbGameFeatureVectorRecord, self.vector),
        )

    async def label(self, **_: object) -> MlbDatasetLabelResult:
        self._lineup_snapshot.expire()
        self._statcast_snapshot.expire()
        self.vector.expire()
        return MlbDatasetLabelResult(
            created=False,
            example=cast(
                MlbLabeledFeatureExampleRecord,
                SimpleNamespace(
                    id=UUID("81000000-0000-0000-0000-000000000998"),
                    split="test",
                ),
            ),
        )


async def _finish_backfill_after_later_rollback_expires_stage_records() -> None:
    lineup = TrackingHistoricalLineupService()
    statcast = TrackingStatcastService()
    features = RollbackAfterLabelFeatureService(lineup.snapshot, statcast.snapshot)
    service = MlbRetrospectiveBackfillService(
        sports_ingestion=cast(SportsIngestionService, FakeSportsIngestion()),
        sports_repository=cast(SportsRepository, FakeFinalSportsRepository()),
        lineup_service=cast(MlbLineupService, lineup),
        statcast_service=cast(MlbStatcastService, statcast),
        feature_service=cast(MlbGameFeatureService, features),
        clock=lambda: NOW,
    )

    result = await service.run(start_date=NOW.date(), end_date=NOW.date(), limit=5, offset=0)

    assert result.result_counts == {"retrospective_example_ready": 1}
    assert result.events[0].lineup_snapshot_id == UUID(int=FINAL_ID.int + 100)
    assert result.events[0].statcast_snapshot_id == UUID(int=FINAL_ID.int + 200)
    assert result.events[0].game_feature_vector_id == UUID(int=FINAL_ID.int + 300)
    assert result.events[0].dataset_example_created is False


def test_backfill_snapshots_stage_fields_before_later_transaction_boundary() -> None:
    asyncio.run(_finish_backfill_after_later_rollback_expires_stage_records())
