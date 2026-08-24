from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal, cast
from uuid import UUID, uuid5

from pydantic import TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.mlb_modeling import (
    MlbDatasetReadinessAssessment,
    MlbDatasetSplit,
    MlbHistoricalBackfillPolicy,
    approved_mlb_dataset_readiness_policy,
)
from app.models.mlb import MlbBackfillBatchRecord, MlbBackfillCheckpointRecord
from app.services.mlb_collection import (
    MlbBackfillEventResult,
    MlbBackfillRunResult,
    MlbRetrospectiveBackfillService,
)
from app.services.mlb_modeling.engine import (
    mlb_chronological_split_policy_fingerprint,
    mlb_dataset_readiness_policy_fingerprint,
)
from app.services.mlb_modeling.service import MlbGameFeatureService

_NAMESPACE = UUID("39e74d5a-145f-4bba-a909-82f540293927")
_EVENT_RESULTS_ADAPTER = TypeAdapter(list[MlbBackfillEventResult])
BackfillStatus = Literal["active", "complete", "exhausted"]
WorkflowAction = Literal["ran_batch", "complete", "exhausted"]
TerminalAction = Literal["complete", "exhausted"]


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def mlb_historical_backfill_policy_fingerprint(
    policy: MlbHistoricalBackfillPolicy,
) -> str:
    readiness_policy = approved_mlb_dataset_readiness_policy()
    return _hash(
        {
            "policy": policy.model_dump(mode="json"),
            "readiness_policy_fingerprint": mlb_dataset_readiness_policy_fingerprint(
                readiness_policy
            ),
        }
    )


def _checkpoint_id(policy_fingerprint: str) -> UUID:
    return uuid5(_NAMESPACE, f"checkpoint:{policy_fingerprint}")


def _batch_id(checkpoint_id: UUID, input_fingerprint: str) -> UUID:
    return uuid5(_NAMESPACE, f"batch:{checkpoint_id}:{input_fingerprint}")


def _checkpoint_state_fingerprint(values: dict[str, object]) -> str:
    return _hash(values)


def _event_results_json(
    events: tuple[MlbBackfillEventResult, ...],
) -> list[dict[str, object]]:
    """Return the immutable event audit facts in PostgreSQL JSONB-safe form."""
    return cast(
        list[dict[str, object]],
        _EVENT_RESULTS_ADAPTER.dump_python(list(events), mode="json"),
    )


def _state_values(
    *,
    checkpoint_id: UUID,
    policy_fingerprint: str,
    status: BackfillStatus,
    train_cursor_date: date,
    train_cursor_offset: int,
    validation_cursor_date: date,
    validation_cursor_offset: int,
    test_cursor_date: date,
    test_cursor_offset: int,
    version: int,
    batches_completed: int,
    events_examined: int,
    examples_created: int,
) -> dict[str, object]:
    return {
        "checkpoint_id": str(checkpoint_id),
        "policy_fingerprint": policy_fingerprint,
        "status": status,
        "train_cursor_date": train_cursor_date.isoformat(),
        "train_cursor_offset": train_cursor_offset,
        "validation_cursor_date": validation_cursor_date.isoformat(),
        "validation_cursor_offset": validation_cursor_offset,
        "test_cursor_date": test_cursor_date.isoformat(),
        "test_cursor_offset": test_cursor_offset,
        "version": version,
        "batches_completed": batches_completed,
        "events_examined": events_examined,
        "examples_created": examples_created,
    }


@dataclass(frozen=True)
class MlbBackfillPlan:
    split: MlbDatasetSplit
    window_date: date
    offset: int
    limit: int
    input_fingerprint: str


@dataclass(frozen=True)
class MlbBackfillWorkflowRunResult:
    action: WorkflowAction
    created: bool
    checkpoint: MlbBackfillCheckpointRecord
    batch: MlbBackfillBatchRecord | None
    readiness: MlbDatasetReadinessAssessment


class MlbBackfillWorkflowConflictError(RuntimeError):
    """Checkpoint state changed outside the expected idempotent cursor transition."""


class MlbBackfillWorkflowRetryableError(RuntimeError):
    """Official provider failed and the cursor must remain unchanged for retry."""


