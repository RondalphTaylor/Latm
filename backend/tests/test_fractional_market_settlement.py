from __future__ import annotations

import asyncio
import importlib.util
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy import Connection, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.domain.markets import BinaryMarketResolution, SettlementResult
from app.models.markets import MarketResolutionRecord
from app.schemas.markets import MarketResolutionResponse, MarketResponse
from app.services.markets.repository import MarketRepository, market_record_id
from tests.test_market_repository import normalized_market

SETTLED = datetime(2026, 8, 1, 11, tzinfo=UTC)


def _response(yes: str, no: str, result: str, resolution_type: str) -> MarketResolutionResponse:
    return MarketResolutionResponse.model_validate(
        {
            "id": uuid4(),
            "result": result,
            "yes_payout": yes,
            "no_payout": no,
            "resolution_type": resolution_type,
            "source": "official_provider",
            "settled_at": SETTLED,
            "retrieved_at": SETTLED + timedelta(hours=1),
            "input_fingerprint": "a" * 64,
        }
    )


@pytest.mark.parametrize("yes", ["0.500000", "0.400001", "0.000001", "0.999999"])
def test_fractional_api_keeps_exact_decimal_payout_and_scalar_result(yes: str) -> None:
    response = _response(yes, str(1 - Decimal(yes)), "scalar", "fractional_binary")
    assert response.result is SettlementResult.SCALAR
    assert response.yes_payout == Decimal(yes)
    assert response.model_dump(mode="json")["result"] == "scalar"


@pytest.mark.parametrize(
    ("yes", "no", "result", "kind"),
    [
        ("0", "1", "scalar", "fractional_binary"),
        ("1", "0", "scalar", "fractional_binary"),
        ("0.5", "0.5", "yes", "fractional_binary"),
        ("0.5", "0.5", "scalar", "standard_binary"),
        ("0.5000001", "0.4999999", "scalar", "fractional_binary"),
        ("0.4", "0.4", "scalar", "fractional_binary"),
    ],
)
def test_fractional_api_rejects_inconsistent_or_overprecise_payouts(
    yes: str, no: str, result: str, kind: str
) -> None:
    with pytest.raises(ValidationError):
        _response(yes, no, result, kind)


def _migration(connection: Connection, *, downgrade: bool) -> None:
    path = Path(__file__).parents[1] / "alembic/versions/0024_fractional_market_settlement.py"
    spec = importlib.util.spec_from_file_location("fractional_settlement_test_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(connection)):
        if downgrade:
            module.downgrade()
        else:
            module.upgrade()


async def _run_database_checks() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            outer = await connection.begin()
            try:
                await connection.run_sync(lambda conn: _migration(conn, downgrade=True))
                await connection.run_sync(lambda conn: _migration(conn, downgrade=False))
                async with AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                ) as session:
                    repository = MarketRepository(session)
                    base = normalized_market()
                    first = BinaryMarketResolution(
                        result=SettlementResult.SCALAR,
                        yes_payout=Decimal("0.5"),
                        no_payout=Decimal("0.5"),
                        resolution_type="fractional_binary",
                        settled_at=SETTLED,
                        retrieved_at=SETTLED + timedelta(hours=1),
                        source_snapshot={
                            "result": "scalar",
                            "settlement_value_dollars": "0.500000",
                        },
                    )
                    market = base.model_copy(update={"resolution": first, "status": "settled"})
                    await repository.upsert_markets([market])
                    refresh = market.model_copy(
                        update={
                            "resolution": first.model_copy(
                                update={"retrieved_at": SETTLED + timedelta(hours=2)}
                            )
                        }
                    )
                    await repository.upsert_markets([refresh])
                    assert (
                        await session.scalar(
                            select(func.count()).select_from(MarketResolutionRecord)
                        )
                        == 1
                    )
                    market_id = market_record_id(base.provider_name, base.provider_market_id)
                    stored = await repository.get_market(market_id)
                    assert stored is not None
                    response = MarketResponse.from_record(stored)
                    assert response.latest_resolution is not None
                    assert response.latest_resolution.result is SettlementResult.SCALAR
                    assert response.latest_resolution.yes_payout == Decimal("0.500000")
                    for result, yes, no, kind in (
                        (SettlementResult.SCALAR, "0.400001", "0.599999", "fractional_binary"),
                        (SettlementResult.YES, "1", "0", "standard_binary"),
                        (SettlementResult.NO, "0", "1", "standard_binary"),
                    ):
                        resolution = BinaryMarketResolution.model_validate(
                            {
                                "result": result,
                                "yes_payout": yes,
                                "no_payout": no,
                                "resolution_type": kind,
                                "settled_at": SETTLED,
                                "retrieved_at": SETTLED + timedelta(hours=2),
                                "source_snapshot": {},
                            }
                        )
                        await repository.upsert_markets(
                            [market.model_copy(update={"resolution": resolution})]
                        )
                    assert (
                        await session.scalar(
                            select(func.count()).select_from(MarketResolutionRecord)
                        )
                        == 4
                    )
                    for invalid_result, yes, no, kind in (
                        ("scalar", "0", "1", "fractional_binary"),
                        ("scalar", "1", "0", "fractional_binary"),
                        ("yes", "0.5", "0.5", "fractional_binary"),
                        ("scalar", "0.5", "0.5", "standard_binary"),
                        ("scalar", "0.4", "0.4", "fractional_binary"),
                    ):
                        with pytest.raises(IntegrityError):
                            async with session.begin_nested():
                                await session.execute(
                                    insert(MarketResolutionRecord).values(
                                        id=uuid4(),
                                        market_id=market_id,
                                        result=invalid_result,
                                        yes_payout=Decimal(yes),
                                        no_payout=Decimal(no),
                                        resolution_type=kind,
                                        source="official_provider",
                                        settled_at=SETTLED,
                                        retrieved_at=SETTLED + timedelta(hours=1),
                                        input_fingerprint=uuid4().hex * 2,
                                        source_snapshot={},
                                    )
                                )
                    for mutation in (
                        update(MarketResolutionRecord).values(yes_payout=Decimal("0.5")),
                        delete(MarketResolutionRecord),
                    ):
                        with pytest.raises(DBAPIError, match="immutable"):
                            async with session.begin_nested():
                                await session.execute(mutation)
                    await session.commit()
                    with pytest.raises(DBAPIError, match="downgrade refused"):
                        async with connection.begin_nested():
                            await connection.run_sync(lambda conn: _migration(conn, downgrade=True))
                    assert (
                        await session.scalar(
                            select(func.count()).select_from(MarketResolutionRecord)
                        )
                        == 4
                    )
            finally:
                await outer.rollback()
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("RUN_DATABASE_INTEGRATION_TESTS") != "1",
    reason="requires isolated migrated PostgreSQL database",
)
def test_fractional_settlement_persistence_replay_corrections_and_database_guards() -> None:
    asyncio.run(_run_database_checks())
