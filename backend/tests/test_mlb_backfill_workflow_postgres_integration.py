from __future__ import annotations

import asyncio
import os
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.domain.mlb_modeling import (
    MlbDatasetReadinessAssessment,
    MlbDatasetSplit,
    approved_mlb_historical_backfill_policy,
)
from app.models.mlb import MlbBackfillBatchRecord, MlbBackfillCheckpointRecord
from app.services.mlb_backfill_workflow import (
    MlbBackfillPlan,
    MlbBackfillWorkflowRepository,
)
from app.services.mlb_collection import MlbBackfillRunResult


def _readiness(test_count: int) -> MlbDatasetReadinessAssessment:
    minimums = {
        MlbDatasetSplit.TRAIN: 500,
        MlbDatasetSplit.VALIDATION: 150,
        MlbDatasetSplit.TEST: 150,
        MlbDatasetSplit.PROSPECTIVE_HOLDOUT: 200,
    }
    eligible = {
        MlbDatasetSplit.TRAIN: 0,
        MlbDatasetSplit.VALIDATION: 0,
        MlbDatasetSplit.TEST: test_count,
        MlbDatasetSplit.PROSPECTIVE_HOLDOUT: 0,
    }
    shortfalls = {split: minimums[split] - eligible[split] for split in minimums}
    return MlbDatasetReadinessAssessment(
        policy_name="mlb_dataset_readiness",
        policy_version="v1",
        policy_fingerprint="1" * 64,
        split_policy_fingerprint="2" * 64,
        minimum_split_counts=minimums,
        eligible_split_counts=eligible,
        shortfall_by_split=shortfalls,
        exploratory_fit_data_ready=False,
        prospective_evaluation_data_ready=False,
        blockers=tuple(
            f"{split.value}_shortfall:{count}" for split, count in shortfalls.items()
        ),
    )


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
                await session.execute(delete(MlbBackfillBatchRecord))
                await session.execute(delete(MlbBackfillCheckpointRecord))
                await session.commit()
                repository = MlbBackfillWorkflowRepository(session)
                policy = approved_mlb_historical_backfill_policy()
                checkpoint = await repository.get_or_create_checkpoint(policy)
                replayed_checkpoint = await repository.get_or_create_checkpoint(policy)
                assert replayed_checkpoint.id == checkpoint.id
                assert checkpoint.test_cursor_date == date(2026, 8, 22)
                assert checkpoint.status == "active"

                plan = MlbBackfillPlan(
                    split=MlbDatasetSplit.TEST,
                    window_date=date(2026, 8, 22),
                    offset=0,
                    limit=10,
                    input_fingerprint="3" * 64,
                )
                result = MlbBackfillRunResult(
                    start_date=plan.window_date,
                    end_date=plan.window_date,
                    run_at=datetime(2026, 8, 23, 12, tzinfo=UTC),
                    events_refreshed=15,
                    examined=0,
                    retrospective_vectors_built=0,
                    examples_labeled=0,
                    result_counts={},
                    events=(),
                )
                after, batch, created = await repository.persist_batch(
                    checkpoint=checkpoint,
                    plan=plan,
                    cursor_date_after=date(2026, 8, 21),
                    cursor_offset_after=0,
                    result=result,
                    readiness_before=_readiness(14),
                    readiness_after=_readiness(14),
                    next_status="active",
                )
                replay_after, replay_batch, replay_created = await repository.persist_batch(
                    checkpoint=checkpoint,
                    plan=plan,
                    cursor_date_after=date(2026, 8, 21),
                    cursor_offset_after=0,
                    result=result,
                    readiness_before=_readiness(14),
                    readiness_after=_readiness(14),
                    next_status="active",
                )

                assert created is True
                assert replay_created is False
                assert replay_batch.id == batch.id
                assert after.version == 1
                assert replay_after.version == 1
                assert after.test_cursor_date == date(2026, 8, 21)
                assert len(
                    await repository.list_batches(
                        checkpoint_id=checkpoint.id, limit=10, offset=0
                    )
                ) == 1

                with pytest.raises(IntegrityError):
                    async with session.begin_nested():
                        await session.execute(
                            update(MlbBackfillBatchRecord)
                            .where(MlbBackfillBatchRecord.id == batch.id)
                            .values(automatic_trading_eligible=True)
                        )
                        await session.flush()
        finally:
            await outer.rollback()
    await engine.dispose()


@pytest.mark.integration
def test_mlb_backfill_checkpoint_replay_and_safety_constraints() -> None:
    if os.environ.get("RUN_DATABASE_INTEGRATION_TESTS") != "1":
        pytest.skip("set RUN_DATABASE_INTEGRATION_TESTS=1 against a migrated test database")
    asyncio.run(_run_integration())
