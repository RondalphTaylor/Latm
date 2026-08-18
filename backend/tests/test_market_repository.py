from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ClauseElement, Executable

from app.domain.markets import (
    BinaryMarketResolution,
    MarketOutcome,
    MarketPrice,
    OutcomeSide,
    PredictionMarket,
)
from app.services.markets.repository import (
    MarketRepository,
    market_record_id,
    market_resolution_fingerprint,
    market_resolution_record_id,
)


class RecordingSession:
    """Minimal async-session test double for statement and transaction assertions."""

    def __init__(self) -> None:
        self.statements: list[ClauseElement] = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement: Executable) -> None:
        self.statements.append(cast(ClauseElement, statement))

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def normalized_market() -> PredictionMarket:
    retrieved_at = datetime(2026, 8, 1, 12, tzinfo=UTC)
    return PredictionMarket(
        provider_name="kalshi",
        provider_market_id="KXNBAGAME-26AUG01BOSNYK-BOS",
        provider_event_id="KXNBAGAME-26AUG01BOSNYK",
        series_ticker="KXNBAGAME",
        category="Sports",
        market_type="binary",
        title="Boston Celtics at New York Knicks winner?",
        status="open",
        outcomes=(
            MarketOutcome(provider_outcome_id="yes", side=OutcomeSide.YES, label="Boston Celtics"),
            MarketOutcome(provider_outcome_id="no", side=OutcomeSide.NO, label="New York Knicks"),
        ),
        price=MarketPrice(
            yes_bid=Decimal("0.54"),
            yes_ask=Decimal("0.56"),
            retrieved_at=retrieved_at,
        ),
        raw_data={"market": {"ticker": "KXNBAGAME-26AUG01BOSNYK-BOS"}},
        retrieved_at=retrieved_at,
    )


def test_upsert_uses_stable_identities_and_idempotent_price_observations() -> None:
    session = RecordingSession()
    repository = MarketRepository(cast(AsyncSession, session))
    market = normalized_market()

    persisted = asyncio.run(repository.upsert_markets([market]))
    persisted_again = asyncio.run(repository.upsert_markets([market]))

    assert persisted == persisted_again == 1
    assert session.commits == 2
    assert session.rollbacks == 0
    assert len(session.statements) == 8
    assert market_record_id("kalshi", market.provider_market_id) == market_record_id(
        "kalshi", market.provider_market_id
    )
    price_sql = str(session.statements[3])
    assert "ON CONFLICT ON CONSTRAINT uq_market_prices_observation DO NOTHING" in price_sql


def test_upsert_batches_large_market_sets_below_driver_parameter_limit() -> None:
    session = RecordingSession()
    repository = MarketRepository(cast(AsyncSession, session))
    base_market = normalized_market()
    markets = [
        base_market.model_copy(
            update={
                "provider_market_id": f"KXNBAGAME-LARGE-{index}",
                "price": None,
            }
        )
        for index in range(501)
    ]

    persisted = asyncio.run(repository.upsert_markets(markets))

    assert persisted == 501
    assert session.commits == 1
    assert len(session.statements) == 6


def test_upsert_appends_official_resolution_by_stable_semantic_identity() -> None:
    session = RecordingSession()
    repository = MarketRepository(cast(AsyncSession, session))
    observed_at = datetime(2026, 8, 2, 2, tzinfo=UTC)
    settled_at = datetime(2026, 8, 2, 1, tzinfo=UTC)
    market = normalized_market().model_copy(
        update={
            "status": "finalized",
            "price": None,
            "resolution": BinaryMarketResolution(
                result=OutcomeSide.YES,
                yes_payout=Decimal("1"),
                no_payout=Decimal("0"),
                settled_at=settled_at,
                retrieved_at=observed_at,
                source_snapshot={"provider_result": "yes"},
            ),
            "retrieved_at": observed_at,
        }
    )

    persisted = asyncio.run(repository.upsert_markets([market]))
    persisted_again = asyncio.run(repository.upsert_markets([market]))

    fingerprint = market_resolution_fingerprint(market)
    assert persisted == persisted_again == 1
    assert fingerprint is not None
    market_id = market_record_id("kalshi", market.provider_market_id)
    assert market_resolution_record_id(market_id, fingerprint) == market_resolution_record_id(
        market_id, fingerprint
    )
    assert len(session.statements) == 8
    resolution_sql = str(session.statements[3])
    assert "INSERT INTO market_resolutions" in resolution_sql
    assert "uq_market_resolutions_semantic_input" in resolution_sql
