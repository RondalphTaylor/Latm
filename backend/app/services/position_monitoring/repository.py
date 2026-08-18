from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import PaperPositionRecord, PaperTradeRecord, PositionEventRecord
from app.models.forecasts import BaseForecastRecord
from app.models.markets import (
    MarketPriceRecord,
    MarketResolutionRecord,
    PredictionMarketRecord,
)
from app.models.matching import MarketEventMatchRecord
from app.models.portfolio import PortfolioRecord, PortfolioSnapshotRecord
from app.models.sports import SportsEventRecord


@dataclass(frozen=True)
class PositionLineage:
    """Immutable entry lineage used to establish the Phase 9 lock order."""

    position: PaperPositionRecord
    opening_trade: PaperTradeRecord
    opening_match: MarketEventMatchRecord
    opening_forecast: BaseForecastRecord


@dataclass(frozen=True)
class PositionMonitoringSources:
    """Latest persisted sources captured under their locked parent rows."""

    market: PredictionMarketRecord
    event: SportsEventRecord
    latest_match: MarketEventMatchRecord | None
    latest_price: MarketPriceRecord | None
    latest_forecast: BaseForecastRecord | None
    resolutions: tuple[MarketResolutionRecord, ...]

    @property
    def resolution_conflict(self) -> bool:
        assertions = {
            (item.result, item.yes_payout, item.no_payout, item.settled_at)
            for item in self.resolutions
        }
        return len(assertions) > 1

    @property
    def official_resolution(self) -> MarketResolutionRecord | None:
        if self.resolution_conflict or not self.resolutions:
            return None
        return self.resolutions[0]


@dataclass(frozen=True)
class PortfolioPositionTotals:
    """Aggregate current projection totals checked against the ledger head."""

    committed_capital: Decimal
    open_position_value: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal


