from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import batched
from uuid import UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.domain.opportunities import OpportunityStatus
from app.domain.portfolio import (
    PortfolioDefinition,
    PortfolioSnapshot,
    PositionSizeProposal,
)
from app.models.forecasts import BaseForecastRecord
from app.models.markets import PredictionMarketRecord
from app.models.opportunities import OpportunityRecord
from app.models.portfolio import (
    PortfolioRecord,
    PortfolioSnapshotRecord,
    PositionSizeProposalRecord,
)
from app.models.sports import SportsEventRecord
from app.services.opportunities.repository import OpportunityRepository

_LATM_PORTFOLIO_NAMESPACE = UUID("08040afc-c43a-4db0-b8d2-55ad5af03b75")
_INSERT_BATCH_SIZE = 250


class PortfolioConflictError(ValueError):
    """Requested portfolio identity conflicts with an existing definition."""


@dataclass(frozen=True)
class PortfolioBundle:
    """Portfolio identity plus its authoritative newest balance snapshot."""

    portfolio: PortfolioRecord
    snapshot: PortfolioSnapshotRecord


@dataclass(frozen=True)
class CurrentOpportunityContext:
    """Current opportunity plus mutable semantics required for final sizing validation."""

    opportunity: OpportunityRecord
    market: PredictionMarketRecord
    event: SportsEventRecord
    forecast: BaseForecastRecord


@dataclass(frozen=True)
class ProposalPersistResult:
    """Atomic persistence counts, including candidates invalidated before insertion."""

    inserted: int
    invalidated: int


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def portfolio_record_id(idempotency_key: str) -> UUID:
    """Return a stable paper-portfolio ID for one client idempotency key."""
    return uuid5(_LATM_PORTFOLIO_NAMESPACE, f"portfolio:{idempotency_key}")


def portfolio_snapshot_record_id(portfolio_id: UUID, sequence: int) -> UUID:
    """Return a stable ledger-snapshot ID."""
    return uuid5(_LATM_PORTFOLIO_NAMESPACE, f"snapshot:{portfolio_id}:{sequence}")


def position_size_proposal_record_id(proposal: PositionSizeProposal) -> UUID:
    """Return a stable ID for one semantic advisory allocation."""
    return uuid5(
        _LATM_PORTFOLIO_NAMESPACE,
        f"proposal:{proposal.portfolio_snapshot_id}:{proposal.opportunity_id}:"
        f"{proposal.strategy_version}:{proposal.input_fingerprint}",
    )


def portfolio_creation_fingerprint(
    *, idempotency_key: str, name: str, starting_bankroll: object
) -> str:
    """Hash the immutable definition of a paper portfolio."""
    return _canonical_hash(
        {
            "idempotency_key": idempotency_key,
            "name": name,
            "mode": "paper",
            "currency": "USD",
            "starting_bankroll": str(starting_bankroll),
            "status": "active",
        }
    )


def portfolio_state_fingerprint(snapshot: PortfolioSnapshot) -> str:
    """Hash authoritative balance values without observation time."""
    payload = snapshot.model_dump(mode="json", exclude={"state_fingerprint", "captured_at"})
    return _canonical_hash(payload)


