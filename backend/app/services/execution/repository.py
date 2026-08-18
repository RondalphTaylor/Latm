from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import PaperPositionRecord, PaperTradeRecord
from app.models.markets import PredictionMarketRecord
from app.models.opportunities import OpportunityRecord
from app.models.portfolio import (
    PortfolioRecord,
    PortfolioSnapshotRecord,
    PositionSizeProposalRecord,
)
from app.models.risk import RiskDecisionRecord
from app.models.sports import SportsEventRecord
from app.services.risk.repository import RiskEvaluationContext, RiskRepository


class PaperExecutionRepository:
    """Persistence boundary for atomic, provider-free paper execution."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_risk_decision(self, decision_id: UUID) -> RiskDecisionRecord | None:
        return await self.session.get(RiskDecisionRecord, decision_id)

    async def lock_portfolio(self, portfolio_id: UUID) -> PortfolioRecord | None:
        """Acquire the first and coarsest execution lock."""
        return cast(
            PortfolioRecord | None,
            await self.session.scalar(
                select(PortfolioRecord).where(PortfolioRecord.id == portfolio_id).with_for_update()
            ),
        )

    async def database_time(self) -> datetime:
        """Capture wall-clock time after any lock wait, not transaction start time."""
        value = await self.session.scalar(select(func.clock_timestamp()))
        if value is None:
            raise RuntimeError("database did not return an execution timestamp")
        return cast(datetime, value)

    async def lock_execution_parents(self, *, market_id: UUID, proposal_id: UUID) -> None:
        """Serialize child source inserts before capturing execution time."""
        market = await self.session.scalar(
            select(PredictionMarketRecord)
            .where(PredictionMarketRecord.id == market_id)
            .with_for_update(of=PredictionMarketRecord)
        )
        event = await self.session.scalar(
            select(SportsEventRecord)
            .join(OpportunityRecord, OpportunityRecord.sports_event_id == SportsEventRecord.id)
            .join(
                PositionSizeProposalRecord,
                PositionSizeProposalRecord.opportunity_id == OpportunityRecord.id,
            )
            .where(PositionSizeProposalRecord.id == proposal_id)
            .with_for_update(of=SportsEventRecord)
        )
        if market is None or event is None:
            raise RuntimeError("risk decision source parents are missing")

    async def lock_risk_decision(self, decision_id: UUID) -> RiskDecisionRecord | None:
        return cast(
            RiskDecisionRecord | None,
            await self.session.scalar(
                select(RiskDecisionRecord)
                .where(RiskDecisionRecord.id == decision_id)
                .with_for_update(of=RiskDecisionRecord)
            ),
        )

    async def get_risk_context(
        self, *, proposal_id: UUID, as_of: datetime
    ) -> RiskEvaluationContext | None:
        return await RiskRepository(self.session).get_evaluation_context(
            proposal_id=proposal_id,
            as_of=as_of,
        )

    async def get_trade_for_risk(self, risk_decision_id: UUID) -> PaperTradeRecord | None:
        return cast(
            PaperTradeRecord | None,
            await self.session.scalar(
                select(PaperTradeRecord).where(
                    PaperTradeRecord.risk_decision_id == risk_decision_id
                )
            ),
        )

    async def latest_risk_id(self, proposal_id: UUID) -> UUID | None:
        return cast(
            UUID | None,
            await self.session.scalar(
                select(RiskDecisionRecord.id)
                .where(RiskDecisionRecord.position_size_proposal_id == proposal_id)
                .order_by(RiskDecisionRecord.evaluated_at.desc(), RiskDecisionRecord.id.desc())
                .limit(1)
            ),
        )

    async def has_open_market_position(self, *, portfolio_id: UUID, market_id: UUID) -> bool:
        return (
            await self.session.scalar(
                select(PaperPositionRecord.id)
                .where(
                    PaperPositionRecord.portfolio_id == portfolio_id,
                    PaperPositionRecord.market_id == market_id,
                    PaperPositionRecord.status == "open",
                )
                .limit(1)
            )
            is not None
        )

    async def persist_rejection(self, trade: PaperTradeRecord) -> None:
        try:
            self.session.add(trade)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    async def persist_fill(
        self,
        *,
        snapshot: PortfolioSnapshotRecord,
        trade: PaperTradeRecord,
        position: PaperPositionRecord,
    ) -> None:
        """Commit the ledger, fill, and position as one financial transition."""
        try:
            self.session.add(snapshot)
            await self.session.flush()
            self.session.add(trade)
            await self.session.flush()
            self.session.add(position)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    async def list_trades(
        self,
        *,
        portfolio_id: UUID | None,
        market_id: UUID | None,
        risk_decision_id: UUID | None,
        status: str | None,
        direction: str | None,
        limit: int,
        offset: int,
    ) -> list[PaperTradeRecord]:
        statement = select(PaperTradeRecord)
        if portfolio_id is not None:
            statement = statement.where(PaperTradeRecord.portfolio_id == portfolio_id)
        if market_id is not None:
            statement = statement.where(PaperTradeRecord.market_id == market_id)
        if risk_decision_id is not None:
            statement = statement.where(PaperTradeRecord.risk_decision_id == risk_decision_id)
        if status is not None:
            statement = statement.where(PaperTradeRecord.status == status)
        if direction is not None:
            statement = statement.where(PaperTradeRecord.direction == direction)
        result = await self.session.scalars(
            statement.order_by(PaperTradeRecord.attempted_at.desc(), PaperTradeRecord.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.all())

    async def get_trade(self, trade_id: UUID) -> PaperTradeRecord | None:
        return await self.session.get(PaperTradeRecord, trade_id)

    async def list_positions(
        self,
        *,
        portfolio_id: UUID | None,
        market_id: UUID | None,
        status: str | None,
        direction: str | None,
        limit: int,
        offset: int,
    ) -> list[PaperPositionRecord]:
        statement = select(PaperPositionRecord)
        if portfolio_id is not None:
            statement = statement.where(PaperPositionRecord.portfolio_id == portfolio_id)
        if market_id is not None:
            statement = statement.where(PaperPositionRecord.market_id == market_id)
        if status is not None:
            statement = statement.where(PaperPositionRecord.status == status)
        if direction is not None:
            statement = statement.where(PaperPositionRecord.direction == direction)
        result = await self.session.scalars(
            statement.order_by(PaperPositionRecord.opened_at.desc(), PaperPositionRecord.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.all())

    async def get_position(self, position_id: UUID) -> PaperPositionRecord | None:
        return await self.session.get(PaperPositionRecord, position_id)

    async def get_position_for_trade(self, trade_id: UUID) -> PaperPositionRecord | None:
        return cast(
            PaperPositionRecord | None,
            await self.session.scalar(
                select(PaperPositionRecord).where(PaperPositionRecord.opening_trade_id == trade_id)
            ),
        )

    async def get_snapshot(self, snapshot_id: UUID) -> PortfolioSnapshotRecord | None:
        return await self.session.get(PortfolioSnapshotRecord, snapshot_id)
