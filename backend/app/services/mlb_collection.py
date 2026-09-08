from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import UUID

from app.domain.mlb_modeling import approved_mlb_dataset_readiness_policy
from app.models.sports import SportsEventRecord
from app.providers.sports.base import SportsDataProviderError
from app.services.mlb_lineups.repository import MlbLineupSourceConflictError
from app.services.mlb_lineups.service import MlbLineupService
from app.services.mlb_modeling.repository import MlbGameFeatureConflictError
from app.services.mlb_modeling.service import MlbGameFeatureService
from app.services.mlb_statcast.repository import MlbStatcastSourceConflictError
from app.services.mlb_statcast.service import MlbStatcastService
from app.services.sports.ingestion import EventIngestionResult, SportsIngestionService
from app.services.sports.repository import SportsRepository

_MAX_COLLECTION_RANGE_DAYS = 7


@dataclass(frozen=True)
class _MlbCollectionSourceEvent:
    """Session-independent event fields used across per-event transaction boundaries."""

    id: UUID
    provider_event_id: str
    scheduled_start_time: datetime
    status: str
    postponed: bool
    game_type: str | None

    @classmethod
    def from_record(cls, event: SportsEventRecord) -> _MlbCollectionSourceEvent:
        game_type = event.raw_data.get("gameType")
        return cls(
            id=event.id,
            provider_event_id=event.provider_event_id,
            scheduled_start_time=event.scheduled_start_time,
            status=event.status,
            postponed=event.postponed,
            game_type=game_type if isinstance(game_type, str) else None,
        )


@dataclass(frozen=True)
class MlbCollectionEventResult:
    event_id: UUID
    provider_event_id: str
    scheduled_start_time: datetime
    stage: Literal["skipped", "lineup_observed", "feature_built", "failed"]
    reason_code: str
    lineup_snapshot_id: UUID | None = None
    statcast_snapshot_id: UUID | None = None
    game_feature_vector_id: UUID | None = None
    lineup_created: bool = False
    statcast_created: bool = False
    feature_vector_created: bool = False
    operational_model_input_eligible: bool = False


@dataclass(frozen=True)
class MlbCollectionRunResult:
    start_date: date
    end_date: date
    run_at: datetime
    events_refreshed: int
    examined: int
    lineup_observed: int
    complete_lineups: int
    feature_vectors_built: int
    operational_feature_vectors: int
    result_counts: dict[str, int]
    events: tuple[MlbCollectionEventResult, ...]
    research_only: Literal[True] = True
    probability_generated: Literal[False] = False
    automatic_trading_eligible: Literal[False] = False


@dataclass(frozen=True)
class MlbBackfillEventResult:
    event_id: UUID
    provider_event_id: str
    scheduled_start_time: datetime
    stage: Literal["skipped", "lineup_observed", "feature_built", "labeled", "failed"]
    reason_code: str
    lineup_snapshot_id: UUID | None = None
    statcast_snapshot_id: UUID | None = None
    game_feature_vector_id: UUID | None = None
    dataset_example_id: UUID | None = None
    split: str | None = None
    lineup_created: bool = False
    statcast_created: bool = False
    feature_vector_created: bool = False
    dataset_example_created: bool = False


@dataclass(frozen=True)
class MlbBackfillRunResult:
    start_date: date
    end_date: date
    run_at: datetime
    events_refreshed: int
    examined: int
    retrospective_vectors_built: int
    examples_labeled: int
    result_counts: dict[str, int]
    events: tuple[MlbBackfillEventResult, ...]
    research_only: Literal[True] = True
    probability_generated: Literal[False] = False
    automatic_trading_eligible: Literal[False] = False


