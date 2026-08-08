from __future__ import annotations

from collections.abc import Sequence
from itertools import batched
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.markets import PredictionMarket
from app.models.markets import (
    MarketOutcomeRecord,
    MarketPriceRecord,
    PredictionMarketRecord,
    Provider,
)
from app.services.markets.filtering import is_likely_nba_market

_LATM_MARKET_NAMESPACE = UUID("2b1a53e9-5257-4bfd-94b2-65a16e111eb5")
_UPSERT_BATCH_SIZE = 500


def market_record_id(provider_name: str, provider_market_id: str) -> UUID:
    """Return a stable internal market ID for a provider identity."""
    return uuid5(_LATM_MARKET_NAMESPACE, f"market:{provider_name}:{provider_market_id}")


def outcome_record_id(market_id: UUID, provider_outcome_id: str) -> UUID:
    """Return a stable internal outcome ID for a provider identity."""
    return uuid5(_LATM_MARKET_NAMESPACE, f"outcome:{market_id}:{provider_outcome_id}")


def price_record_id(market_id: UUID, retrieved_at_iso: str) -> UUID:
    """Return an idempotent ID for one market observation timestamp."""
    return uuid5(_LATM_MARKET_NAMESPACE, f"price:{market_id}:{retrieved_at_iso}")


class MarketRepository:
    """Persist and query normalized prediction markets."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _upsert_providers(self, values: list[dict[str, object]]) -> None:
        provider_insert = insert(Provider).values(values)
        await self._session.execute(
            provider_insert.on_conflict_do_update(
                index_elements=[Provider.name],
                set_={
                    "display_name": provider_insert.excluded.display_name,
                    "is_read_only": True,
                },
            )
        )

    async def _upsert_market_values(self, values: list[dict[str, object]]) -> None:
        for batch in batched(values, _UPSERT_BATCH_SIZE, strict=False):
            market_insert = insert(PredictionMarketRecord).values(list(batch))
            update_columns = {
                column: getattr(market_insert.excluded, column)
                for column in (
                    "provider_event_id",
                    "series_ticker",
                    "category",
                    "market_type",
                    "title",
                    "subtitle",
                    "rules_primary",
                    "rules_secondary",
                    "status",
                    "is_nba",
                    "open_time",
                    "close_time",
                    "occurrence_time",
                    "provider_created_at",
                    "provider_updated_at",
                    "raw_data",
                    "last_seen_at",
                )
            }
            await self._session.execute(
                market_insert.on_conflict_do_update(
                    constraint="uq_markets_provider_market_id",
                    set_=update_columns,
                )
            )

    async def _upsert_outcome_values(self, values: list[dict[str, object]]) -> None:
        for batch in batched(values, _UPSERT_BATCH_SIZE, strict=False):
            outcome_insert = insert(MarketOutcomeRecord).values(list(batch))
            await self._session.execute(
                outcome_insert.on_conflict_do_update(
                    constraint="uq_market_outcomes_provider_outcome_id",
                    set_={
                        "side": outcome_insert.excluded.side,
                        "label": outcome_insert.excluded.label,
                    },
                )
            )

    async def _insert_price_values(self, values: list[dict[str, object]]) -> None:
        for batch in batched(values, _UPSERT_BATCH_SIZE, strict=False):
            price_insert = insert(MarketPriceRecord).values(list(batch))
            await self._session.execute(
                price_insert.on_conflict_do_nothing(constraint="uq_market_prices_observation")
            )

    async def upsert_markets(self, markets: Sequence[PredictionMarket]) -> int:
        """Upsert market identities and append distinct price observations."""
        if not markets:
            return 0

        provider_names = sorted({market.provider_name for market in markets})
        provider_values = [
            {
                "name": name,
                "display_name": "Kalshi" if name == "kalshi" else name.title(),
                "is_read_only": True,
            }
            for name in provider_names
        ]
        market_values: list[dict[str, object]] = []
        outcome_values: list[dict[str, object]] = []
        price_values: list[dict[str, object]] = []
        for market in markets:
            market_id = market_record_id(market.provider_name, market.provider_market_id)
            market_values.append(
                {
                    "id": market_id,
                    "provider_name": market.provider_name,
                    "provider_market_id": market.provider_market_id,
                    "provider_event_id": market.provider_event_id,
                    "series_ticker": market.series_ticker,
                    "category": market.category,
                    "market_type": market.market_type,
                    "title": market.title,
                    "subtitle": market.subtitle,
                    "rules_primary": market.rules_primary,
                    "rules_secondary": market.rules_secondary,
                    "status": market.status,
                    "is_nba": is_likely_nba_market(market),
                    "open_time": market.open_time,
                    "close_time": market.close_time,
                    "occurrence_time": market.occurrence_time,
                    "provider_created_at": market.provider_created_at,
                    "provider_updated_at": market.provider_updated_at,
                    "raw_data": market.raw_data,
                    "first_seen_at": market.retrieved_at,
                    "last_seen_at": market.retrieved_at,
                }
            )
            for outcome in market.outcomes:
                outcome_values.append(
                    {
                        "id": outcome_record_id(market_id, outcome.provider_outcome_id),
                        "market_id": market_id,
                        "provider_outcome_id": outcome.provider_outcome_id,
                        "side": outcome.side.value,
                        "label": outcome.label,
                    }
                )
            if market.price is not None:
                retrieved_at_iso = market.price.retrieved_at.isoformat()
                price_values.append(
                    {
                        "id": price_record_id(market_id, retrieved_at_iso),
                        "market_id": market_id,
                        "yes_bid": market.price.yes_bid,
                        "yes_ask": market.price.yes_ask,
                        "no_bid": market.price.no_bid,
                        "no_ask": market.price.no_ask,
                        "last_price": market.price.last_price,
                        "volume": market.price.volume,
                        "volume_24h": market.price.volume_24h,
                        "open_interest": market.price.open_interest,
                        "liquidity": market.price.liquidity,
                        "retrieved_at": market.price.retrieved_at,
                    }
                )

        try:
            await self._upsert_providers(provider_values)
            await self._upsert_market_values(market_values)
            if outcome_values:
                await self._upsert_outcome_values(outcome_values)
            if price_values:
                await self._insert_price_values(price_values)
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        return len(markets)

    async def list_markets(
        self,
        *,
        nba_only: bool,
        provider_name: str | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> list[PredictionMarketRecord]:
        """Return persisted markets with outcomes and price history."""
        statement = (
            select(PredictionMarketRecord)
            .options(
                selectinload(PredictionMarketRecord.outcomes),
                selectinload(PredictionMarketRecord.prices),
            )
            .order_by(PredictionMarketRecord.occurrence_time, PredictionMarketRecord.title)
            .limit(limit)
            .offset(offset)
        )
        if nba_only:
            statement = statement.where(PredictionMarketRecord.is_nba.is_(True))
        if provider_name is not None:
            statement = statement.where(PredictionMarketRecord.provider_name == provider_name)
        if status is not None:
            statement = statement.where(PredictionMarketRecord.status == status)
        result = await self._session.scalars(statement)
        return list(result.all())

    async def get_market(self, market_id: UUID) -> PredictionMarketRecord | None:
        """Return one persisted market by its internal stable ID."""
        statement = (
            select(PredictionMarketRecord)
            .where(PredictionMarketRecord.id == market_id)
            .options(
                selectinload(PredictionMarketRecord.outcomes),
                selectinload(PredictionMarketRecord.prices),
            )
        )
        result = await self._session.scalars(statement)
        return result.one_or_none()
