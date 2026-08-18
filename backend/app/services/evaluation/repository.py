from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import cast
from uuid import UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlalchemy.sql.selectable import Subquery

from app.domain.forecast_evaluation import ForecastEvaluation, ForecastEvaluationInput
from app.domain.forecasts import ForecastPurpose
from app.models.evaluation import ForecastEvaluationRecord
from app.models.execution import PaperPositionRecord, PaperTradeRecord, PositionEventRecord
from app.models.forecasts import BaseForecastRecord, ModelVersionRecord
from app.models.opportunities import OpportunityRecord
from app.models.portfolio import (
    PortfolioRecord,
    PortfolioSnapshotRecord,
    PositionSizeProposalRecord,
)
from app.models.risk import RiskDecisionRecord
from app.models.sports import SportsEventRecord

_LATM_EVALUATION_NAMESPACE = UUID("af91497b-f12d-4b1e-b0de-c69b79a2c991")


def forecast_evaluation_record_id(evaluation: ForecastEvaluation) -> UUID:
    """Return the stable identity for one immutable forecast/outcome score."""
    return uuid5(
        _LATM_EVALUATION_NAMESPACE,
        f"forecast-evaluation:{evaluation.forecast_id}:"
        f"{evaluation.policy_version}:{evaluation.input_fingerprint}",
    )


@dataclass(frozen=True)
class ForecastEvaluationCandidate:
    """Latest selected forecast and the current normalized result row."""

    forecast: BaseForecastRecord
    event: SportsEventRecord


@dataclass(frozen=True)
class ForecastEvaluationPersistence:
    """Domain input and score needed to freeze one evaluation fact."""

    source: ForecastEvaluationInput
    evaluation: ForecastEvaluation
    event_date: date


@dataclass(frozen=True)
class TradingPositionLineage:
    """One current position with its immutable entry policy lineage."""

    position: PaperPositionRecord
    trade: PaperTradeRecord
    opportunity: OpportunityRecord
    proposal: PositionSizeProposalRecord
    risk_decision: RiskDecisionRecord
    forecast: BaseForecastRecord
    model_version: ModelVersionRecord
    events: tuple[PositionEventRecord, ...]


@dataclass(frozen=True)
class TradingPerformanceSources:
    """Portfolio-locked sources anchored to one immutable ledger head."""

    portfolio: PortfolioRecord
    snapshots: tuple[PortfolioSnapshotRecord, ...]
    positions: tuple[TradingPositionLineage, ...]
    fallback_snapshot_ids: frozenset[UUID]
    evaluated_at: datetime


