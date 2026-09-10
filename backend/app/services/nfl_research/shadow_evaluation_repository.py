from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.domain.nfl_shadow import NflShadowPrediction, NflShadowTarget
from app.domain.nfl_shadow_evaluation import (
    NflShadowFinalResult,
    NflShadowLabel,
    NflShadowModelPerformance,
    NflShadowScoringInput,
)
from app.models.nfl_shadow import NflShadowForecastRecord
from app.models.nfl_shadow_evaluation import NflShadowEvaluationRecord
from app.models.sports import SportsEventRecord
from app.providers.sports.nfl import NflGamePayload
from app.services.nfl_research.shadow_evaluation import aggregate_shadow_labels, build_shadow_label

MAX_PERFORMANCE_SNAPSHOTS = 10_000


class NflShadowCanonicalPerformance(BaseModel):
    model_config = ConfigDict(frozen=True)

    total_snapshots: int
    canonical_snapshots: int
    labeled: int
    pending_result: int
    pending_label: int
    ineligible: int
    reason_counts: dict[str, int]
    groups: tuple[NflShadowModelPerformance, ...]
    research_only: Literal[True] = True
    trading_enabled: Literal[False] = False
    canonical_policy: Literal["earliest_capture_per_event_model_seed_v1"] = (
        "earliest_capture_per_event_model_seed_v1"
    )


class _PendingResult(ValueError):
    pass


def _snapshot_input(
    snapshot: NflShadowForecastRecord,
) -> tuple[NflShadowScoringInput, NflShadowTarget]:
    try:
        prediction = NflShadowPrediction.model_validate(snapshot.audit.get("prediction"))
        target = prediction.target_snapshot
        if (
            target.event_id != snapshot.sports_event_id
            or target.scheduled_start != snapshot.scheduled_start_time
            or prediction.seed_fingerprint != snapshot.seed_fingerprint
            or prediction.config_version != snapshot.model_version
            or prediction.expected_home_payout != snapshot.expected_home_payout
            or prediction.expected_away_payout != snapshot.expected_away_payout
            or target.source_last_seen != snapshot.target_source_last_seen_at
            or not target.source_last_seen <= prediction.as_of <= snapshot.generated_at
            or not snapshot.research_only
            or snapshot.trading_enabled
        ):
            raise ValueError("invalid_snapshot_lineage")
        return NflShadowScoringInput(
            snapshot_id=snapshot.id,
            event_id=snapshot.sports_event_id,
            provider_event_id=target.provider_event_id,
            model_version=snapshot.model_version,
            seed_fingerprint=snapshot.seed_fingerprint,
            generated_at=snapshot.generated_at,
            kickoff=snapshot.scheduled_start_time,
            home_team_id=target.home_team_id,
            away_team_id=target.away_team_id,
            yes_team_id=snapshot.yes_team_id,
            expected_home_payout=snapshot.expected_home_payout,
            expected_yes_payout=snapshot.expected_yes_payout,
        ), target
    except ValidationError as exc:
        raise ValueError("invalid_snapshot_audit") from exc


def _current_result(
    event: SportsEventRecord, target: NflShadowTarget, now: datetime
) -> NflShadowFinalResult:
    if (
        event.id != target.event_id
        or event.provider_event_id != target.provider_event_id
        or event.provider_name != "balldontlie_nfl"
        or event.league != "nfl"
        or event.season != 2026
        or event.postseason
        or event.scheduled_start_time != target.scheduled_start
        or event.home_team_id != target.home_team_id
        or event.away_team_id != target.away_team_id
    ):
        raise ValueError("changed_target_identity_or_schedule")
    try:
        payload = NflGamePayload.model_validate(event.raw_data)
        if (
            str(payload.id) != event.provider_event_id
            or payload.season != 2026
            or payload.postseason
            or payload.date != event.scheduled_start_time
            or payload.status_state.strip().casefold() != event.status
            or type(event.raw_data.get("week")) is not int
            or payload.week != target.week
            or event.raw_data.get("preseason", False) is not False
            or event.raw_data.get("season_type", 2) not in (2, "2")
            or str(payload.home_team.id) != event.home_team.provider_team_id
            or str(payload.visitor_team.id) != event.away_team.provider_team_id
            or event.home_team.provider_name != "balldontlie_nfl"
            or event.away_team.provider_name != "balldontlie_nfl"
            or event.home_team.league != "nfl"
            or event.away_team.league != "nfl"
            or event.last_seen_at > now
        ):
            raise ValueError("invalid_result_metadata")
        if event.status != "final":
            raise _PendingResult("pending_result")
        home_score, away_score = event.home_score, event.away_score
        if (
            home_score is None
            or away_score is None
            or payload.home_team_score != home_score
            or payload.visitor_team_score != away_score
            or event.postponed
        ):
            raise ValueError("invalid_final_scores")
        return NflShadowFinalResult(
            status="final",
            event_id=event.id,
            provider_event_id=event.provider_event_id,
            scheduled_start=event.scheduled_start_time,
            home_team_id=event.home_team_id,
            away_team_id=event.away_team_id,
            home_score=home_score,
            away_score=away_score,
            source_last_seen=event.last_seen_at,
        )
    except ValidationError as exc:
        raise ValueError("invalid_result_metadata") from exc