class PositionMonitoringRepository:
    """Atomic persistence and fixed-order locking for paper position monitoring."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_position(self, position_id: UUID) -> PaperPositionRecord | None:
        return await self.session.get(PaperPositionRecord, position_id)

    async def get_lineage(self, position_id: UUID) -> PositionLineage | None:
        position = await self.get_position(position_id)
        if position is None:
            return None
        opening_trade = await self.session.get(PaperTradeRecord, position.opening_trade_id)
        if opening_trade is None:
            raise RuntimeError("position opening trade is missing")
        opening_match = await self.session.get(
            MarketEventMatchRecord,
            opening_trade.market_event_match_id,
        )
        opening_forecast = await self.session.get(
            BaseForecastRecord,
            opening_trade.base_forecast_id,
        )
        if opening_match is None or opening_forecast is None:
            raise RuntimeError("position opening source lineage is missing")
        return PositionLineage(
            position=position,
            opening_trade=opening_trade,
            opening_match=opening_match,
            opening_forecast=opening_forecast,
        )

    async def lock_portfolio(self, portfolio_id: UUID) -> PortfolioRecord | None:
        return cast(
            PortfolioRecord | None,
            await self.session.scalar(
                select(PortfolioRecord)
                .where(PortfolioRecord.id == portfolio_id)
                .with_for_update(of=PortfolioRecord)
            ),
        )

    async def lock_market(self, market_id: UUID) -> PredictionMarketRecord | None:
        return cast(
            PredictionMarketRecord | None,
            await self.session.scalar(
                select(PredictionMarketRecord)
                .where(PredictionMarketRecord.id == market_id)
                .with_for_update(of=PredictionMarketRecord)
            ),
        )

    async def lock_event(self, event_id: UUID) -> SportsEventRecord | None:
        return cast(
            SportsEventRecord | None,
            await self.session.scalar(
                select(SportsEventRecord)
                .where(SportsEventRecord.id == event_id)
                .with_for_update(of=SportsEventRecord)
            ),
        )

    async def lock_position(self, position_id: UUID) -> PaperPositionRecord | None:
        return cast(
            PaperPositionRecord | None,
            await self.session.scalar(
                select(PaperPositionRecord)
                .where(PaperPositionRecord.id == position_id)
                .with_for_update(of=PaperPositionRecord)
            ),
        )

    async def lock_latest_snapshot(self, portfolio_id: UUID) -> PortfolioSnapshotRecord | None:
        return cast(
            PortfolioSnapshotRecord | None,
            await self.session.scalar(
                select(PortfolioSnapshotRecord)
                .where(PortfolioSnapshotRecord.portfolio_id == portfolio_id)
                .order_by(
                    PortfolioSnapshotRecord.sequence.desc(),
                    PortfolioSnapshotRecord.id.desc(),
                )
                .limit(1)
                .with_for_update(of=PortfolioSnapshotRecord)
            ),
        )

    async def database_time(self) -> datetime:
        value = await self.session.scalar(select(func.clock_timestamp()))
        if value is None:
            raise RuntimeError("database did not return a monitoring timestamp")
        return cast(datetime, value)

    async def lock_sources(
        self,
        *,
        market: PredictionMarketRecord,
        event: SportsEventRecord,
        opening_forecast: BaseForecastRecord,
    ) -> PositionMonitoringSources:
        latest_match = cast(
            MarketEventMatchRecord | None,
            await self.session.scalar(
                select(MarketEventMatchRecord)
                .where(MarketEventMatchRecord.market_id == market.id)
                .order_by(
                    MarketEventMatchRecord.evaluated_at.desc(),
                    MarketEventMatchRecord.id.desc(),
                )
                .limit(1)
                .with_for_update(of=MarketEventMatchRecord)
            ),
        )
        latest_price = cast(
            MarketPriceRecord | None,
            await self.session.scalar(
                select(MarketPriceRecord)
                .where(MarketPriceRecord.market_id == market.id)
                .order_by(MarketPriceRecord.retrieved_at.desc(), MarketPriceRecord.id.desc())
                .limit(1)
                .with_for_update(of=MarketPriceRecord)
            ),
        )
        latest_forecast = cast(
            BaseForecastRecord | None,
            await self.session.scalar(
                select(BaseForecastRecord)
                .where(
                    BaseForecastRecord.sports_event_id == event.id,
                    BaseForecastRecord.model_version_id == opening_forecast.model_version_id,
                    BaseForecastRecord.purpose == "operational",
                )
                .order_by(BaseForecastRecord.generated_at.desc(), BaseForecastRecord.id.desc())
                .limit(1)
                .with_for_update(of=BaseForecastRecord)
            ),
        )
        resolution_result = await self.session.scalars(
            select(MarketResolutionRecord)
            .where(MarketResolutionRecord.market_id == market.id)
            .order_by(
                MarketResolutionRecord.settled_at.desc(),
                MarketResolutionRecord.retrieved_at.desc(),
                MarketResolutionRecord.id.desc(),
            )
            .with_for_update(of=MarketResolutionRecord)
        )
        return PositionMonitoringSources(
            market=market,
            event=event,
            latest_match=latest_match,
            latest_price=latest_price,
            latest_forecast=latest_forecast,
            resolutions=tuple(resolution_result.all()),
        )

    async def get_event_by_input(
        self,
        *,
        position_id: UUID,
        policy_version: str,
        input_fingerprint: str,
    ) -> PositionEventRecord | None:
        return cast(
            PositionEventRecord | None,
            await self.session.scalar(
                select(PositionEventRecord).where(
                    PositionEventRecord.position_id == position_id,
                    PositionEventRecord.policy_version == policy_version,
                    PositionEventRecord.input_fingerprint == input_fingerprint,
                )
            ),
        )

    async def portfolio_position_totals(self, portfolio_id: UUID) -> PortfolioPositionTotals:
        open_totals = (
            await self.session.execute(
                select(
                    func.coalesce(func.sum(PaperPositionRecord.total_cost_basis), 0),
                    func.coalesce(func.sum(PaperPositionRecord.market_value), 0),
                    func.coalesce(func.sum(PaperPositionRecord.unrealized_pnl), 0),
                ).where(
                    PaperPositionRecord.portfolio_id == portfolio_id,
                    PaperPositionRecord.status == "open",
                )
            )
        ).one()
        realized = await self.session.scalar(
            select(func.coalesce(func.sum(PaperPositionRecord.realized_pnl), 0)).where(
                PaperPositionRecord.portfolio_id == portfolio_id
            )
        )
        return PortfolioPositionTotals(
            committed_capital=Decimal(open_totals[0]),
            open_position_value=Decimal(open_totals[1]),
            unrealized_pnl=Decimal(open_totals[2]),
            realized_pnl=Decimal(realized or 0),
        )

    async def stage_event(
        self,
        *,
        event: PositionEventRecord,
        snapshot: PortfolioSnapshotRecord | None,
    ) -> None:
        """Flush a projection, event, and optional ledger state for final reconciliation."""
        await self.session.flush()
        if snapshot is not None:
            self.session.add(snapshot)
            await self.session.flush()
        self.session.add(event)
        await self.session.flush()

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def list_open_position_ids(
        self,
        *,
        portfolio_id: UUID | None,
        limit: int,
        offset: int,
    ) -> list[UUID]:
        statement = select(PaperPositionRecord.id).where(PaperPositionRecord.status == "open")
        if portfolio_id is not None:
            statement = statement.where(PaperPositionRecord.portfolio_id == portfolio_id)
        rows = await self.session.scalars(
            statement.order_by(PaperPositionRecord.id).limit(limit).offset(offset)
        )
        return list(rows.all())

    async def list_events(
        self,
        *,
        position_id: UUID | None,
        portfolio_id: UUID | None,
        market_id: UUID | None,
        decision: str | None,
        reason_code: str | None,
        policy_version: str | None,
        limit: int,
        offset: int,
    ) -> list[PositionEventRecord]:
        statement = select(PositionEventRecord)
        filters = (
            (PositionEventRecord.position_id, position_id),
            (PositionEventRecord.portfolio_id, portfolio_id),
            (PositionEventRecord.market_id, market_id),
            (PositionEventRecord.decision, decision),
            (PositionEventRecord.reason_code, reason_code),
            (PositionEventRecord.policy_version, policy_version),
        )
        for column, value in filters:
            if value is not None:
                statement = statement.where(column == value)
        rows = await self.session.scalars(
            statement.order_by(
                PositionEventRecord.evaluated_at.desc(),
                PositionEventRecord.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return list(rows.all())

    async def get_event(self, event_id: UUID) -> PositionEventRecord | None:
        return await self.session.get(PositionEventRecord, event_id)

    async def latest_event_for_position(self, position_id: UUID) -> PositionEventRecord | None:
        return cast(
            PositionEventRecord | None,
            await self.session.scalar(
                select(PositionEventRecord)
                .where(PositionEventRecord.position_id == position_id)
                .order_by(
                    PositionEventRecord.evaluated_at.desc(),
                    PositionEventRecord.id.desc(),
                )
                .limit(1)
            ),
        )

    async def get_snapshot(self, snapshot_id: UUID) -> PortfolioSnapshotRecord | None:
        return await self.session.get(PortfolioSnapshotRecord, snapshot_id)
