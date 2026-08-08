from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from itertools import batched
from uuid import UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload, selectinload

from app.domain.matching import MarketEventMatchDecision
from app.models.markets import PredictionMarketRecord
from app.models.matching import MarketEventMatchRecord
from app.models.sports import SportsEventRecord, TeamRecord

_LATM_MATCH_NAMESPACE = UUID("e8c924f5-88bf-4243-ae84-d45d4ebf86a2")
_MATCH_INSERT_BATCH_SIZE = 500


def match_record_id(decision: MarketEventMatchDecision) -> UUID:
    """Return a stable ID for one semantic matching attempt."""
    return uuid5(
        _LATM_MATCH_NAMESPACE,
        f"{decision.market_id}:{decision.matcher_version}:{decision.input_fingerprint}",
    )


class MatchingRepository:
    """Read normalized inputs and persist append-oriented matching attempts."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_markets_for_matching(
        self,
        *,
        reference_start: datetime,
        reference_end: datetime,
        market_id: UUID | None,
        limit: int,
        offset: int,
    ) -> list[PredictionMarketRecord]:
        """Return a deterministic bounded batch of NBA-discovery markets."""
        statement = (
            select(PredictionMarketRecord)
            .where(PredictionMarketRecord.is_nba.is_(True))
            .options(
                selectinload(PredictionMarketRecord.outcomes),
                noload(PredictionMarketRecord.prices),
            )
            .order_by(PredictionMarketRecord.id)
            .limit(limit)
            .offset(offset)
        )
        if market_id is not None:
            statement = statement.where(PredictionMarketRecord.id == market_id)
        else:
            reference_time = func.coalesce(
                PredictionMarketRecord.occurrence_time,
                PredictionMarketRecord.close_time,
            )
            statement = statement.where(
                reference_time >= reference_start,
                reference_time <= reference_end,
            )
        result = await self._session.scalars(statement)
        return list(result.unique().all())

    async def list_teams_for_matching(self, *, provider_name: str) -> list[TeamRecord]:
        """Return the configured provider's normalized NBA teams."""
        statement = (
            select(TeamRecord)
            .where(
                TeamRecord.provider_name == provider_name,
                TeamRecord.league == "nba",
            )
            .order_by(TeamRecord.id)
        )
        result = await self._session.scalars(statement)
        return list(result.all())

    async def list_events_for_matching(
        self,
        *,
        provider_name: str,
        start_date: date,
        end_date: date,
    ) -> list[SportsEventRecord]:
        """Return a date-bounded candidate event set without provider calls."""
        statement = (
            select(SportsEventRecord)
            .where(
                SportsEventRecord.provider_name == provider_name,
                SportsEventRecord.league == "nba",
                SportsEventRecord.event_date >= start_date,
                SportsEventRecord.event_date <= end_date,
            )
            .order_by(SportsEventRecord.id)
        )
        result = await self._session.scalars(statement)
        return list(result.unique().all())

    async def insert_decisions(self, decisions: Sequence[MarketEventMatchDecision]) -> int:
        """Insert new semantic decisions and ignore identical reruns."""
        if not decisions:
            return 0
        inserted = 0
        try:
            for batch in batched(decisions, _MATCH_INSERT_BATCH_SIZE, strict=False):
                values = [self._decision_values(decision) for decision in batch]
                statement = (
                    insert(MarketEventMatchRecord)
                    .values(values)
                    .on_conflict_do_nothing(constraint="uq_market_event_matches_semantic_input")
                    .returning(MarketEventMatchRecord.id)
                )
                result = await self._session.scalars(statement)
                inserted += len(result.all())
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        return inserted

    @staticmethod
    def _decision_values(decision: MarketEventMatchDecision) -> dict[str, object]:
        return {
            "id": match_record_id(decision),
            "market_id": decision.market_id,
            "sports_event_id": decision.sports_event_id,
            "status": decision.status.value,
            "confidence": decision.confidence,
            "method": decision.method,
            "reason": decision.reason,
            "matcher_version": decision.matcher_version,
            "min_confidence": decision.min_confidence,
            "ambiguity_margin": decision.ambiguity_margin,
            "time_window_hours": decision.time_window_hours,
            "automatic_trading_eligible": decision.automatic_trading_eligible,
            "input_fingerprint": decision.input_fingerprint,
            "team_signals": [signal.model_dump(mode="json") for signal in decision.team_signals],
            "candidate_scores": [
                candidate.model_dump(mode="json") for candidate in decision.candidate_scores
            ],
            "evidence": decision.evidence,
            "evaluated_at": decision.evaluated_at,
        }

    async def list_matches(
        self,
        *,
        latest_only: bool,
        match_status: str | None,
        market_id: UUID | None,
        sports_event_id: UUID | None,
        automatic_trading_eligible: bool | None,
        limit: int,
        offset: int,
    ) -> list[MarketEventMatchRecord]:
        """Return matching audit rows with optional latest-per-market semantics."""
        if latest_only:
            ranked = select(
                MarketEventMatchRecord.id.label("match_id"),
                func.row_number()
                .over(
                    partition_by=MarketEventMatchRecord.market_id,
                    order_by=(
                        MarketEventMatchRecord.evaluated_at.desc(),
                        MarketEventMatchRecord.id.desc(),
                    ),
                )
                .label("row_number"),
            ).subquery()
            statement = select(MarketEventMatchRecord).join(
                ranked,
                MarketEventMatchRecord.id == ranked.c.match_id,
            )
            statement = statement.where(ranked.c.row_number == 1)
        else:
            statement = select(MarketEventMatchRecord)

        if match_status is not None:
            statement = statement.where(MarketEventMatchRecord.status == match_status)
        if market_id is not None:
            statement = statement.where(MarketEventMatchRecord.market_id == market_id)
        if sports_event_id is not None:
            statement = statement.where(MarketEventMatchRecord.sports_event_id == sports_event_id)
        if automatic_trading_eligible is not None:
            statement = statement.where(
                MarketEventMatchRecord.automatic_trading_eligible == automatic_trading_eligible
            )
        statement = (
            statement.order_by(
                MarketEventMatchRecord.evaluated_at.desc(),
                MarketEventMatchRecord.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.scalars(statement)
        return list(result.all())

    async def get_match(self, match_id: UUID) -> MarketEventMatchRecord | None:
        """Return one historical matching attempt by ID."""
        result = await self._session.scalars(
            select(MarketEventMatchRecord).where(MarketEventMatchRecord.id == match_id)
        )
        return result.one_or_none()

    async def get_latest_market_match(self, market_id: UUID) -> MarketEventMatchRecord | None:
        """Return the newest matching attempt for one market."""
        statement = (
            select(MarketEventMatchRecord)
            .where(MarketEventMatchRecord.market_id == market_id)
            .order_by(
                MarketEventMatchRecord.evaluated_at.desc(),
                MarketEventMatchRecord.id.desc(),
            )
            .limit(1)
        )
        result = await self._session.scalars(statement)
        return result.one_or_none()
