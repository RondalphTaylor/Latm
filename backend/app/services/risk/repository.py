from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.domain.opportunities import OpportunityStatus
from app.domain.risk import RiskDecision, RiskDecisionType
from app.models.forecasts import BaseForecastRecord
from app.models.markets import MarketPriceRecord, PredictionMarketRecord
from app.models.matching import MarketEventMatchRecord
from app.models.opportunities import OpportunityRecord
from app.models.portfolio import (
    PortfolioRecord,
    PortfolioSnapshotRecord,
    PositionSizeProposalRecord,
)
from app.models.risk import RiskDecisionRecord
from app.models.sports import SportsEventRecord
from app.services.opportunities.repository import OpportunityRepository

_LATM_RISK_NAMESPACE = UUID("f2958940-776d-4c34-ae80-f43878993559")


@dataclass(frozen=True)
class RiskEvaluationContext:
    """Proposal plus authoritative state loaded under its portfolio lock."""

    proposal: PositionSizeProposalRecord
    portfolio: PortfolioRecord
    proposal_snapshot: PortfolioSnapshotRecord
    latest_snapshot: PortfolioSnapshotRecord
    opportunity: OpportunityRecord
    market: PredictionMarketRecord
    event: SportsEventRecord
    source_match: MarketEventMatchRecord
    latest_match: MarketEventMatchRecord
    source_price: MarketPriceRecord
    latest_price: MarketPriceRecord
    source_forecast: BaseForecastRecord
    latest_forecast: BaseForecastRecord
    opportunity_is_current: bool
    current_authorized_capital: Decimal
    duplicate_active_intent_exists: bool


@dataclass(frozen=True)
class RiskPersistResult:
    """Idempotent risk-decision persistence result."""

    record: RiskDecisionRecord
    created: bool


def risk_decision_record_id(decision: RiskDecision) -> UUID:
    """Return the stable ID for one proposal, policy, and semantic risk state."""
    return uuid5(
        _LATM_RISK_NAMESPACE,
        f"risk:{decision.position_size_proposal_id}:{decision.risk_policy_version}:"
        f"{decision.input_fingerprint}",
    )


