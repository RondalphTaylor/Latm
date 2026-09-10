from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.domain.nfl_shadow import NflShadowPrediction, NflShadowTarget
from app.models.forecasts import BaseForecastRecord
from app.models.markets import MarketPriceRecord
from app.models.nfl_opportunities import NflPaperOpportunityRecord
from app.services.nfl_forecasting.repository import NflPayoutForecastRepository
from app.services.nfl_opportunities.repository import NflPaperOpportunityRepository
from app.services.nfl_research.baseline import NFL_BASELINE_VERSION, NflResearchGame
from app.services.nfl_research.repository import NflResearchRepository
from tests.test_nfl_shadow_repository import _prepare, _test_prediction, _test_seed


def _prediction(
    history: list[NflResearchGame], target: NflShadowTarget, as_of: datetime
) -> NflShadowPrediction:
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
                    match_id, market_id, _, _ = await _prepare(session)
                    forecast, created = await NflPayoutForecastRepository(session).run(
                        match_id, "opportunity-forecast"
                    )
                    assert created
                    now = await session.scalar(select(func.clock_timestamp()))
                    assert isinstance(now, datetime)
                    if fault != "no_quote":
                        price_time = now
                        if fault == "stale_quote":
                            price_time -= timedelta(minutes=16)
                        session.add(
                            MarketPriceRecord(
                                id=uuid4(),
                                market_id=market_id,
                                yes_bid=Decimal("0.45"),
                                yes_ask=Decimal("0.50"),
                                no_bid=Decimal("0.45"),
                                no_ask=Decimal("0.55"),
                                last_price=Decimal("0.50"),
                                volume=None,
                                volume_24h=None,
                                open_interest=None,
                                liquidity=None,
                                retrieved_at=price_time,
                            )
                        )
                        await session.commit()
                    repository = NflPaperOpportunityRepository(session)
                    first, created = await repository.run(forecast.id, "opportunity-test")
                    assert created
                    if fault == "no_quote":
                        assert first.price_id is None
                        assert first.yes_status == first.no_status == "ineligible"
                        assert first.valid_until is None
                    elif fault == "stale_quote":
                        assert first.yes_reason == first.no_reason == "stale_quote"
                        assert first.yes_raw_edge is first.no_raw_edge is None
                    else:
                        assert first.yes_status == "paper_candidate"
                        assert first.yes_raw_edge == Decimal("0.100000")
                        assert first.no_status == "ignore"
                        assert first.no_raw_edge == Decimal("-0.150000")
                        assert first.valid_until is not None
                    replay, created = await repository.run(forecast.id, "opportunity-test")
                    assert (
                        not created
                        and replay.id == first.id
                        and replay.valid_until == first.valid_until
                    )
                    with pytest.raises(ValueError, match="another forecast"):
                        await repository.run(UUID(int=999), "opportunity-test")
                    assert await repository.get_opportunity(first.id) is not None
                    assert len(await repository.list_opportunities(limit=10, offset=0)) == 1
                    assert (
                        await session.scalar(select(func.count()).select_from(BaseForecastRecord))
                        == 0
                    )
                    for statement in (
                        update(NflPaperOpportunityRecord).values(trading_enabled=True),
                        delete(NflPaperOpportunityRecord),
                    ):
                        with pytest.raises(DBAPIError, match="immutable"):
                            async with session.begin_nested():
                                await session.execute(statement)
                    values = {
                        column.name: getattr(first, column.name)
                        for column in NflPaperOpportunityRecord.__table__.columns
                    }
                    values.update(id=uuid4(), idempotency_key="invalid-flag", trading_enabled=True)
                    with pytest.raises(IntegrityError, match="safety"):
                        async with session.begin_nested():
                            await session.execute(insert(NflPaperOpportunityRecord).values(values))
                    values.update(
                        trading_enabled=False, event_id=uuid4(), idempotency_key="invalid-lineage"
                    )
                    with pytest.raises(DBAPIError, match="lineage"):
                        async with session.begin_nested():
                            await session.execute(insert(NflPaperOpportunityRecord).values(values))
            finally:
                await outer.rollback()
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_INTEGRATION_TESTS") != "1",
    reason="requires isolated migrated PostgreSQL database",
)
@pytest.mark.parametrize("fault", [None, "no_quote", "stale_quote"])
def test_nfl_paper_opportunity_storage_and_safety(
    monkeypatch: pytest.MonkeyPatch, fault: str | None
) -> None:
    monkeypatch.setattr(NflResearchRepository, "select_games", _test_seed)
    monkeypatch.setattr(
        "app.services.nfl_research.shadow_repository.build_shadow_prediction", _prediction
    )
    monkeypatch.setattr(
        "app.services.nfl_forecasting.repository.build_shadow_prediction", _prediction
    )
    asyncio.run(_run(fault))
