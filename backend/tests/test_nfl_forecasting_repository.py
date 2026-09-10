from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.domain.nfl_shadow import NflShadowPrediction, NflShadowTarget
from app.models.forecasts import BaseForecastRecord
from app.models.markets import PredictionMarketRecord
from app.models.matching import MarketEventMatchRecord
from app.models.nfl_forecasting import NflPayoutForecastRecord
from app.models.nfl_shadow import NflShadowForecastRecord
from app.models.sports import SportsEventRecord
from app.services.nfl_forecasting.repository import NflPayoutForecastRepository
from app.services.nfl_research.baseline import NFL_BASELINE_VERSION, NflResearchGame
from app.services.nfl_research.repository import NflResearchRepository
from tests.test_nfl_shadow_repository import _prepare, _test_prediction, _test_seed


def _prediction(
    history: list[NflResearchGame], target: NflShadowTarget, as_of: datetime
) -> NflShadowPrediction:
    """Only model math is stubbed; real candidate validation/storage stay exercised."""
    fingerprint = hashlib.sha256(
        json.dumps(
            target.model_dump(mode="json", exclude={"source_last_seen"}),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return _test_prediction(history, target, as_of).model_copy(
        update={"baseline_version": NFL_BASELINE_VERSION, "target_fingerprint": fingerprint}
    )


@pytest.mark.parametrize("key", ["", " bad", "bad key", "x" * 101, "💥"])
def test_repository_rejects_invalid_request_key_before_database(key: str) -> None:
    with pytest.raises(ValueError, match="idempotency key"):
        asyncio.run(NflPayoutForecastRepository(cast(AsyncSession, None)).run(uuid4(), key))


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
                    match_id, market_id, event_id, kickoff = await _prepare(session)
                    repository = NflPayoutForecastRepository(session)
                    if fault == "stale_event":
                        await session.execute(
                            update(SportsEventRecord)
                            .where(SportsEventRecord.id == event_id)
                            .values(last_seen_at=kickoff - timedelta(days=2))
                        )
                        await session.commit()
                    if fault == "expiry_crossed":
                        captured: list[datetime] = []

                        async def clock() -> datetime:
                            if not captured:
                                now = await session.scalar(select(func.clock_timestamp()))
                                assert isinstance(now, datetime)
                                captured.append(now)
                                return now
                            return captured[0] + timedelta(minutes=16)

                        repository._now = clock  # type: ignore[method-assign]
                    if fault is not None:
                        with pytest.raises(ValueError):
                            await repository.run(match_id, "candidate-test")
                        assert (
                            await session.scalar(
                                select(func.count()).select_from(NflPayoutForecastRecord)
                            )
                            == 0
                        )
                        assert (
                            await session.scalar(
                                select(func.count()).select_from(NflShadowForecastRecord)
                            )
                            == 0
                        )
                        return
                    first, created = await repository.run(match_id, "candidate-test")
                    first_id, first_generated, first_expiry = (
                        first.id,
                        first.generated_at,
                        first.valid_until,
                    )
                    first_audit = first.audit
                    assert created and not first.operational_eligible and not first.trading_enabled
                    assert first.purpose == "paper_candidate" and first.promotion_state == "blocked"
                    assert first_expiry == first_generated + timedelta(minutes=15)
                    second, created = await repository.run(match_id, "candidate-test")
                    assert not created and second.id == first_id and second.audit == first_audit
                    newer, created = await repository.run(match_id, "candidate-test-new")
                    assert created and newer.id != first_id and newer.generated_at > first_generated
                    assert newer.source_shadow_snapshot_id == first.source_shadow_snapshot_id
                    assert (
                        await session.scalar(select(func.count()).select_from(BaseForecastRecord))
                        == 0
                    )
                    assert (
                        await session.scalar(
                            select(MarketEventMatchRecord.automatic_trading_eligible).where(
                                MarketEventMatchRecord.id == match_id
                            )
                        )
                        is False
                    )
                    # New key builds fresh inputs, not the older replayed shadow capture.
                    prediction = cast(dict[str, object], newer.audit["prediction"])
                    assert prediction["as_of"] == newer.generated_at.isoformat().replace(
                        "+00:00", "Z"
                    )
                    with pytest.raises(ValueError, match="another match"):
                        await repository.run(uuid4(), "candidate-test")
                    await session.execute(
                        update(PredictionMarketRecord)
                        .where(PredictionMarketRecord.id == market_id)
                        .values(status="closed")
                    )
                    await session.commit()
                    replay, created = await repository.run(match_id, "candidate-test")
                    assert (
                        not created
                        and replay.generated_at == first_generated
                        and replay.valid_until == first_expiry
                    )
                    with pytest.raises(ValueError, match="lifecycle gates"):
                        await repository.run(match_id, "candidate-new-closed")
                    loaded = await repository.get_forecast(first_id)
                    assert loaded is not None
                    first = loaded
                    assert len(await repository.list_forecasts(limit=10, offset=0)) == 2
                    await session.execute(
                        update(PredictionMarketRecord)
                        .where(PredictionMarketRecord.id == market_id)
                        .values(status="open")
                    )
                    await session.commit()
                    for statement in (
                        update(NflPayoutForecastRecord).values(trading_enabled=True),
                        delete(NflPayoutForecastRecord),
                    ):
                        with pytest.raises(DBAPIError, match="immutable"):
                            async with session.begin_nested():
                                await session.execute(statement)
                    values = {
                        column.name: getattr(first, column.name)
                        for column in NflPayoutForecastRecord.__table__.columns
                    }
                    values.update(id=uuid4(), idempotency_key="invalid-flag", trading_enabled=True)
                    with pytest.raises(IntegrityError, match="safety"):
                        async with session.begin_nested():
                            await session.execute(insert(NflPayoutForecastRecord).values(values))
                    values.update(
                        trading_enabled=False, event_id=uuid4(), idempotency_key="invalid-lineage"
                    )
                    with pytest.raises(DBAPIError, match="lineage"):
                        async with session.begin_nested():
                            await session.execute(insert(NflPayoutForecastRecord).values(values))
            finally:
                await outer.rollback()
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_INTEGRATION_TESTS") != "1",
    reason="requires isolated migrated PostgreSQL database",
)
@pytest.mark.parametrize("fault", [None, "stale_event", "builder_failure", "expiry_crossed"])
def test_candidate_atomic_storage_replay_and_failure_gates(
    monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    monkeypatch.setattr(NflResearchRepository, "select_games", _test_seed)
    monkeypatch.setattr(
        "app.services.nfl_research.shadow_repository.build_shadow_prediction", _prediction
    )
    monkeypatch.setattr(
        "app.services.nfl_forecasting.repository.build_shadow_prediction", _prediction
    )
    if fault == "builder_failure":

        def fail(**_: object) -> None:
            raise ValueError("test candidate builder failed")

        monkeypatch.setattr(
            "app.services.nfl_forecasting.repository.build_nfl_payout_forecast_candidate", fail
        )
    asyncio.run(_run(fault))
