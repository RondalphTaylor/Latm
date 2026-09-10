from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.domain.nfl_paper_preflight import NflPaperPreflightPolicy
from app.models.markets import MarketPriceRecord
from app.services.nfl_forecasting.repository import NflPayoutForecastRepository
from app.services.nfl_opportunities.repository import NflPaperOpportunityRepository
from app.services.nfl_preflights.repository import NflPaperPreflightRepository
from app.services.nfl_research.repository import NflResearchRepository
from tests.test_nfl_opportunities_repository import _prediction
from tests.test_nfl_shadow_repository import _prepare, _test_seed


async def _run() -> None:
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
                    forecast, _ = await NflPayoutForecastRepository(session).run(
                        match_id, "preflight-forecast"
                    )
                    now = await session.scalar(select(func.clock_timestamp()))
                    assert now is not None
                    session.add(
                        MarketPriceRecord(
                            id=uuid4(),
                            market_id=market_id,
                            yes_bid=Decimal(".2"),
                            yes_ask=Decimal(".3"),
                            no_bid=Decimal(".2"),
                            no_ask=Decimal(".75"),
                            last_price=Decimal(".3"),
                            volume=None,
                            volume_24h=None,
                            open_interest=None,
                            liquidity=None,
                            retrieved_at=now,
                        )
                    )
                    await session.commit()
                    opportunity, _ = await NflPaperOpportunityRepository(session).run(
                        forecast.id, "preflight-opportunity"
                    )
                    policy = NflPaperPreflightPolicy(
                        slippage_bps=Decimal("25"),
                        fee_bps=Decimal("50"),
                        minimum_adjusted_edge=Decimal(".03"),
                    )
                    first, created = await NflPaperPreflightRepository(session, policy).run(
                        opportunity.id, "yes", Decimal("10"), "preflight-review"
                    )
                    replay, created_again = await NflPaperPreflightRepository(session, policy).run(
                        opportunity.id, "yes", Decimal("10"), "preflight-review"
                    )
                    assert created and not created_again and replay.id == first.id
                    assert first.risk_decision == "reject" and not first.execution_enabled
                    assert first.quantity > 0 and first.adjusted_edge is not None
            finally:
                await outer.rollback()
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_INTEGRATION_TESTS") != "1",
    reason="requires isolated migrated PostgreSQL database",
)
def test_nfl_paper_preflight_persists_only_a_blocked_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(NflResearchRepository, "select_games", _test_seed)
    monkeypatch.setattr(
        "app.services.nfl_research.shadow_repository.build_shadow_prediction", _prediction
    )
    monkeypatch.setattr(
        "app.services.nfl_forecasting.repository.build_shadow_prediction", _prediction
    )
    asyncio.run(_run())