class MlbBackfillWorkflowRepository:
    """Persist one mutable cursor and append-only successful batch facts."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create_checkpoint(
        self, policy: MlbHistoricalBackfillPolicy
    ) -> MlbBackfillCheckpointRecord:
        readiness = approved_mlb_dataset_readiness_policy()
        split_policy_fingerprint = mlb_chronological_split_policy_fingerprint(
            readiness.split_policy
        )
        policy_fingerprint = mlb_historical_backfill_policy_fingerprint(policy)
        record_id = _checkpoint_id(policy_fingerprint)
        validation_start = readiness.split_policy.validation_start.date()
        test_start = readiness.split_policy.test_start.date()
        holdout_start = readiness.split_policy.prospective_holdout_start.date()
        train_cursor_date = validation_start - timedelta(days=1)
        validation_cursor_date = test_start - timedelta(days=1)
        test_cursor_date = holdout_start - timedelta(days=1)
        initial = _state_values(
            checkpoint_id=record_id,
            policy_fingerprint=policy_fingerprint,
            status="active",
            train_cursor_date=train_cursor_date,
            train_cursor_offset=0,
            validation_cursor_date=validation_cursor_date,
            validation_cursor_offset=0,
            test_cursor_date=test_cursor_date,
            test_cursor_offset=0,
            version=0,
            batches_completed=0,
            events_examined=0,
            examples_created=0,
        )
        try:
            await self._session.execute(
                insert(MlbBackfillCheckpointRecord)
                .values(
                    id=record_id,
                    policy_name=policy.policy_name,
                    policy_version=policy.policy_version,
                    policy_fingerprint=policy_fingerprint,
                    split_policy_fingerprint=split_policy_fingerprint,
                    status="active",
                    regular_season_start=policy.regular_season_start,
                    validation_start_date=validation_start,
                    test_start_date=test_start,
                    prospective_holdout_start_date=holdout_start,
                    train_cursor_date=train_cursor_date,
                    train_cursor_offset=0,
                    validation_cursor_date=validation_cursor_date,
                    validation_cursor_offset=0,
                    test_cursor_date=test_cursor_date,
                    test_cursor_offset=0,
                    batch_limit=policy.batch_limit,
                    version=0,
                    batches_completed=0,
                    events_examined=0,
                    examples_created=0,
                    state_fingerprint=_checkpoint_state_fingerprint(initial),
                    research_only=True,
                    probability_generated=False,
                    automatic_trading_eligible=False,
                )
                .on_conflict_do_nothing(constraint="uq_mlb_backfill_checkpoints_policy")
            )
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        checkpoint = await self.get_checkpoint(record_id)
        if checkpoint is None:
            raise RuntimeError("MLB backfill checkpoint could not be loaded")
        return checkpoint

    async def get_checkpoint(self, checkpoint_id: UUID) -> MlbBackfillCheckpointRecord | None:
        result = await self._session.scalars(
            select(MlbBackfillCheckpointRecord).where(
                MlbBackfillCheckpointRecord.id == checkpoint_id
            )
        )
        return result.unique().one_or_none()

    async def get_for_policy(self, policy_fingerprint: str) -> MlbBackfillCheckpointRecord | None:
        result = await self._session.scalars(
            select(MlbBackfillCheckpointRecord).where(
                MlbBackfillCheckpointRecord.policy_fingerprint == policy_fingerprint
            )
        )
        return result.unique().one_or_none()

    async def list_batches(
        self, *, checkpoint_id: UUID, limit: int, offset: int
    ) -> list[MlbBackfillBatchRecord]:
        return list(
            (
                await self._session.scalars(
                    select(MlbBackfillBatchRecord)
                    .where(MlbBackfillBatchRecord.checkpoint_id == checkpoint_id)
                    .order_by(MlbBackfillBatchRecord.sequence.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .unique()
            .all()
        )

    async def finalize_checkpoint(
        self,
        *,
        checkpoint: MlbBackfillCheckpointRecord,
        status: TerminalAction,
    ) -> MlbBackfillCheckpointRecord:
        try:
            locked = await self._session.scalar(
                select(MlbBackfillCheckpointRecord)
                .where(MlbBackfillCheckpointRecord.id == checkpoint.id)
                .with_for_update(of=MlbBackfillCheckpointRecord)
            )
            if locked is None:
                raise LookupError("MLB backfill checkpoint not found")
            if locked.status in {"complete", "exhausted"}:
                await self._session.commit()
                return locked
            if locked.state_fingerprint != checkpoint.state_fingerprint:
                raise MlbBackfillWorkflowConflictError("MLB backfill checkpoint advanced")
            finished_at_value = await self._session.scalar(select(func.clock_timestamp()))
            if finished_at_value is None:
                raise RuntimeError("database did not return an MLB backfill timestamp")
            finished_at = cast(datetime, finished_at_value)
            next_version = locked.version + 1
            state = _state_values(
                checkpoint_id=locked.id,
                policy_fingerprint=locked.policy_fingerprint,
                status=status,
                train_cursor_date=locked.train_cursor_date,
                train_cursor_offset=locked.train_cursor_offset,
                validation_cursor_date=locked.validation_cursor_date,
                validation_cursor_offset=locked.validation_cursor_offset,
                test_cursor_date=locked.test_cursor_date,
                test_cursor_offset=locked.test_cursor_offset,
                version=next_version,
                batches_completed=locked.batches_completed,
                events_examined=locked.events_examined,
                examples_created=locked.examples_created,
            )
            locked.status = status
            locked.version = next_version
            locked.finished_at = finished_at
            locked.state_fingerprint = _checkpoint_state_fingerprint(state)
            await self._session.commit()
            reloaded = await self.get_checkpoint(locked.id)
            if reloaded is None:
                raise RuntimeError("MLB backfill checkpoint could not be finalized")
            return reloaded
        except Exception:
            await self._session.rollback()
            raise

    async def persist_batch(
        self,
        *,
        checkpoint: MlbBackfillCheckpointRecord,
        plan: MlbBackfillPlan,
        cursor_date_after: date,
        cursor_offset_after: int,
        result: MlbBackfillRunResult,
        readiness_before: MlbDatasetReadinessAssessment,
        readiness_after: MlbDatasetReadinessAssessment,
        next_status: BackfillStatus,
    ) -> tuple[MlbBackfillCheckpointRecord, MlbBackfillBatchRecord, bool]:
        event_results = _event_results_json(result.events)
        readiness_before_json = readiness_before.model_dump(mode="json")
        readiness_after_json = readiness_after.model_dump(mode="json")
        examples_created = sum(event.dataset_example_created for event in result.events)
        result_fingerprint = _hash(
            {
                "input_fingerprint": plan.input_fingerprint,
                "run": {
                    "run_at": result.run_at.isoformat(),
                    "events_refreshed": result.events_refreshed,
                    "examined": result.examined,
                    "retrospective_vectors_built": result.retrospective_vectors_built,
                    "examples_labeled": result.examples_labeled,
                    "examples_created": examples_created,
                    "result_counts": result.result_counts,
                    "events": event_results,
                },
                "readiness_after": readiness_after_json,
            }
        )
        try:
            locked = await self._session.scalar(
                select(MlbBackfillCheckpointRecord)
                .where(MlbBackfillCheckpointRecord.id == checkpoint.id)
                .with_for_update(of=MlbBackfillCheckpointRecord)
            )
            if locked is None:
                raise LookupError("MLB backfill checkpoint not found")
            existing = await self._session.scalar(
                select(MlbBackfillBatchRecord).where(
                    MlbBackfillBatchRecord.checkpoint_id == checkpoint.id,
                    MlbBackfillBatchRecord.input_fingerprint == plan.input_fingerprint,
                )
            )
            if existing is not None:
                await self._session.commit()
                reloaded = await self.get_checkpoint(checkpoint.id)
                if reloaded is None:
                    raise RuntimeError("MLB backfill checkpoint replay could not be loaded")
                return reloaded, existing, False
            if locked.state_fingerprint != checkpoint.state_fingerprint:
                raise MlbBackfillWorkflowConflictError("MLB backfill checkpoint advanced")

            train_cursor_date = locked.train_cursor_date
            train_cursor_offset = locked.train_cursor_offset
            validation_cursor_date = locked.validation_cursor_date
            validation_cursor_offset = locked.validation_cursor_offset
            test_cursor_date = locked.test_cursor_date
            test_cursor_offset = locked.test_cursor_offset
            if plan.split is MlbDatasetSplit.TRAIN:
                train_cursor_date = cursor_date_after
                train_cursor_offset = cursor_offset_after
            elif plan.split is MlbDatasetSplit.VALIDATION:
                validation_cursor_date = cursor_date_after
                validation_cursor_offset = cursor_offset_after
            else:
                test_cursor_date = cursor_date_after
                test_cursor_offset = cursor_offset_after
            next_version = locked.version + 1
            next_batches = locked.batches_completed + 1
            next_examined = locked.events_examined + result.examined
            next_examples = locked.examples_created + examples_created
            state = _state_values(
                checkpoint_id=locked.id,
                policy_fingerprint=locked.policy_fingerprint,
                status=next_status,
                train_cursor_date=train_cursor_date,
                train_cursor_offset=train_cursor_offset,
                validation_cursor_date=validation_cursor_date,
                validation_cursor_offset=validation_cursor_offset,
                test_cursor_date=test_cursor_date,
                test_cursor_offset=test_cursor_offset,
                version=next_version,
                batches_completed=next_batches,
                events_examined=next_examined,
                examples_created=next_examples,
            )
            batch = MlbBackfillBatchRecord(
                id=_batch_id(locked.id, plan.input_fingerprint),
                checkpoint_id=locked.id,
                sequence=next_batches,
                split=plan.split.value,
                window_date=plan.window_date,
                offset=plan.offset,
                batch_limit=plan.limit,
                cursor_date_after=cursor_date_after,
                cursor_offset_after=cursor_offset_after,
                run_at=result.run_at,
                events_refreshed=result.events_refreshed,
                examined=result.examined,
                retrospective_vectors_built=result.retrospective_vectors_built,
                examples_labeled=result.examples_labeled,
                examples_created=examples_created,
                result_counts=result.result_counts,
                event_results=event_results,
                readiness_before=readiness_before_json,
                readiness_after=readiness_after_json,
                input_fingerprint=plan.input_fingerprint,
                result_fingerprint=result_fingerprint,
                research_only=True,
                probability_generated=False,
                automatic_trading_eligible=False,
            )
            self._session.add(batch)
            locked.status = next_status
            locked.train_cursor_date = train_cursor_date
            locked.train_cursor_offset = train_cursor_offset
            locked.validation_cursor_date = validation_cursor_date
            locked.validation_cursor_offset = validation_cursor_offset
            locked.test_cursor_date = test_cursor_date
            locked.test_cursor_offset = test_cursor_offset
            locked.version = next_version
            locked.batches_completed = next_batches
            locked.events_examined = next_examined
            locked.examples_created = next_examples
            locked.last_run_at = result.run_at
            locked.finished_at = result.run_at if next_status != "active" else None
            locked.state_fingerprint = _checkpoint_state_fingerprint(state)
            await self._session.commit()
            reloaded_checkpoint = await self.get_checkpoint(locked.id)
            reloaded_batch = await self._session.scalar(
                select(MlbBackfillBatchRecord).where(MlbBackfillBatchRecord.id == batch.id)
            )
            if reloaded_checkpoint is None or reloaded_batch is None:
                raise RuntimeError("MLB backfill batch could not be reloaded")
            return reloaded_checkpoint, reloaded_batch, True
        except Exception:
            await self._session.rollback()
            raise


class MlbHistoricalBackfillWorkflowService:
    """Advance one audited regular-season batch without fitting or publishing probabilities."""

    def __init__(
        self,
        *,
        repository: MlbBackfillWorkflowRepository,
        backfill_service: MlbRetrospectiveBackfillService,
        feature_service: MlbGameFeatureService,
        policy: MlbHistoricalBackfillPolicy,
    ) -> None:
        self._repository = repository
        self._backfill_service = backfill_service
        self._feature_service = feature_service
        self._policy = policy

    @staticmethod
    def _cursor(
        checkpoint: MlbBackfillCheckpointRecord, split: MlbDatasetSplit
    ) -> tuple[date, int]:
        return (
            getattr(checkpoint, f"{split.value}_cursor_date"),
            getattr(checkpoint, f"{split.value}_cursor_offset"),
        )

    @staticmethod
    def _lower_bound(checkpoint: MlbBackfillCheckpointRecord, split: MlbDatasetSplit) -> date:
        if split is MlbDatasetSplit.TEST:
            return checkpoint.test_start_date
        if split is MlbDatasetSplit.VALIDATION:
            return checkpoint.validation_start_date
        return checkpoint.regular_season_start

    def _plan(
        self,
        checkpoint: MlbBackfillCheckpointRecord,
        readiness: MlbDatasetReadinessAssessment,
    ) -> MlbBackfillPlan | TerminalAction:
        if readiness.exploratory_fit_data_ready:
            return "complete"
        for split in self._policy.split_priority:
            if readiness.shortfall_by_split.get(split, 0) <= 0:
                continue
            cursor_date, offset = self._cursor(checkpoint, split)
            if cursor_date < self._lower_bound(checkpoint, split):
                return "exhausted"
            input_fingerprint = _hash(
                {
                    "checkpoint_id": str(checkpoint.id),
                    "checkpoint_state_fingerprint": checkpoint.state_fingerprint,
                    "policy_fingerprint": checkpoint.policy_fingerprint,
                    "split": split.value,
                    "window_date": cursor_date.isoformat(),
                    "offset": offset,
                    "limit": checkpoint.batch_limit,
                }
            )
            return MlbBackfillPlan(
                split=split,
                window_date=cursor_date,
                offset=offset,
                limit=checkpoint.batch_limit,
                input_fingerprint=input_fingerprint,
            )
        return "complete"

    async def run_once(self) -> MlbBackfillWorkflowRunResult:
        checkpoint = await self._repository.get_or_create_checkpoint(self._policy)
        readiness_before = await self._feature_service.approved_dataset_readiness()
        if checkpoint.status in {"complete", "exhausted"}:
            return MlbBackfillWorkflowRunResult(
                action=cast(TerminalAction, checkpoint.status),
                created=False,
                checkpoint=checkpoint,
                batch=None,
                readiness=readiness_before,
            )
        plan = self._plan(checkpoint, readiness_before)
        if isinstance(plan, str):
            checkpoint = await self._repository.finalize_checkpoint(
                checkpoint=checkpoint,
                status=plan,
            )
            return MlbBackfillWorkflowRunResult(
                action=plan,
                created=False,
                checkpoint=checkpoint,
                batch=None,
                readiness=readiness_before,
            )

        result = await self._backfill_service.run(
            start_date=plan.window_date,
            end_date=plan.window_date,
            limit=plan.limit,
            offset=plan.offset,
        )
        if result.result_counts.get("official_source_unavailable", 0) > 0:
            raise MlbBackfillWorkflowRetryableError(
                "official MLB or Baseball Savant source unavailable; cursor retained"
            )
        cursor_date_after = plan.window_date
        cursor_offset_after = plan.offset + plan.limit
        if result.examined < plan.limit:
            cursor_date_after = plan.window_date - timedelta(days=1)
            cursor_offset_after = 0
        readiness_after = await self._feature_service.approved_dataset_readiness()
        next_status: BackfillStatus = "active"
        if readiness_after.exploratory_fit_data_ready:
            next_status = "complete"
        elif cursor_date_after < self._lower_bound(checkpoint, plan.split):
            next_status = "exhausted"
        checkpoint_after, batch, created = await self._repository.persist_batch(
            checkpoint=checkpoint,
            plan=plan,
            cursor_date_after=cursor_date_after,
            cursor_offset_after=cursor_offset_after,
            result=result,
            readiness_before=readiness_before,
            readiness_after=readiness_after,
            next_status=next_status,
        )
        action: WorkflowAction = "ran_batch" if next_status == "active" else next_status
        return MlbBackfillWorkflowRunResult(
            action=action,
            created=created,
            checkpoint=checkpoint_after,
            batch=batch,
            readiness=readiness_after,
        )
