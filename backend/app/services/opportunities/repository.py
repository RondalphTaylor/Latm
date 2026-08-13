from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from itertools import batched
from uuid import UUID, uuid5

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.domain.opportunities import (
    OpportunityDecision,
    OpportunityDirection,
    OpportunityStatus,
)
from app.models.forecasts import BaseForecastRecord, ModelVersionRecord
from app.models.markets import MarketPriceRecord, PredictionMarketRecord
from app.models.matching import MarketEventMatchRecord
from app.models.opportunities import OpportunityRecord
from app.models.sports import SportsEventRecord

_LATM_OPPORTUNITY_NAMESPACE = UUID("cc3ab27f-f432-4eac-baa1-92ac73ca2e0c")
_INSERT_BATCH_SIZE = 500


@dataclass(frozen=True)
class OpportunitySourceBundle:
    """Newest local snapshots for one market, without unsafe fallback."""

    market: PredictionMarketRecord
    match: MarketEventMatchRecord | None
    price: MarketPriceRecord | None
    event: SportsEventRecord | None
    forecast: BaseForecastRecord | None


def opportunity_record_id(decision: OpportunityDecision) -> UUID:
    """Return a stable ID for one directional semantic comparison."""
    return uuid5(
        _LATM_OPPORTUNITY_NAMESPACE,
        f"opportunity:{decision.market_id}:{decision.direction.value}:"
        f"{decision.strategy_version}:{decision.input_fingerprint}",
    )