class EvaluationRepository:
    """Read immutable evaluation sources and persist forecast score facts."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def database_time(self) -> datetime:
        value = await self.session.scalar(select(func.clock_timestamp()))
        if value is None:
            raise RuntimeError("database did not return an evaluation timestamp")
        return cast(datetime, value)

    @staticmethod
    def _ranked_forecasts(*, purpose: ForecastPurpose) -> Subquery:
        return (
            select(
                BaseForecastRecord.id.label("forecast_id"),
                func.row_number()
                .over(
                    partition_by=(
                        BaseForecastRecord.sports_event_id,
                        BaseForecastRecord.model_version_id,
                        BaseForecastRecord.purpose,
                    ),
                    order_by=(
                        BaseForecastRecord.generated_at.desc(),
                        BaseForecastRecord.id.desc(),
                    ),
                )
                .label("row_number"),
            )
            .where(BaseForecastRecord.purpose == purpose.value)
            .subquery()
        )

    async def list_forecast_candidates(
        self,
        *,
        purpose: ForecastPurpose,
        start_date: date,
        end_date: date,
        event_id: UUID | None,
        model_version_id: UUID | None,
        limit: int,
        offset: int,
    ) -> list[ForecastEvaluationCandidate]:
        """Return latest-per-event/model forecasts before applying eligibility gates."""
        ranked = self._ranked_forecasts(purpose=purpose)
        statement = (
            select(BaseForecastRecord, SportsEventRecord)
            .join(ranked, BaseForecastRecord.id == ranked.c.forecast_id)
            .join(SportsEventRecord, SportsEventRecord.id == BaseForecastRecord.sports_event_id)
            .where(
                ranked.c.row_number == 1,
                SportsEventRecord.event_date >= start_date,
                SportsEventRecord.event_date <= end_date,
            )
            .options(joinedload(BaseForecastRecord.model_version))
        )
        if event_id is not None:
            statement = statement.where(SportsEventRecord.id == event_id)
        if model_version_id is not None:
            statement = statement.where(BaseForecastRecord.model_version_id == model_version_id)
        result = await self.session.execute(
            statement.order_by(SportsEventRecord.id, BaseForecastRecord.model_version_id)
            .limit(limit)
            .offset(offset)
            .with_for_update(of=SportsEventRecord)
        )
        return [
            ForecastEvaluationCandidate(forecast=row[0], event=row[1])
            for row in result.unique().all()
        ]

    async def persist_forecast_evaluations(
        self,
        items: list[ForecastEvaluationPersistence],
    ) -> int:
        """Insert new semantic scores atomically and return the inserted count."""
        if not items:
            await self.session.commit()
            return 0
        values = [self._forecast_evaluation_values(item) for item in items]
        try:
            result = await self.session.scalars(
                insert(ForecastEvaluationRecord)
                .values(values)
                .on_conflict_do_nothing(constraint="uq_forecast_evaluations_semantic_input")
                .returning(ForecastEvaluationRecord.id)
            )
            inserted = len(result.all())
            await self.session.commit()
            return inserted
        except Exception:
            await self.session.rollback()
            raise

    @staticmethod
    def _forecast_evaluation_values(
        item: ForecastEvaluationPersistence,
    ) -> dict[str, object]:
        source = item.source
        score = item.evaluation
        return {
            "id": forecast_evaluation_record_id(score),
            "base_forecast_id": score.forecast_id,
            "sports_event_id": score.sports_event_id,
            "model_version_id": score.model_version_id,
            "home_team_id": source.home_team_id,
            "away_team_id": source.away_team_id,
            "purpose": score.purpose.value,
            "event_date": item.event_date,
            "result_scheduled_start_time": source.result_scheduled_start_time,
            "forecast_as_of": source.forecast_as_of,
            "forecast_generated_at": source.forecast_generated_at,
            "result_source_last_seen_at": source.result_source_last_seen_at,
            "home_win_probability": score.home_win_probability,
            "predicted_home_win": score.predicted_home_win,
            "home_won": score.home_won,
            "result_home_score": score.result_home_score,
            "result_away_score": score.result_away_score,
            "brier_score": score.brier_score,
            "correct": score.prediction_correct,
            "policy_name": score.policy_name,
            "policy_version": score.policy_version,
            "policy_fingerprint": score.policy_fingerprint,
            "outcome_fingerprint": score.outcome_fingerprint,
            "input_fingerprint": score.input_fingerprint,
            "audit_snapshot": score.audit_snapshot,
            "evaluated_at": score.evaluated_at,
        }

    async def list_forecast_evaluations(
        self,
        *,
        forecast_id: UUID | None,
        sports_event_id: UUID | None,
        purpose: ForecastPurpose | None,
        model_name: str | None,
        model_version: str | None,
        start_date: date | None,
        end_date: date | None,
        evaluator_version: str | None,
        limit: int,
        offset: int,
    ) -> list[ForecastEvaluationRecord]:
        statement = (
            select(ForecastEvaluationRecord)
            .join(ModelVersionRecord)
            .options(joinedload(ForecastEvaluationRecord.model_version))
        )
        filters = (
            (ForecastEvaluationRecord.base_forecast_id, forecast_id),
            (ForecastEvaluationRecord.sports_event_id, sports_event_id),
            (ForecastEvaluationRecord.purpose, purpose.value if purpose is not None else None),
            (ModelVersionRecord.model_name, model_name),
            (ModelVersionRecord.model_version, model_version),
            (ForecastEvaluationRecord.policy_version, evaluator_version),
        )
        for column, value in filters:
            if value is not None:
                statement = statement.where(column == value)
        if start_date is not None:
            statement = statement.where(ForecastEvaluationRecord.event_date >= start_date)
        if end_date is not None:
            statement = statement.where(ForecastEvaluationRecord.event_date <= end_date)
        rows = await self.session.scalars(
            statement.order_by(
                ForecastEvaluationRecord.evaluated_at.desc(),
                ForecastEvaluationRecord.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return list(rows.unique().all())

    async def get_forecast_evaluation(self, evaluation_id: UUID) -> ForecastEvaluationRecord | None:
        return cast(
            ForecastEvaluationRecord | None,
            await self.session.scalar(
                select(ForecastEvaluationRecord)
                .where(ForecastEvaluationRecord.id == evaluation_id)
                .options(joinedload(ForecastEvaluationRecord.model_version))
            ),
        )

    async def list_current_forecast_evaluations(
        self,
        *,
        purpose: ForecastPurpose,
        start_date: date | None,
        end_date: date | None,
        model_version_ids: tuple[UUID, ...] | None,
        evaluator_version: str,
    ) -> list[ForecastEvaluationRecord]:
        """Return scores matching current canonical forecasts and current event semantics."""
        ranked = self._ranked_forecasts(purpose=purpose)
        statement = (
            select(ForecastEvaluationRecord)
            .join(ranked, ForecastEvaluationRecord.base_forecast_id == ranked.c.forecast_id)
            .join(
                SportsEventRecord, SportsEventRecord.id == ForecastEvaluationRecord.sports_event_id
            )
            .join(ModelVersionRecord)
            .where(
                ranked.c.row_number == 1,
                ForecastEvaluationRecord.policy_version == evaluator_version,
                SportsEventRecord.status == "final",
                SportsEventRecord.league == "nba",
                SportsEventRecord.postponed.is_(False),
                SportsEventRecord.event_date == ForecastEvaluationRecord.event_date,
                SportsEventRecord.home_score == ForecastEvaluationRecord.result_home_score,
                SportsEventRecord.away_score == ForecastEvaluationRecord.result_away_score,
                SportsEventRecord.home_team_id == ForecastEvaluationRecord.home_team_id,
                SportsEventRecord.away_team_id == ForecastEvaluationRecord.away_team_id,
                SportsEventRecord.scheduled_start_time
                == ForecastEvaluationRecord.result_scheduled_start_time,
            )
            .options(joinedload(ForecastEvaluationRecord.model_version))
        )
        if start_date is not None:
            statement = statement.where(ForecastEvaluationRecord.event_date >= start_date)
        if end_date is not None:
            statement = statement.where(ForecastEvaluationRecord.event_date <= end_date)
        if model_version_ids is not None:
            statement = statement.where(
                ForecastEvaluationRecord.model_version_id.in_(model_version_ids)
            )
        rows = await self.session.scalars(
            statement.order_by(
                ForecastEvaluationRecord.model_version_id,
                ForecastEvaluationRecord.event_date,
                ForecastEvaluationRecord.sports_event_id,
            )
        )
        return list(rows.unique().all())

    async def existing_model_version_ids(self, ids: tuple[UUID, ...]) -> frozenset[UUID]:
        rows = await self.session.scalars(
            select(ModelVersionRecord.id).where(ModelVersionRecord.id.in_(ids))
        )
        return frozenset(rows.all())

    async def load_trading_performance_sources(
        self, portfolio_id: UUID
    ) -> TradingPerformanceSources | None:
        """Lock one paper portfolio and freeze all sources through its ledger head."""
        portfolio = cast(
            PortfolioRecord | None,
            await self.session.scalar(
                select(PortfolioRecord)
                .where(PortfolioRecord.id == portfolio_id)
                .with_for_update(of=PortfolioRecord)
            ),
        )
        if portfolio is None:
            return None
        evaluated_at = await self.database_time()
        head = cast(
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
        if head is None:
            raise RuntimeError("portfolio is missing its authoritative ledger head")
        snapshot_rows = await self.session.scalars(
            select(PortfolioSnapshotRecord)
            .where(
                PortfolioSnapshotRecord.portfolio_id == portfolio_id,
                PortfolioSnapshotRecord.sequence <= head.sequence,
            )
            .order_by(PortfolioSnapshotRecord.sequence)
        )
        snapshots = tuple(snapshot_rows.all())

        result = await self.session.execute(
            select(
                PaperPositionRecord,
                PaperTradeRecord,
                OpportunityRecord,
                PositionSizeProposalRecord,
                RiskDecisionRecord,
                BaseForecastRecord,
                ModelVersionRecord,
            )
            .join(PaperTradeRecord, PaperTradeRecord.id == PaperPositionRecord.opening_trade_id)
            .join(OpportunityRecord, OpportunityRecord.id == PaperTradeRecord.opportunity_id)
            .join(
                PositionSizeProposalRecord,
                PositionSizeProposalRecord.id == PaperTradeRecord.position_size_proposal_id,
            )
            .join(RiskDecisionRecord, RiskDecisionRecord.id == PaperTradeRecord.risk_decision_id)
            .join(BaseForecastRecord, BaseForecastRecord.id == PaperTradeRecord.base_forecast_id)
            .join(ModelVersionRecord, ModelVersionRecord.id == BaseForecastRecord.model_version_id)
            .where(
                PaperPositionRecord.portfolio_id == portfolio_id,
                PaperTradeRecord.portfolio_id == portfolio_id,
                PaperTradeRecord.status == "filled",
            )
            .order_by(PaperPositionRecord.id)
        )
        raw_lineages = result.all()
        filled_trade_rows = await self.session.scalars(
            select(PaperTradeRecord.id).where(
                PaperTradeRecord.portfolio_id == portfolio_id,
                PaperTradeRecord.status == "filled",
            )
        )
        filled_trade_ids = set(filled_trade_rows.all())
        opening_trade_ids = {row[1].id for row in raw_lineages}
        if filled_trade_ids != opening_trade_ids:
            raise RuntimeError("every filled trade must have exactly one position lineage")

        position_ids = tuple(row[0].id for row in raw_lineages)
        event_map: dict[UUID, list[PositionEventRecord]] = {item: [] for item in position_ids}
        if position_ids:
            event_rows = await self.session.scalars(
                select(PositionEventRecord)
                .where(PositionEventRecord.position_id.in_(position_ids))
                .order_by(
                    PositionEventRecord.position_id,
                    PositionEventRecord.position_version_after,
                    PositionEventRecord.evaluated_at,
                    PositionEventRecord.id,
                )
            )
            for event in event_rows.all():
                event_map[event.position_id].append(event)

        lineages = tuple(
            TradingPositionLineage(
                position=row[0],
                trade=row[1],
                opportunity=row[2],
                proposal=row[3],
                risk_decision=row[4],
                forecast=row[5],
                model_version=row[6],
                events=tuple(event_map[row[0].id]),
            )
            for row in raw_lineages
        )
        fallback_ids: set[UUID] = {
            item.trade.portfolio_snapshot_after_id
            for item in lineages
            if item.trade.mark_basis == "directional_ask_fallback"
            and item.trade.portfolio_snapshot_after_id is not None
        }
        fallback_ids.update(
            event.portfolio_snapshot_after_id
            for item in lineages
            for event in item.events
            if event.after_mark_basis == "directional_ask_fallback"
            and event.portfolio_snapshot_after_id is not None
        )
        snapshot_sequences = {item.id: item.sequence for item in snapshots}
        fallback_sequences = [
            snapshot_sequences[item] for item in fallback_ids if item in snapshot_sequences
        ]
        if fallback_sequences:
            first_fallback_sequence = min(fallback_sequences)
            fallback_ids.update(
                item.id for item in snapshots if item.sequence >= first_fallback_sequence
            )
        return TradingPerformanceSources(
            portfolio=portfolio,
            snapshots=snapshots,
            positions=lineages,
            fallback_snapshot_ids=frozenset(fallback_ids),
            evaluated_at=evaluated_at,
        )

    async def rollback(self) -> None:
        await self.session.rollback()
