from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.domain.mlb_modeling import MlbFeatureSelectionPolicy, MlbModelFeatureInput
from app.domain.mlb_statcast import MlbStatcastObservationBasis, MlbStatcastPlayerFeatures
from app.models.mlb import MlbGameFeatureVectorRecord
from app.services.mlb_modeling.engine import DeterministicMlbGameFeatureEngine
from app.services.mlb_modeling.repository import MlbGameFeatureRepository


@dataclass(frozen=True)
class MlbGameFeatureBuildResult:
    created: bool
    vector: MlbGameFeatureVectorRecord


class MlbGameFeatureService:
    """Derive one vector from an exact persisted Statcast source, with no I/O provider."""

    def __init__(
        self,
        *,
        repository: MlbGameFeatureRepository,
        engine: DeterministicMlbGameFeatureEngine,
        policy: MlbFeatureSelectionPolicy,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._engine = engine
        self._policy = policy
        self._clock = clock

    async def build(self, statcast_snapshot_id: UUID) -> MlbGameFeatureBuildResult:
        source = await self._repository.get_statcast_snapshot(statcast_snapshot_id)
        if source is None:
            raise LookupError("MLB Statcast snapshot not found")
        event = source.sports_event
        vector = self._engine.evaluate(
            MlbModelFeatureInput(
                sports_event_id=source.sports_event_id,
                lineup_snapshot_id=source.lineup_snapshot_id,
                statcast_snapshot_id=source.id,
                provider_event_id=source.provider_event_id,
                target_event_date=source.target_event_date,
                scheduled_start_time=source.scheduled_start_time,
                home_team_id=event.home_team_id,
                away_team_id=event.away_team_id,
                source_retrieved_at=source.source_retrieved_at,
                source_observation_basis=MlbStatcastObservationBasis(source.observation_basis),
                source_operational_pregame_eligible=source.operational_pregame_eligible,
                statcast_policy_fingerprint=source.policy_fingerprint,
                statcast_source_fingerprint=source.source_fingerprint,
                statcast_input_fingerprint=source.input_fingerprint,
                home_starting_pitcher=MlbStatcastPlayerFeatures.model_validate(
                    source.home_starting_pitcher
                ),
                away_starting_pitcher=MlbStatcastPlayerFeatures.model_validate(
                    source.away_starting_pitcher
                ),
                home_batters=tuple(
                    MlbStatcastPlayerFeatures.model_validate(item) for item in source.home_batters
                ),
                away_batters=tuple(
                    MlbStatcastPlayerFeatures.model_validate(item) for item in source.away_batters
                ),
                built_at=self._clock(),
                policy=self._policy,
            )
        )
        record, created = await self._repository.persist_vector(vector)
        return MlbGameFeatureBuildResult(created=created, vector=record)