class OpportunityRepository:
    """Read current local evidence and append immutable opportunity history."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_source_bundles(
        self,
        *,
        start_date: date,
        end_date: date,
        market_id: UUID | None,
        model_name: str,
        model_version: str,
        limit: int,
        offset: int,
    ) -> list[OpportunitySourceBundle]:
        """Return bounded markets plus each newest related snapshot."""
        start_at = datetime.combine(start_date, time.min, tzinfo=UTC)
        end_exclusive = datetime.combine(end_date, time.max, tzinfo=UTC)
        reference_time = func.coalesce(
            PredictionMarketRecord.occurrence_time,
            PredictionMarketRecord.close_time,
        )
        market_statement = select(PredictionMarketRecord).where(
            PredictionMarketRecord.is_nba.is_(True),
            reference_time >= start_at,
            reference_time <= end_exclusive,
        )
        if market_id is not None:
            market_statement = market_statement.where(PredictionMarketRecord.id == market_id)
        market_statement = (
            market_statement.options(selectinload(PredictionMarketRecord.outcomes))
            .order_by(reference_time, PredictionMarketRecord.id)
            .limit(limit)
            .offset(offset)
        )
        market_result = await self._session.scalars(market_statement)
        markets = list(market_result.unique().all())
        if not markets:
            return []
        market_ids = [market.id for market in markets]

        matches = await self._latest_matches(market_ids)
        prices = await self._latest_prices(market_ids)
        event_ids = {
            match.sports_event_id for match in matches.values() if match.sports_event_id is not None
        }
        events = await self._events(event_ids)
        forecasts = await self._latest_forecasts(
            event_ids,
            model_name=model_name,
            model_version=model_version,
        )
        bundles: list[OpportunitySourceBundle] = []
        for market in markets:
            match = matches.get(market.id)
            event_id = match.sports_event_id if match is not None else None
            bundles.append(
                OpportunitySourceBundle(
                    market=market,
                    match=match,
                    price=prices.get(market.id),
                    event=events.get(event_id) if event_id is not None else None,
                    forecast=forecasts.get(event_id) if event_id is not None else None,
                )
            )
        return bundles

    async def _latest_matches(
        self, market_ids: Sequence[UUID]
    ) -> dict[UUID, MarketEventMatchRecord]:
        ranked = (
            select(
                MarketEventMatchRecord.id.label("record_id"),
                func.row_number()
                .over(
                    partition_by=MarketEventMatchRecord.market_id,
                    order_by=(
                        MarketEventMatchRecord.evaluated_at.desc(),
                        MarketEventMatchRecord.id.desc(),
                    ),
                )
                .label("row_number"),
            )
            .where(MarketEventMatchRecord.market_id.in_(market_ids))
            .subquery()
        )
        result = await self._session.scalars(
            select(MarketEventMatchRecord)
            .join(ranked, MarketEventMatchRecord.id == ranked.c.record_id)
            .where(ranked.c.row_number == 1)
        )
        return {record.market_id: record for record in result.all()}

    async def _latest_prices(self, market_ids: Sequence[UUID]) -> dict[UUID, MarketPriceRecord]:
        ranked = (
            select(
                MarketPriceRecord.id.label("record_id"),
                func.row_number()
                .over(
                    partition_by=MarketPriceRecord.market_id,
                    order_by=(MarketPriceRecord.retrieved_at.desc(), MarketPriceRecord.id.desc()),
                )
                .label("row_number"),
            )
            .where(MarketPriceRecord.market_id.in_(market_ids))
            .subquery()
        )
        result = await self._session.scalars(
            select(MarketPriceRecord)
            .join(ranked, MarketPriceRecord.id == ranked.c.record_id)
            .where(ranked.c.row_number == 1)
        )
        return {record.market_id: record for record in result.all()}

    async def _events(self, event_ids: set[UUID]) -> dict[UUID, SportsEventRecord]:
        if not event_ids:
            return {}
        result = await self._session.scalars(
            select(SportsEventRecord).where(SportsEventRecord.id.in_(event_ids))
        )
        return {record.id: record for record in result.unique().all()}

    async def _latest_forecasts(
        self,
        event_ids: set[UUID],
        *,
        model_name: str,
        model_version: str,
    ) -> dict[UUID, BaseForecastRecord]:
        if not event_ids:
            return {}
        ranked = (
            select(
                BaseForecastRecord.id.label("record_id"),
                func.row_number()
                .over(
                    partition_by=BaseForecastRecord.sports_event_id,
                    order_by=(BaseForecastRecord.generated_at.desc(), BaseForecastRecord.id.desc()),
                )
                .label("row_number"),
            )
            .join(ModelVersionRecord)
            .where(
                BaseForecastRecord.sports_event_id.in_(event_ids),
                BaseForecastRecord.purpose == "operational",
                ModelVersionRecord.model_name == model_name,
                ModelVersionRecord.model_version == model_version,
            )
            .subquery()
        )
        result = await self._session.scalars(
            select(BaseForecastRecord)
            .join(ranked, BaseForecastRecord.id == ranked.c.record_id)
            .where(ranked.c.row_number == 1)
            .options(joinedload(BaseForecastRecord.model_version))
        )
        return {record.sports_event_id: record for record in result.unique().all()}

    async def persist_opportunities(self, decisions: Sequence[OpportunityDecision]) -> int:
        """Insert new semantic comparisons atomically and ignore exact reruns."""
        inserted = 0
        try:
            for batch in batched(decisions, _INSERT_BATCH_SIZE, strict=False):
                result = await self._session.scalars(
                    insert(OpportunityRecord)
                    .values([self._record_values(decision) for decision in batch])
                    .on_conflict_do_nothing(constraint="uq_opportunities_semantic_input")
                    .returning(OpportunityRecord.id)
                )
                inserted += len(result.all())
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        return inserted

    @staticmethod
    def _record_values(decision: OpportunityDecision) -> dict[str, object]:
        values = decision.model_dump(mode="python")
        values["id"] = opportunity_record_id(decision)
        values["direction"] = decision.direction.value
        values["price_source"] = decision.price_source.value
        values["status"] = decision.status.value
        return values

    async def list_opportunities(
        self,
        *,
        latest_only: bool,
        current_only: bool,
        current_at: datetime | None,
        status: OpportunityStatus | None,
        direction: OpportunityDirection | None,
        market_id: UUID | None,
        sports_event_id: UUID | None,
        model_name: str | None,
        model_version: str | None,
        opportunity_id: UUID | None,
        limit: int,
        offset: int,
    ) -> list[OpportunityRecord]:
        """Return current or historical research classifications."""
        if latest_only:
            ranked = select(
                OpportunityRecord.id.label("record_id"),
                func.row_number()
                .over(
                    partition_by=(
                        OpportunityRecord.market_id,
                        OpportunityRecord.direction,
                        OpportunityRecord.strategy_name,
                        OpportunityRecord.strategy_version,
                        OpportunityRecord.model_version_id,
                    ),
                    order_by=(OpportunityRecord.evaluated_at.desc(), OpportunityRecord.id.desc()),
                )
                .label("row_number"),
            ).subquery()
            statement = (
                select(OpportunityRecord)
                .join(ranked, OpportunityRecord.id == ranked.c.record_id)
                .where(ranked.c.row_number == 1)
            )
        else:
            statement = select(OpportunityRecord)
        statement = statement.join(ModelVersionRecord).options(
            joinedload(OpportunityRecord.model_version)
        )
        if current_only:
            current_time = current_at if current_at is not None else func.now()
            latest_price_id = (
                select(MarketPriceRecord.id)
                .where(MarketPriceRecord.market_id == OpportunityRecord.market_id)
                .order_by(MarketPriceRecord.retrieved_at.desc(), MarketPriceRecord.id.desc())
                .limit(1)
                .correlate(OpportunityRecord)
                .scalar_subquery()
            )
            latest_match_id = (
                select(MarketEventMatchRecord.id)
                .where(MarketEventMatchRecord.market_id == OpportunityRecord.market_id)
                .order_by(
                    MarketEventMatchRecord.evaluated_at.desc(),
                    MarketEventMatchRecord.id.desc(),
                )
                .limit(1)
                .correlate(OpportunityRecord)
                .scalar_subquery()
            )
            latest_forecast_id = (
                select(BaseForecastRecord.id)
                .where(
                    BaseForecastRecord.sports_event_id == OpportunityRecord.sports_event_id,
                    BaseForecastRecord.model_version_id == OpportunityRecord.model_version_id,
                    BaseForecastRecord.purpose == "operational",
                )
                .order_by(BaseForecastRecord.generated_at.desc(), BaseForecastRecord.id.desc())
                .limit(1)
                .correlate(OpportunityRecord)
                .scalar_subquery()
            )
            statement = (
                statement.join(
                    PredictionMarketRecord,
                    PredictionMarketRecord.id == OpportunityRecord.market_id,
                )
                .join(
                    SportsEventRecord,
                    SportsEventRecord.id == OpportunityRecord.sports_event_id,
                )
                .where(
                    OpportunityRecord.valid_until >= current_time,
                    OpportunityRecord.market_price_id == latest_price_id,
                    OpportunityRecord.market_event_match_id == latest_match_id,
                    OpportunityRecord.base_forecast_id == latest_forecast_id,
                    PredictionMarketRecord.status.in_(("active", "open")),
                    or_(
                        PredictionMarketRecord.close_time.is_(None),
                        PredictionMarketRecord.close_time > current_time,
                    ),
                    SportsEventRecord.status == "scheduled",
                    SportsEventRecord.postponed.is_(False),
                    SportsEventRecord.scheduled_start_time > current_time,
                )
            )
        if status is not None:
            statement = statement.where(OpportunityRecord.status == status.value)
        if direction is not None:
            statement = statement.where(OpportunityRecord.direction == direction.value)
        if market_id is not None:
            statement = statement.where(OpportunityRecord.market_id == market_id)
        if sports_event_id is not None:
            statement = statement.where(OpportunityRecord.sports_event_id == sports_event_id)
        if model_name is not None:
            statement = statement.where(ModelVersionRecord.model_name == model_name)
        if model_version is not None:
            statement = statement.where(ModelVersionRecord.model_version == model_version)
        if opportunity_id is not None:
            statement = statement.where(OpportunityRecord.id == opportunity_id)
        statement = (
            statement.order_by(OpportunityRecord.evaluated_at.desc(), OpportunityRecord.id.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.scalars(statement)
        return list(result.unique().all())

    async def get_opportunity(self, opportunity_id: UUID) -> OpportunityRecord | None:
        """Return one immutable research classification."""
        result = await self._session.scalars(
            select(OpportunityRecord)
            .where(OpportunityRecord.id == opportunity_id)
            .options(joinedload(OpportunityRecord.model_version))
        )
        return result.unique().one_or_none()