class MlbProspectiveCollectionService:
    """Run the bounded official pregame research pipeline without scheduling or trading."""

    def __init__(
        self,
        *,
        sports_ingestion: SportsIngestionService,
        sports_repository: SportsRepository,
        lineup_service: MlbLineupService,
        statcast_service: MlbStatcastService,
        feature_service: MlbGameFeatureService,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sports_ingestion = sports_ingestion
        self._sports_repository = sports_repository
        self._lineup_service = lineup_service
        self._statcast_service = statcast_service
        self._feature_service = feature_service
        self._clock = clock

    @staticmethod
    def _validate_range(start_date: date, end_date: date) -> None:
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        if end_date - start_date > timedelta(days=_MAX_COLLECTION_RANGE_DAYS - 1):
            raise ValueError(
                f"prospective MLB collection cannot exceed {_MAX_COLLECTION_RANGE_DAYS} days"
            )

    async def run(
        self,
        *,
        start_date: date,
        end_date: date,
        limit: int,
        offset: int,
    ) -> MlbCollectionRunResult:
        self._validate_range(start_date, end_date)
        refresh: EventIngestionResult = await self._sports_ingestion.ingest_events(
            start_date=start_date, end_date=end_date
        )
        events = tuple(
            _MlbCollectionSourceEvent.from_record(event)
            for event in await self._sports_repository.list_events(
                start_date=start_date,
                end_date=end_date,
                league="mlb",
                event_status=None,
                team_id=None,
                provider_name="mlb",
                limit=limit,
                offset=offset,
            )
        )
        run_at = self._clock()
        if run_at.tzinfo is None or run_at.utcoffset() is None:
            raise ValueError("MLB collection clock must be timezone-aware")
        results: list[MlbCollectionEventResult] = []
        for event in events:
            if event.postponed:
                results.append(
                    MlbCollectionEventResult(
                        event_id=event.id,
                        provider_event_id=event.provider_event_id,
                        scheduled_start_time=event.scheduled_start_time,
                        stage="skipped",
                        reason_code="postponed",
                    )
                )
                continue
            if event.status != "scheduled":
                results.append(
                    MlbCollectionEventResult(
                        event_id=event.id,
                        provider_event_id=event.provider_event_id,
                        scheduled_start_time=event.scheduled_start_time,
                        stage="skipped",
                        reason_code="not_scheduled",
                    )
                )
                continue
            if event.scheduled_start_time <= run_at:
                results.append(
                    MlbCollectionEventResult(
                        event_id=event.id,
                        provider_event_id=event.provider_event_id,
                        scheduled_start_time=event.scheduled_start_time,
                        stage="skipped",
                        reason_code="first_pitch_reached",
                    )
                )
                continue
            try:
                lineup = await self._lineup_service.ingest(event.id)
                lineup_snapshot_id = lineup.snapshot.id
                lineup_complete = lineup.snapshot.complete_for_pregame_model
                lineup_created = lineup.created
                if not lineup_complete:
                    results.append(
                        MlbCollectionEventResult(
                            event_id=event.id,
                            provider_event_id=event.provider_event_id,
                            scheduled_start_time=event.scheduled_start_time,
                            stage="lineup_observed",
                            reason_code="lineup_incomplete",
                            lineup_snapshot_id=lineup_snapshot_id,
                            lineup_created=lineup_created,
                        )
                    )
                    continue
                statcast = await self._statcast_service.ingest(
                    event_id=event.id,
                    lineup_snapshot_id=lineup_snapshot_id,
                )
                statcast_snapshot_id = statcast.snapshot.id
                statcast_created = statcast.created
                vector = await self._feature_service.build(statcast_snapshot_id)
                vector_id = vector.vector.id
                operational_model_input_eligible = vector.vector.operational_model_input_eligible
                feature_vector_created = vector.created
                results.append(
                    MlbCollectionEventResult(
                        event_id=event.id,
                        provider_event_id=event.provider_event_id,
                        scheduled_start_time=event.scheduled_start_time,
                        stage="feature_built",
                        reason_code=(
                            "operational_feature_ready"
                            if operational_model_input_eligible
                            else "retrospective_only"
                        ),
                        lineup_snapshot_id=lineup_snapshot_id,
                        statcast_snapshot_id=statcast_snapshot_id,
                        game_feature_vector_id=vector_id,
                        lineup_created=lineup_created,
                        statcast_created=statcast_created,
                        feature_vector_created=feature_vector_created,
                        operational_model_input_eligible=operational_model_input_eligible,
                    )
                )
            except SportsDataProviderError:
                results.append(
                    MlbCollectionEventResult(
                        event_id=event.id,
                        provider_event_id=event.provider_event_id,
                        scheduled_start_time=event.scheduled_start_time,
                        stage="failed",
                        reason_code="official_source_unavailable",
                    )
                )
            except (
                LookupError,
                ValueError,
                MlbLineupSourceConflictError,
                MlbStatcastSourceConflictError,
                MlbGameFeatureConflictError,
            ):
                results.append(
                    MlbCollectionEventResult(
                        event_id=event.id,
                        provider_event_id=event.provider_event_id,
                        scheduled_start_time=event.scheduled_start_time,
                        stage="failed",
                        reason_code="source_lineage_conflict",
                    )
                )
        counts = Counter(result.reason_code for result in results)
        return MlbCollectionRunResult(
            start_date=start_date,
            end_date=end_date,
            run_at=run_at,
            events_refreshed=refresh.events_persisted,
            examined=len(results),
            lineup_observed=sum(result.lineup_snapshot_id is not None for result in results),
            complete_lineups=sum(result.statcast_snapshot_id is not None for result in results),
            feature_vectors_built=sum(
                result.game_feature_vector_id is not None for result in results
            ),
            operational_feature_vectors=sum(
                result.operational_model_input_eligible for result in results
            ),
            result_counts=dict(sorted(counts.items())),
            events=tuple(results),
        )


class MlbRetrospectiveBackfillService:
    """Build explicitly retrospective research examples from official completed games."""

    def __init__(
        self,
        *,
        sports_ingestion: SportsIngestionService,
        sports_repository: SportsRepository,
        lineup_service: MlbLineupService,
        statcast_service: MlbStatcastService,
        feature_service: MlbGameFeatureService,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sports_ingestion = sports_ingestion
        self._sports_repository = sports_repository
        self._lineup_service = lineup_service
        self._statcast_service = statcast_service
        self._feature_service = feature_service
        self._clock = clock

    async def run(
        self,
        *,
        start_date: date,
        end_date: date,
        limit: int,
        offset: int,
    ) -> MlbBackfillRunResult:
        MlbProspectiveCollectionService._validate_range(start_date, end_date)
        refresh = await self._sports_ingestion.ingest_events(
            start_date=start_date, end_date=end_date
        )
        events = tuple(
            _MlbCollectionSourceEvent.from_record(event)
            for event in await self._sports_repository.list_events(
                start_date=start_date,
                end_date=end_date,
                league="mlb",
                event_status=None,
                team_id=None,
                provider_name="mlb",
                limit=limit,
                offset=offset,
            )
        )
        run_at = self._clock()
        if run_at.tzinfo is None or run_at.utcoffset() is None:
            raise ValueError("MLB backfill clock must be timezone-aware")
        split_policy = approved_mlb_dataset_readiness_policy().split_policy
        results: list[MlbBackfillEventResult] = []
        for event in events:
            if event.postponed:
                results.append(
                    MlbBackfillEventResult(
                        event_id=event.id,
                        provider_event_id=event.provider_event_id,
                        scheduled_start_time=event.scheduled_start_time,
                        stage="skipped",
                        reason_code="postponed",
                    )
                )
                continue
            if event.game_type != "R":
                results.append(
                    MlbBackfillEventResult(
                        event_id=event.id,
                        provider_event_id=event.provider_event_id,
                        scheduled_start_time=event.scheduled_start_time,
                        stage="skipped",
                        reason_code="unsupported_game_type",
                    )
                )
                continue
            if event.scheduled_start_time >= split_policy.prospective_holdout_start:
                results.append(
                    MlbBackfillEventResult(
                        event_id=event.id,
                        provider_event_id=event.provider_event_id,
                        scheduled_start_time=event.scheduled_start_time,
                        stage="skipped",
                        reason_code="prospective_holdout_requires_operational_pregame",
                    )
                )
                continue
            if event.status != "final":
                results.append(
                    MlbBackfillEventResult(
                        event_id=event.id,
                        provider_event_id=event.provider_event_id,
                        scheduled_start_time=event.scheduled_start_time,
                        stage="skipped",
                        reason_code="outcome_not_final",
                    )
                )
                continue
            try:
                lineup = await self._lineup_service.ingest(event.id)
                lineup_snapshot_id = lineup.snapshot.id
                lineup_complete = lineup.snapshot.complete_for_research_features
                lineup_created = lineup.created
                if not lineup_complete:
                    results.append(
                        MlbBackfillEventResult(
                            event_id=event.id,
                            provider_event_id=event.provider_event_id,
                            scheduled_start_time=event.scheduled_start_time,
                            stage="lineup_observed",
                            reason_code="historical_lineup_incomplete",
                            lineup_snapshot_id=lineup_snapshot_id,
                            lineup_created=lineup_created,
                        )
                    )
                    continue
                statcast = await self._statcast_service.ingest(
                    event_id=event.id,
                    lineup_snapshot_id=lineup_snapshot_id,
                )
                statcast_snapshot_id = statcast.snapshot.id
                statcast_created = statcast.created
                vector = await self._feature_service.build(statcast_snapshot_id)
                vector_id = vector.vector.id
                feature_availability_basis = vector.vector.feature_availability_basis
                complete_feature_vector = vector.vector.complete_feature_vector
                feature_vector_created = vector.created
                if feature_availability_basis != "retrospective":
                    raise ValueError("historical backfill produced a non-retrospective vector")
                if not complete_feature_vector:
                    results.append(
                        MlbBackfillEventResult(
                            event_id=event.id,
                            provider_event_id=event.provider_event_id,
                            scheduled_start_time=event.scheduled_start_time,
                            stage="feature_built",
                            reason_code="feature_vector_incomplete",
                            lineup_snapshot_id=lineup_snapshot_id,
                            statcast_snapshot_id=statcast_snapshot_id,
                            game_feature_vector_id=vector_id,
                            lineup_created=lineup_created,
                            statcast_created=statcast_created,
                            feature_vector_created=feature_vector_created,
                        )
                    )
                    continue
                label = await self._feature_service.label(
                    vector_id=vector_id,
                    split_policy=split_policy,
                )
                dataset_example_id = label.example.id
                split = label.example.split
                dataset_example_created = label.created
                results.append(
                    MlbBackfillEventResult(
                        event_id=event.id,
                        provider_event_id=event.provider_event_id,
                        scheduled_start_time=event.scheduled_start_time,
                        stage="labeled",
                        reason_code="retrospective_example_ready",
                        lineup_snapshot_id=lineup_snapshot_id,
                        statcast_snapshot_id=statcast_snapshot_id,
                        game_feature_vector_id=vector_id,
                        dataset_example_id=dataset_example_id,
                        split=split,
                        lineup_created=lineup_created,
                        statcast_created=statcast_created,
                        feature_vector_created=feature_vector_created,
                        dataset_example_created=dataset_example_created,
                    )
                )
            except SportsDataProviderError:
                results.append(
                    MlbBackfillEventResult(
                        event_id=event.id,
                        provider_event_id=event.provider_event_id,
                        scheduled_start_time=event.scheduled_start_time,
                        stage="failed",
                        reason_code="official_source_unavailable",
                    )
                )
            except (
                LookupError,
                ValueError,
                MlbLineupSourceConflictError,
                MlbStatcastSourceConflictError,
                MlbGameFeatureConflictError,
            ):
                results.append(
                    MlbBackfillEventResult(
                        event_id=event.id,
                        provider_event_id=event.provider_event_id,
                        scheduled_start_time=event.scheduled_start_time,
                        stage="failed",
                        reason_code="source_or_outcome_ineligible",
                    )
                )
        counts = Counter(result.reason_code for result in results)
        return MlbBackfillRunResult(
            start_date=start_date,
            end_date=end_date,
            run_at=run_at,
            events_refreshed=refresh.events_persisted,
            examined=len(results),
            retrospective_vectors_built=sum(
                result.game_feature_vector_id is not None for result in results
            ),
            examples_labeled=sum(result.dataset_example_id is not None for result in results),
            result_counts=dict(sorted(counts.items())),
            events=tuple(results),
        )