class RiskRepository:
    """Load locked risk inputs and persist immutable authorization evidence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def portfolio_exists(self, portfolio_id: UUID) -> bool:
        """Return whether a portfolio identity exists."""
        return (
            await self._session.scalar(
                select(PortfolioRecord.id).where(PortfolioRecord.id == portfolio_id)
            )
            is not None
        )

    async def get_latest_snapshot(self, portfolio_id: UUID) -> PortfolioSnapshotRecord | None:
        """Return the authoritative latest portfolio snapshot without locking it."""
        return cast(
            PortfolioSnapshotRecord | None,
            await self._session.scalar(
                select(PortfolioSnapshotRecord)
                .where(PortfolioSnapshotRecord.portfolio_id == portfolio_id)
                .order_by(
                    PortfolioSnapshotRecord.sequence.desc(),
                    PortfolioSnapshotRecord.id.desc(),
                )
                .limit(1)
            ),
        )

    async def list_proposal_ids(
        self,
        *,
        proposal_id: UUID | None,
        portfolio_id: UUID | None,
        limit: int,
        offset: int,
    ) -> list[UUID]:
        """Return a bounded deterministic proposal set for evaluation."""
        statement = select(PositionSizeProposalRecord.id)
        if proposal_id is not None:
            statement = statement.where(PositionSizeProposalRecord.id == proposal_id)
        if portfolio_id is not None:
            statement = statement.where(PositionSizeProposalRecord.portfolio_id == portfolio_id)
        result = await self._session.scalars(
            statement.order_by(
                PositionSizeProposalRecord.proposed_at,
                PositionSizeProposalRecord.id,
            )
            .limit(limit)
            .offset(offset)
        )
        return list(result.all())

    async def get_evaluation_context(
        self,
        *,
        proposal_id: UUID,
        as_of: datetime,
    ) -> RiskEvaluationContext | None:
        """Lock one portfolio and load exact plus current evidence for its proposal."""
        proposal_result = await self._session.scalars(
            select(PositionSizeProposalRecord).where(PositionSizeProposalRecord.id == proposal_id)
        )
        proposal = proposal_result.unique().one_or_none()
        if proposal is None:
            return None
        portfolio = await self._session.scalar(
            select(PortfolioRecord)
            .where(PortfolioRecord.id == proposal.portfolio_id)
            .with_for_update()
        )
        if portfolio is None:
            raise RuntimeError("proposal references a missing portfolio")
        proposal_snapshot = await self._session.scalar(
            select(PortfolioSnapshotRecord).where(
                PortfolioSnapshotRecord.id == proposal.portfolio_snapshot_id
            )
        )
        latest_snapshot = await self._session.scalar(
            select(PortfolioSnapshotRecord)
            .where(PortfolioSnapshotRecord.portfolio_id == proposal.portfolio_id)
            .order_by(
                PortfolioSnapshotRecord.sequence.desc(),
                PortfolioSnapshotRecord.id.desc(),
            )
            .limit(1)
        )
        if proposal_snapshot is None or latest_snapshot is None:
            raise RuntimeError("proposal references a missing portfolio snapshot")
        opportunity = await self._session.scalar(
            select(OpportunityRecord)
            .where(OpportunityRecord.id == proposal.opportunity_id)
            .options(joinedload(OpportunityRecord.model_version))
        )
        if opportunity is None:
            raise RuntimeError("proposal references a missing opportunity")
        market_result = await self._session.scalars(
            select(PredictionMarketRecord)
            .where(PredictionMarketRecord.id == proposal.market_id)
            .options(selectinload(PredictionMarketRecord.outcomes))
        )
        market = market_result.unique().one_or_none()
        event_result = await self._session.scalars(
            select(SportsEventRecord)
            .where(SportsEventRecord.id == opportunity.sports_event_id)
            .options(
                joinedload(SportsEventRecord.home_team),
                joinedload(SportsEventRecord.away_team),
            )
        )
        event = event_result.unique().one_or_none()
        source_match = await self._session.get(
            MarketEventMatchRecord,
            opportunity.market_event_match_id,
        )
        latest_match = await self._session.scalar(
            select(MarketEventMatchRecord)
            .where(MarketEventMatchRecord.market_id == proposal.market_id)
            .order_by(
                MarketEventMatchRecord.evaluated_at.desc(),
                MarketEventMatchRecord.id.desc(),
            )
            .limit(1)
        )
        source_price = await self._session.get(MarketPriceRecord, opportunity.market_price_id)
        latest_price = await self._session.scalar(
            select(MarketPriceRecord)
            .where(MarketPriceRecord.market_id == proposal.market_id)
            .order_by(MarketPriceRecord.retrieved_at.desc(), MarketPriceRecord.id.desc())
            .limit(1)
        )
        source_forecast = await self._session.get(
            BaseForecastRecord,
            opportunity.base_forecast_id,
        )
        latest_forecast = await self._session.scalar(
            select(BaseForecastRecord)
            .where(
                BaseForecastRecord.sports_event_id == opportunity.sports_event_id,
                BaseForecastRecord.model_version_id == opportunity.model_version_id,
                BaseForecastRecord.purpose == "operational",
            )
            .order_by(BaseForecastRecord.generated_at.desc(), BaseForecastRecord.id.desc())
            .limit(1)
        )
        if (
            market is None
            or event is None
            or source_match is None
            or latest_match is None
            or source_price is None
            or latest_price is None
            or source_forecast is None
            or latest_forecast is None
        ):
            raise RuntimeError("proposal source graph is incomplete")
        current = await OpportunityRepository(self._session).list_opportunities(
            latest_only=True,
            current_only=True,
            current_at=as_of,
            status=OpportunityStatus.TRADE_CANDIDATE,
            direction=None,
            market_id=None,
            sports_event_id=None,
            model_name=None,
            model_version=None,
            opportunity_id=opportunity.id,
            limit=1,
            offset=0,
        )
        authorized, duplicate = await self._current_authorization_state(
            proposal=proposal,
            snapshot_id=latest_snapshot.id,
            as_of=as_of,
        )
        return RiskEvaluationContext(
            proposal=proposal,
            portfolio=portfolio,
            proposal_snapshot=proposal_snapshot,
            latest_snapshot=latest_snapshot,
            opportunity=opportunity,
            market=market,
            event=event,
            source_match=source_match,
            latest_match=latest_match,
            source_price=source_price,
            latest_price=latest_price,
            source_forecast=source_forecast,
            latest_forecast=latest_forecast,
            opportunity_is_current=bool(current),
            current_authorized_capital=authorized,
            duplicate_active_intent_exists=duplicate,
        )

    async def _current_authorization_state(
        self,
        *,
        proposal: PositionSizeProposalRecord,
        snapshot_id: UUID,
        as_of: datetime,
    ) -> tuple[Decimal, bool]:
        ranked = (
            select(
                RiskDecisionRecord.id.label("record_id"),
                func.row_number()
                .over(
                    partition_by=RiskDecisionRecord.position_size_proposal_id,
                    order_by=(
                        RiskDecisionRecord.evaluated_at.desc(),
                        RiskDecisionRecord.id.desc(),
                    ),
                )
                .label("row_number"),
            )
            .where(
                RiskDecisionRecord.portfolio_id == proposal.portfolio_id,
                RiskDecisionRecord.authorization_valid_until > as_of,
                RiskDecisionRecord.portfolio_snapshot_id == snapshot_id,
                RiskDecisionRecord.position_size_proposal_id != proposal.id,
            )
            .subquery()
        )
        current_statement = (
            select(RiskDecisionRecord)
            .join(ranked, RiskDecisionRecord.id == ranked.c.record_id)
            .where(ranked.c.row_number == 1)
        )
        current = list((await self._session.scalars(current_statement)).unique().all())
        authorized = sum(
            (
                item.proposed_capital
                for item in current
                if item.decision == RiskDecisionType.AUTO_APPROVE.value
            ),
            start=Decimal("0.00"),
        )
        duplicate = any(
            item.decision
            in {
                RiskDecisionType.AUTO_APPROVE.value,
                RiskDecisionType.REQUIRE_HUMAN_APPROVAL.value,
            }
            and item.market_id == proposal.market_id
            and item.direction == proposal.direction
            and item.outcome_team_id == proposal.outcome_team_id
            for item in current
        )
        return authorized, duplicate

    async def persist_decision(
        self,
        decision: RiskDecision,
        context: RiskEvaluationContext,
    ) -> RiskPersistResult:
        """Insert one semantic decision and release the portfolio lock by committing."""
        decision_id = risk_decision_record_id(decision)
        values = decision.model_dump(mode="python")
        values.update(
            {
                "id": decision_id,
                "decision": decision.decision.value,
                "escalation_band": decision.escalation_band.value,
                "failed_rules": list(decision.failed_rules),
                "check_results": [item.model_dump(mode="json") for item in decision.check_results],
                "market_event_match_id": context.latest_match.id,
                "market_price_id": context.latest_price.id,
                "base_forecast_id": context.latest_forecast.id,
            }
        )
        try:
            result = await self._session.scalars(
                insert(RiskDecisionRecord)
                .values(values)
                .on_conflict_do_nothing(constraint="uq_risk_decisions_semantic_input")
                .returning(RiskDecisionRecord.id)
            )
            created = bool(result.all())
            record_result = await self._session.scalars(
                select(RiskDecisionRecord).where(RiskDecisionRecord.id == decision_id)
            )
            record = record_result.unique().one_or_none()
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        if record is None:
            raise RuntimeError("risk decision insert completed without a readable record")
        return RiskPersistResult(record=record, created=created)

    async def list_decisions(
        self,
        *,
        latest_only: bool,
        unexpired_only: bool,
        current_at: datetime,
        proposal_id: UUID | None,
        portfolio_id: UUID | None,
        market_id: UUID | None,
        decision: RiskDecisionType | None,
        risk_policy_version: str | None,
        limit: int,
        offset: int,
    ) -> list[RiskDecisionRecord]:
        """Return unexpired authorization views or immutable audit history."""
        if latest_only:
            ranked = select(
                RiskDecisionRecord.id.label("record_id"),
                func.row_number()
                .over(
                    partition_by=RiskDecisionRecord.position_size_proposal_id,
                    order_by=(
                        RiskDecisionRecord.evaluated_at.desc(),
                        RiskDecisionRecord.id.desc(),
                    ),
                )
                .label("row_number"),
            ).subquery()
            statement = (
                select(RiskDecisionRecord)
                .join(ranked, RiskDecisionRecord.id == ranked.c.record_id)
                .where(ranked.c.row_number == 1)
            )
        else:
            statement = select(RiskDecisionRecord)
        if unexpired_only:
            statement = statement.where(RiskDecisionRecord.authorization_valid_until > current_at)
        if proposal_id is not None:
            statement = statement.where(RiskDecisionRecord.position_size_proposal_id == proposal_id)
        if portfolio_id is not None:
            statement = statement.where(RiskDecisionRecord.portfolio_id == portfolio_id)
        if market_id is not None:
            statement = statement.where(RiskDecisionRecord.market_id == market_id)
        if decision is not None:
            statement = statement.where(RiskDecisionRecord.decision == decision.value)
        if risk_policy_version is not None:
            statement = statement.where(
                RiskDecisionRecord.risk_policy_version == risk_policy_version
            )
        result = await self._session.scalars(
            statement.order_by(
                RiskDecisionRecord.evaluated_at.desc(),
                RiskDecisionRecord.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return list(result.unique().all())

    async def get_decision(self, decision_id: UUID) -> RiskDecisionRecord | None:
        """Return one historical risk decision without implying current authority."""
        result = await self._session.scalars(
            select(RiskDecisionRecord).where(RiskDecisionRecord.id == decision_id)
        )
        return result.unique().one_or_none()
