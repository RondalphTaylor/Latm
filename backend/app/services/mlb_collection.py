from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import UUID

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
        events = await self._sports_repository.list_events(
            start_date=start_date,
            end_date=end_date,
            league="mlb",
            event_status=None,
            team_id=None,
            provider_name="mlb",
            limit=limit,
            offset=offset,
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
                if not lineup.snapshot.complete_for_pregame_model:
                    results.append(
                        MlbCollectionEventResult(
                            event_id=event.id,
                            provider_event_id=event.provider_event_id,
                            scheduled_start_time=event.scheduled_start_time,
                            stage="lineup_observed",
                            reason_code="lineup_incomplete",
                            lineup_snapshot_id=lineup.snapshot.id,
                            lineup_created=lineup.created,
                        )
                    )
                    continue
                statcast = await self._statcast_service.ingest(
                    event_id=event.id,
                    lineup_snapshot_id=lineup.snapshot.id,
                )
                vector = await self._feature_service.build(statcast.snapshot.id)
                results.append(
                    MlbCollectionEventResult(
                        event_id=event.id,
                        provider_event_id=event.provider_event_id,
                        scheduled_start_time=event.scheduled_start_time,
                        stage="feature_built",
                        reason_code=(
                            "operational_feature_ready"
                            if vector.vector.operational_model_input_eligible
                            else "retrospective_only"
                        ),
                        lineup_snapshot_id=lineup.snapshot.id,
                        statcast_snapshot_id=statcast.snapshot.id,
                        game_feature_vector_id=vector.vector.id,
                        lineup_created=lineup.created,
                        statcast_created=statcast.created,
                        feature_vector_created=vector.created,
                        operational_model_input_eligible=(
                            vector.vector.operational_model_input_eligible
                        ),
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
