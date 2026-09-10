from __future__ import annotations

import asyncio
import importlib.util
import os
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.domain.nfl_shadow import NflShadowTarget
from app.models.nfl_shadow import NflShadowForecastRecord
from app.models.nfl_shadow_evaluation import NflShadowEvaluationRecord
from app.models.sports import SportsEventRecord
from app.services.nfl_research.repository import _select_records
from app.services.nfl_research.shadow_evaluation_repository import NflShadowEvaluationRepository
from tests.test_nfl_research_api import _record
from tests.test_nfl_shadow_repository import _prepare, _test_prediction


def _downgrade(connection: Connection) -> None:
    path = Path(__file__).parents[1] / "alembic/versions/0023_nfl_shadow_evaluations.py"
    spec = importlib.util.spec_from_file_location("shadow_label_test_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with Operations.context(MigrationContext.configure(connection)):
        migration.downgrade()


async def _seed(session: AsyncSession) -> tuple[UUID, UUID]:
    """Backdated synthetic snapshots exist only inside rollback-only test fixtures."""
    match_id, market_id, event_id, _ = await _prepare(session)
    now = await session.scalar(select(func.clock_timestamp()))
    assert isinstance(now, datetime)
    kickoff = now - timedelta(hours=2)
    generated = kickoff - timedelta(minutes=30)
    event = await session.get(SportsEventRecord, event_id)
    assert event is not None
    raw = dict(event.raw_data)
    raw["date"] = kickoff.isoformat()
    await session.execute(
        update(SportsEventRecord)
        .where(SportsEventRecord.id == event_id)
        .values(
            scheduled_start_time=kickoff,
            raw_data=raw,
        )
    )
    target = NflShadowTarget(
        event_id=event_id,
        provider_event_id=event.provider_event_id,
        season=2026,
        week=1,
        scheduled_start=kickoff,
        home_team_id=event.home_team_id,
        away_team_id=event.away_team_id,
        source_last_seen=generated - timedelta(minutes=1),
    )
    prediction = _test_prediction(
        list(_select_records([_record()], truncated=False).games), target, generated
    )
    snapshot_id = uuid4()
    await session.execute(
        insert(NflShadowForecastRecord).values(
            id=snapshot_id,
            match_id=match_id,
            market_id=market_id,
            sports_event_id=event_id,
            yes_team_id=event.away_team_id,
            model_version=prediction.config_version,
            seed_fingerprint=prediction.seed_fingerprint,
            input_fingerprint="1" * 64,
            generated_at=generated,
            scheduled_start_time=kickoff,
            target_source_last_seen_at=target.source_last_seen,
            expected_home_payout=prediction.expected_home_payout,
            expected_away_payout=prediction.expected_away_payout,
            expected_yes_payout=prediction.expected_away_payout,
            expected_no_payout=prediction.expected_home_payout,
            research_only=True,
            trading_enabled=False,
            audit={"prediction": prediction.model_dump(mode="json")},
        )
    )
    await session.commit()
    return snapshot_id, event_id


async def _final(session: AsyncSession, event_id: UUID, home: int, away: int) -> None:
    event = await session.get(SportsEventRecord, event_id)
    assert event is not None
    raw = dict(event.raw_data)
    raw.update(status="Final", status_state="final", home_team_score=home, visitor_team_score=away)
    now = await session.scalar(select(func.clock_timestamp()))
    await session.execute(
        update(SportsEventRecord)
        .where(SportsEventRecord.id == event_id)
        .values(
            status="final",
            status_detail="Final",
            home_score=home,
            away_score=away,
            raw_data=raw,
            last_seen_at=now,
        )
    )
    await session.commit()


async def _clone(session: AsyncSession, snapshot_id: UUID, *, seed: str | None = None) -> UUID:
    snapshot = await session.get(NflShadowForecastRecord, snapshot_id)
    assert snapshot is not None
    values = {
        column.name: getattr(snapshot, column.name)
        for column in NflShadowForecastRecord.__table__.columns
    }
    identity = uuid4()
    values.update(
        id=identity,
        input_fingerprint=identity.hex * 2,
        generated_at=snapshot.generated_at + timedelta(minutes=1),
    )
    if seed:
        audit = dict(snapshot.audit)
        prediction = dict(audit["prediction"])  # type: ignore[call-overload]
        prediction["seed_fingerprint"] = seed
        audit["prediction"] = prediction
        values.update(seed_fingerprint=seed, audit=audit)
    await session.execute(insert(NflShadowForecastRecord).values(values))
    await session.commit()
    return identity


async def _lifecycle(session: AsyncSession, snapshot_id: UUID, event_id: UUID) -> None:
    later = await _clone(session, snapshot_id)
    repository = NflShadowEvaluationRepository(session)
    pending = await repository.performance()
    assert (
        pending.total_snapshots == 2
        and pending.canonical_snapshots == 1
        and pending.pending_result == 1
    )
    with pytest.raises(ValueError, match="pending_result"):
        await repository.run(snapshot_id)
    await _final(session, event_id, 23, 20)
    await repository.run(later)
    after_later = await repository.performance()
    assert after_later.labeled == 0 and after_later.pending_label == 1
    first, created = await repository.run(snapshot_id)
    first_id = first.id
    assert created and first.actual_home_payout == 1 and first.actual_yes_payout == 0
    assert first.squared_home_payout_error == Decimal("0.160000000000")
    await _final(session, event_id, 23, 20)
    replay, created = await repository.run(snapshot_id)
    assert not created and replay.id == first_id
    assert (await repository.performance()).labeled == 1
    # A same-winner score correction still requires a new semantic result label.
    await _final(session, event_id, 24, 20)
    assert (await repository.performance()).pending_label == 1
    correction, created = await repository.run(snapshot_id)
    assert created and correction.result_fingerprint != first.result_fingerprint
    await _final(session, event_id, 20, 20)
    tie, created = await repository.run(snapshot_id)
    assert created and tie.actual_home_payout == Decimal("0.5")
    assert tie.actual_yes_payout == Decimal("0.5")
    assert (await repository.performance()).groups[0].tie_count == 1
    await _final(session, event_id, 23, 20)
    assert (await repository.performance()).labeled == 1
    reverted, created = await repository.run(snapshot_id)
    assert not created and reverted.id == first_id
    other_seed = await _clone(session, snapshot_id, seed="a" * 64)
    await repository.run(other_seed)
    groups = await repository.performance()
    assert groups.total_snapshots == 3 and groups.canonical_snapshots == 2 and groups.labeled == 2
    assert len(groups.groups) == 2 and all(group.count == 1 for group in groups.groups)
    connection = await session.connection()
    with pytest.raises(DBAPIError, match="downgrade refused"):
        async with connection.begin_nested():
            await connection.run_sync(_downgrade)
    for mutation in (
        update(NflShadowEvaluationRecord).values(trading_enabled=True),
        delete(NflShadowEvaluationRecord),
    ):
        with pytest.raises(DBAPIError, match="immutable"):
            async with session.begin_nested():
                await session.execute(mutation)
    label_values = {
        column.name: getattr(reverted, column.name)
        for column in NflShadowEvaluationRecord.__table__.columns
    }
    event = await session.get(SportsEventRecord, event_id)
    assert event is not None
    label_values.update(
        id=uuid4(),
        input_fingerprint="b" * 64,
        trading_enabled=True,
        result_source_last_seen_at=event.last_seen_at,
        label_time=await repository._now(),
    )
    with pytest.raises(IntegrityError, match="safety"):
        async with session.begin_nested():
            await session.execute(insert(NflShadowEvaluationRecord).values(label_values))
    label_values.update(trading_enabled=False, sports_event_id=uuid4())
    with pytest.raises(DBAPIError, match="lineage"):
        async with session.begin_nested():
            await session.execute(insert(NflShadowEvaluationRecord).values(label_values))
    # Changed target schedule invalidates ALL groups rather than choosing the later capture.
    await session.execute(
        update(SportsEventRecord)
        .where(SportsEventRecord.id == event_id)
        .values(scheduled_start_time=event.scheduled_start_time + timedelta(hours=1))
    )
    await session.commit()
    changed = await repository.performance()
    assert changed.labeled == 0 and changed.ineligible == 2


async def _run(fault: str | None) -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            outer = await connection.begin()
            try:
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    snapshot_id, event_id = await _seed(session)
                    if fault == "snapshot_cap":
                        await _clone(session, snapshot_id)
                        with pytest.raises(ValueError, match="snapshot_limit_exceeded"):
                            await NflShadowEvaluationRepository(session).performance()
                        return
                    if fault is None:
                        await _lifecycle(session, snapshot_id, event_id)
                        return
                    await _final(session, event_id, 23, 20)
                    if fault == "invalid_earliest":
                        await NflShadowEvaluationRepository(session).run(snapshot_id)
                        snapshot = await session.get(NflShadowForecastRecord, snapshot_id)
                        assert snapshot is not None
                        values = {
                            column.name: getattr(snapshot, column.name)
                            for column in NflShadowForecastRecord.__table__.columns
                        }
                        identity = uuid4()
                        values.update(
                            id=identity,
                            input_fingerprint=identity.hex * 2,
                            audit={},
                            generated_at=snapshot.generated_at - timedelta(seconds=1),
                        )
                        await session.execute(insert(NflShadowForecastRecord).values(values))
                        await session.commit()
                        performance = await NflShadowEvaluationRepository(session).performance()
                        assert performance.canonical_snapshots == 1
                        assert performance.labeled == 0 and performance.ineligible == 1
                        return
                    event = await session.get(SportsEventRecord, event_id)
                    assert event is not None
                    raw = dict(event.raw_data)
                    changes: dict[str, object] = {}
                    if fault == "missing_week":
                        del raw["week"]
                    elif fault == "changed_week":
                        raw["week"] = 2
                    elif fault == "conflicting_scores":
                        raw["home_team_score"] = 99
                    elif fault == "future_observation":
                        changes["last_seen_at"] = datetime.now(
                            event.last_seen_at.tzinfo
                        ) + timedelta(hours=1)
                    elif fault == "pre_kickoff_result":
                        changes["last_seen_at"] = event.scheduled_start_time - timedelta(seconds=1)
                    elif fault == "nonfinal_after_label":
                        await NflShadowEvaluationRepository(session).run(snapshot_id)
                        raw.update(
                            status="Scheduled",
                            status_state="scheduled",
                            home_team_score=None,
                            visitor_team_score=None,
                        )
                        changes.update(status="scheduled", home_score=None, away_score=None)
                    changes["raw_data"] = raw
                    await session.execute(
                        update(SportsEventRecord)
                        .where(SportsEventRecord.id == event_id)
                        .values(**changes)
                    )
                    await session.commit()
                    repository = NflShadowEvaluationRepository(session)
                    with pytest.raises(ValueError):
                        await repository.run(snapshot_id)
                    performance = await repository.performance()
                    assert performance.labeled == 0
                    if fault == "nonfinal_after_label":
                        assert performance.pending_result == 1
                    else:
                        assert performance.ineligible == 1
            finally:
                await outer.rollback()
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_INTEGRATION_TESTS") != "1",
    reason="requires isolated migrated PostgreSQL database",
)
@pytest.mark.parametrize(
    "fault",
    [
        None,
        "missing_week",
        "changed_week",
        "conflicting_scores",
        "future_observation",
        "pre_kickoff_result",
        "nonfinal_after_label",
        "snapshot_cap",
        "invalid_earliest",
    ],
)
def test_shadow_outcome_repository_replay_corrections_canonical_and_safety(
    fault: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if fault == "snapshot_cap":
        monkeypatch.setattr(
            "app.services.nfl_research.shadow_evaluation_repository.MAX_PERFORMANCE_SNAPSHOTS", 1
        )
    asyncio.run(_run(fault))