class PositionSizingRepository:
    """Persist paper portfolios and append-only advisory sizing proposals."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_portfolio(
        self,
        definition: PortfolioDefinition,
        initial_snapshot: PortfolioSnapshot,
    ) -> tuple[PortfolioBundle, bool]:
        """Create or idempotently return one immutable paper portfolio."""
        if definition.id != initial_snapshot.portfolio_id:
            raise ValueError("initial snapshot does not belong to the portfolio")
        inserted = False
        try:
            result = await self._session.scalars(
                insert(PortfolioRecord)
                .values(
                    id=definition.id,
                    idempotency_key=definition.idempotency_key,
                    name=definition.name,
                    execution_mode=definition.mode.value,
                    currency=definition.currency,
                    starting_bankroll=definition.starting_bankroll,
                    status=definition.status.value,
                    is_active=True,
                    creation_fingerprint=definition.creation_fingerprint,
                    created_at=definition.created_at,
                )
                .on_conflict_do_nothing(constraint="uq_portfolios_idempotency_key")
                .returning(PortfolioRecord.id)
            )
            inserted = bool(result.all())
            record = await self._session.scalar(
                select(PortfolioRecord).where(
                    PortfolioRecord.idempotency_key == definition.idempotency_key
                )
            )
            if record is None or record.creation_fingerprint != definition.creation_fingerprint:
                raise PortfolioConflictError(
                    "portfolio idempotency key already has a different definition"
                )
            await self._session.execute(
                insert(PortfolioSnapshotRecord)
                .values(self._snapshot_values(initial_snapshot))
                .on_conflict_do_nothing(constraint="uq_portfolio_snapshots_sequence")
            )
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise PortfolioConflictError("portfolio name is already in use") from exc
        except Exception:
            await self._session.rollback()
            raise
        bundle = await self.get_portfolio(definition.id)
        if bundle is None:
            raise RuntimeError("portfolio creation committed without a readable portfolio")
        return bundle, inserted

    @staticmethod
    def _snapshot_values(snapshot: PortfolioSnapshot) -> dict[str, object]:
        return {
            "id": snapshot.id,
            "portfolio_id": snapshot.portfolio_id,
            "sequence": snapshot.sequence,
            "execution_mode": snapshot.mode.value,
            "currency": snapshot.currency,
            "starting_bankroll": snapshot.starting_bankroll,
            "current_bankroll": snapshot.current_bankroll,
            "cash_balance": snapshot.cash_balance,
            "reserved_capital": snapshot.reserved_capital,
            "committed_capital": snapshot.committed_capital,
            "available_bankroll": snapshot.available_bankroll,
            "realized_pnl": snapshot.realized_pnl,
            "reason": snapshot.reason.value,
            "state_fingerprint": snapshot.state_fingerprint,
            "captured_at": snapshot.captured_at,
        }

    async def list_portfolios(self, *, limit: int, offset: int) -> list[PortfolioBundle]:
        """Return paper portfolios with the latest sequenced balance snapshot."""
        result = await self._session.scalars(
            select(PortfolioRecord)
            .order_by(PortfolioRecord.created_at, PortfolioRecord.id)
            .limit(limit)
            .offset(offset)
        )
        records = list(result.all())
        snapshots = await self._latest_snapshots([record.id for record in records])
        return [
            PortfolioBundle(record, snapshots[record.id])
            for record in records
            if record.id in snapshots
        ]

    async def get_portfolio(self, portfolio_id: UUID) -> PortfolioBundle | None:
        """Return one portfolio and its authoritative newest snapshot."""
        record = await self._session.scalar(
            select(PortfolioRecord).where(PortfolioRecord.id == portfolio_id)
        )
        if record is None:
            return None
        snapshots = await self._latest_snapshots([portfolio_id])
        snapshot = snapshots.get(portfolio_id)
        if snapshot is None:
            raise RuntimeError("portfolio is missing its initial balance snapshot")
        return PortfolioBundle(record, snapshot)

    async def _latest_snapshots(
        self, portfolio_ids: Sequence[UUID]
    ) -> dict[UUID, PortfolioSnapshotRecord]:
        if not portfolio_ids:
            return {}
        ranked = (
            select(
                PortfolioSnapshotRecord.id.label("record_id"),
                func.row_number()
                .over(
                    partition_by=PortfolioSnapshotRecord.portfolio_id,
                    order_by=(
                        PortfolioSnapshotRecord.sequence.desc(),
                        PortfolioSnapshotRecord.id.desc(),
                    ),
                )
                .label("row_number"),
            )
            .where(PortfolioSnapshotRecord.portfolio_id.in_(portfolio_ids))
            .subquery()
        )
        result = await self._session.scalars(
            select(PortfolioSnapshotRecord)
            .join(ranked, PortfolioSnapshotRecord.id == ranked.c.record_id)
            .where(ranked.c.row_number == 1)
        )
        return {record.portfolio_id: record for record in result.all()}

    async def list_portfolio_snapshots(
        self, *, portfolio_id: UUID, limit: int, offset: int
    ) -> list[PortfolioSnapshotRecord]:
        """Return immutable balance history ordered newest sequence first."""
        result = await self._session.scalars(
            select(PortfolioSnapshotRecord)
            .where(PortfolioSnapshotRecord.portfolio_id == portfolio_id)
            .order_by(
                PortfolioSnapshotRecord.sequence.desc(),
                PortfolioSnapshotRecord.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return list(result.all())

    async def list_current_opportunity_contexts(
        self,
        *,
        as_of: datetime,
        opportunity_id: UUID | None,
        limit: int,
        offset: int,
    ) -> list[CurrentOpportunityContext]:
        """Return current Phase 5 candidates plus semantics needed for sizing validation."""
        opportunities = await OpportunityRepository(self._session).list_opportunities(
            latest_only=True,
            current_only=True,
            current_at=as_of,
            status=OpportunityStatus.TRADE_CANDIDATE,
            direction=None,
            market_id=None,
            sports_event_id=None,
            model_name=None,
            model_version=None,
            opportunity_id=opportunity_id,
            limit=limit,
            offset=offset,
        )
        if not opportunities:
            return []
        market_ids = {item.market_id for item in opportunities}
        event_ids = {item.sports_event_id for item in opportunities}
        forecast_ids = {item.base_forecast_id for item in opportunities}
        markets_result = await self._session.scalars(
            select(PredictionMarketRecord)
            .where(PredictionMarketRecord.id.in_(market_ids))
            .options(selectinload(PredictionMarketRecord.outcomes))
        )
        events_result = await self._session.scalars(
            select(SportsEventRecord)
            .where(SportsEventRecord.id.in_(event_ids))
            .options(
                joinedload(SportsEventRecord.home_team),
                joinedload(SportsEventRecord.away_team),
            )
        )
        forecasts_result = await self._session.scalars(
            select(BaseForecastRecord).where(BaseForecastRecord.id.in_(forecast_ids))
        )
        markets = {item.id: item for item in markets_result.unique().all()}
        events = {item.id: item for item in events_result.unique().all()}
        forecasts = {item.id: item for item in forecasts_result.all()}
        return [
            CurrentOpportunityContext(
                opportunity=item,
                market=markets[item.market_id],
                event=events[item.sports_event_id],
                forecast=forecasts[item.base_forecast_id],
            )
            for item in opportunities
            if item.market_id in markets
            and item.sports_event_id in events
            and item.base_forecast_id in forecasts
        ]

    async def persist_proposals(
        self, proposals: Sequence[PositionSizeProposal]
    ) -> ProposalPersistResult:
        """Recheck source currentness and insert semantic proposals atomically."""
        if not proposals:
            return ProposalPersistResult(inserted=0, invalidated=0)
        valid: list[PositionSizeProposal] = []
        for proposal in proposals:
            current = await OpportunityRepository(self._session).list_opportunities(
                latest_only=True,
                current_only=True,
                current_at=proposal.proposed_at,
                status=OpportunityStatus.TRADE_CANDIDATE,
                direction=None,
                market_id=None,
                sports_event_id=None,
                model_name=None,
                model_version=None,
                opportunity_id=proposal.opportunity_id,
                limit=1,
                offset=0,
            )
            if current:
                valid.append(proposal)
        inserted = 0
        try:
            for batch in batched(valid, _INSERT_BATCH_SIZE, strict=False):
                result = await self._session.scalars(
                    insert(PositionSizeProposalRecord)
                    .values([self._proposal_values(proposal) for proposal in batch])
                    .on_conflict_do_nothing(constraint="uq_position_size_proposals_semantic_input")
                    .returning(PositionSizeProposalRecord.id)
                )
                inserted += len(result.all())
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        return ProposalPersistResult(
            inserted=inserted,
            invalidated=len(proposals) - len(valid),
        )

    @staticmethod
    def _proposal_values(proposal: PositionSizeProposal) -> dict[str, object]:
        values = proposal.model_dump(mode="python")
        values["id"] = position_size_proposal_record_id(proposal)
        values["execution_mode"] = proposal.mode.value
        values["state"] = proposal.state.value
        values["confidence_basis"] = proposal.confidence_basis.value
        del values["mode"]
        return values

    async def list_proposals(
        self,
        *,
        portfolio_id: UUID | None,
        opportunity_id: UUID | None,
        market_id: UUID | None,
        direction: str | None,
        strategy_version: str | None,
        limit: int,
        offset: int,
    ) -> list[PositionSizeProposalRecord]:
        """Return immutable advisory allocation history."""
        statement = select(PositionSizeProposalRecord)
        if portfolio_id is not None:
            statement = statement.where(PositionSizeProposalRecord.portfolio_id == portfolio_id)
        if opportunity_id is not None:
            statement = statement.where(PositionSizeProposalRecord.opportunity_id == opportunity_id)
        if market_id is not None:
            statement = statement.where(PositionSizeProposalRecord.market_id == market_id)
        if direction is not None:
            statement = statement.where(PositionSizeProposalRecord.direction == direction)
        if strategy_version is not None:
            statement = statement.where(
                PositionSizeProposalRecord.strategy_version == strategy_version
            )
        result = await self._session.scalars(
            statement.order_by(
                PositionSizeProposalRecord.proposed_at.desc(),
                PositionSizeProposalRecord.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return list(result.unique().all())

    async def get_proposal(self, proposal_id: UUID) -> PositionSizeProposalRecord | None:
        """Return one historical advisory allocation."""
        result = await self._session.scalars(
            select(PositionSizeProposalRecord).where(PositionSizeProposalRecord.id == proposal_id)
        )
        return result.unique().one_or_none()