class NflShadowEvaluationRepository:
    """Local ordinary-outcome scoring; never financial settlement or a provider call."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _now(self) -> datetime:
        value = await self._session.scalar(select(func.clock_timestamp()))
        if not isinstance(value, datetime):
            raise ValueError("database_clock_unavailable")
        return value

    async def run(self, snapshot_id: UUID) -> tuple[NflShadowEvaluationRecord, bool]:
        try:
            snapshot_rows = await self._session.scalars(
                select(NflShadowForecastRecord)
                .where(NflShadowForecastRecord.id == snapshot_id)
                .execution_options(populate_existing=True)
            )
            snapshot = snapshot_rows.one_or_none()
            if snapshot is None:
                raise LookupError("NFL shadow snapshot not found")
            scoring, target = _snapshot_input(snapshot)
            result = await self._session.scalars(
                select(SportsEventRecord)
                .where(SportsEventRecord.id == snapshot.sports_event_id)
                .with_for_update(of=SportsEventRecord)
                .execution_options(populate_existing=True)
            )
            event = result.unique().one_or_none()
            if event is None:
                raise LookupError("NFL event not found")
            now = await self._now()
            final = _current_result(event, target, now)
            label = build_shadow_label(scoring, final, now)
            inserted = await self._session.scalar(
                insert(NflShadowEvaluationRecord)
                .values(
                    id=uuid4(),
                    snapshot_id=snapshot.id,
                    sports_event_id=event.id,
                    model_version=snapshot.model_version,
                    seed_fingerprint=snapshot.seed_fingerprint,
                    evaluation_version=label.evaluation_version,
                    snapshot_fingerprint=label.snapshot_fingerprint,
                    result_fingerprint=label.result_fingerprint,
                    input_fingerprint=label.label_fingerprint,
                    label_time=now,
                    generated_at=snapshot.generated_at,
                    scheduled_start_time=snapshot.scheduled_start_time,
                    result_source_last_seen_at=event.last_seen_at,
                    expected_home_payout=scoring.expected_home_payout,
                    expected_yes_payout=scoring.expected_yes_payout,
                    actual_home_payout=label.actual_home_payout,
                    actual_yes_payout=label.actual_yes_payout,
                    squared_home_payout_error=label.squared_home_payout_error,
                    constant_half_squared_error=label.constant_half_squared_error,
                    research_only=True,
                    trading_enabled=False,
                    audit={
                        "label": label.model_dump(mode="json"),
                        "source_raw": event.raw_data,
                        "target": target.model_dump(mode="json"),
                    },
                )
                .on_conflict_do_nothing(
                    index_elements=[NflShadowEvaluationRecord.input_fingerprint]
                )
                .returning(NflShadowEvaluationRecord.id)
            )
            rows = await self._session.scalars(
                select(NflShadowEvaluationRecord).where(
                    NflShadowEvaluationRecord.input_fingerprint == label.label_fingerprint
                )
            )
            record = rows.one()
            await self._session.commit()
            return record, inserted is not None
        except Exception:
            await self._session.rollback()
            raise

    async def get_label(self, label_id: UUID) -> NflShadowEvaluationRecord | None:
        rows = await self._session.scalars(
            select(NflShadowEvaluationRecord)
            .where(NflShadowEvaluationRecord.id == label_id)
            .execution_options(populate_existing=True)
        )
        return rows.one_or_none()

    async def list_labels(self, *, limit: int, offset: int) -> list[NflShadowEvaluationRecord]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("invalid_label_pagination")
        rows = await self._session.scalars(
            select(NflShadowEvaluationRecord)
            .options(defer(NflShadowEvaluationRecord.audit))
            .order_by(
                NflShadowEvaluationRecord.label_time.desc(), NflShadowEvaluationRecord.id.desc()
            )
            .limit(limit)
            .offset(offset)
        )
        return list(rows.all())

    async def performance(self) -> NflShadowCanonicalPerformance:
        rows = await self._session.scalars(
            select(NflShadowForecastRecord)
            .options(defer(NflShadowForecastRecord.audit))
            .order_by(NflShadowForecastRecord.generated_at, NflShadowForecastRecord.id)
            .limit(MAX_PERFORMANCE_SNAPSHOTS + 1)
        )
        snapshots = list(rows.all())
        if len(snapshots) > MAX_PERFORMANCE_SNAPSHOTS:
            raise ValueError("shadow_performance_snapshot_limit_exceeded")
        earliest: dict[tuple[UUID, str, str], UUID] = {}
        for snapshot in snapshots:
            earliest.setdefault(
                (snapshot.sports_event_id, snapshot.model_version, snapshot.seed_fingerprint),
                snapshot.id,
            )
        canonical = (
            list(
                (
                    await self._session.scalars(
                        select(NflShadowForecastRecord)
                        .where(NflShadowForecastRecord.id.in_(earliest.values()))
                        .execution_options(populate_existing=True)
                    )
                ).all()
            )
            if earliest
            else []
        )
        events = (
            {
                event.id: event
                for event in (
                    await self._session.scalars(
                        select(SportsEventRecord)
                        .where(
                            SportsEventRecord.id.in_(
                                [snapshot.sports_event_id for snapshot in canonical]
                            )
                        )
                        .execution_options(populate_existing=True)
                    )
                )
                .unique()
                .all()
            }
            if canonical
            else {}
        )
        now = await self._now()
        expected: dict[str, NflShadowLabel] = {}
        counts: Counter[str] = Counter()
        pending_result = ineligible = 0
        for snapshot in canonical:
            try:
                scoring, target = _snapshot_input(snapshot)
                event = events.get(snapshot.sports_event_id)
                if event is None:
                    raise ValueError("missing_current_event")
                final = _current_result(event, target, now)
                label = build_shadow_label(scoring, final, now)
                expected[label.label_fingerprint] = label
            except _PendingResult:
                pending_result += 1
                counts["pending_result"] += 1
            except ValueError as exc:
                ineligible += 1
                counts[str(exc)] += 1
        current_labels = (
            list(
                (
                    await self._session.scalars(
                        select(NflShadowEvaluationRecord)
                        .where(NflShadowEvaluationRecord.input_fingerprint.in_(expected))
                        .limit(MAX_PERFORMANCE_SNAPSHOTS + 1)
                    )
                ).all()
            )
            if expected
            else []
        )
        if len(current_labels) > MAX_PERFORMANCE_SNAPSHOTS:
            raise ValueError("shadow_performance_label_limit_exceeded")
        verified: list[NflShadowLabel] = []
        for stored in current_labels:
            label = NflShadowLabel.model_validate(stored.audit.get("label"))
            if (
                label.label_fingerprint != stored.input_fingerprint
                or label.snapshot_fingerprint != stored.snapshot_fingerprint
                or label.result_fingerprint != stored.result_fingerprint
                or label.evaluation_version != stored.evaluation_version
                or build_shadow_label(label.snapshot, label.result, label.evaluated_at) != label
                or label.snapshot.snapshot_id != stored.snapshot_id
                or label.snapshot.event_id != stored.sports_event_id
                or label.snapshot.model_version != stored.model_version
                or label.snapshot.seed_fingerprint != stored.seed_fingerprint
                or label.snapshot.generated_at != stored.generated_at
                or label.snapshot.kickoff != stored.scheduled_start_time
                or label.snapshot.expected_home_payout != stored.expected_home_payout
                or label.snapshot.expected_yes_payout != stored.expected_yes_payout
                or label.evaluated_at != stored.label_time
                or label.result.source_last_seen != stored.result_source_last_seen_at
                or label.actual_home_payout != stored.actual_home_payout
                or label.actual_yes_payout != stored.actual_yes_payout
                or label.squared_home_payout_error != stored.squared_home_payout_error
                or label.constant_half_squared_error != stored.constant_half_squared_error
                or not stored.research_only
                or stored.trading_enabled
            ):
                raise ValueError("stored_shadow_label_integrity_failure")
            verified.append(label)
        pending_label = len(expected) - len(verified)
        if pending_label:
            counts["pending_label"] = pending_label
        summary = aggregate_shadow_labels(verified)
        return NflShadowCanonicalPerformance(
            total_snapshots=len(snapshots),
            canonical_snapshots=len(canonical),
            labeled=len(verified),
            pending_result=pending_result,
            pending_label=pending_label,
            ineligible=ineligible,
            reason_counts=dict(sorted(counts.items())),
            groups=summary.model_groups,
        )
