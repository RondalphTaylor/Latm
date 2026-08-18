from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_UP, Decimal
from typing import Literal, cast
from uuid import UUID

from pydantic import JsonValue, TypeAdapter

from app.domain.forecast_evaluation import (
    ForecastCalibrationReport,
    ForecastEvaluation,
    ForecastEvaluationInput,
    ForecastEvaluationPolicy,
    ModelEvaluationSummary,
    PairedModelComparison,
)
from app.domain.forecasts import ForecastPurpose
from app.domain.portfolio import PortfolioMode, PortfolioSnapshot, PortfolioSnapshotReason
from app.domain.trading_evaluation import (
    EntryLineage,
    PositionPerformanceFact,
    TradingEvaluationInput,
    TradingEvaluationPolicy,
    TradingEvaluationSnapshot,
    TradingPerformanceEvaluation,
    TradingPositionStatus,
)
from app.models.evaluation import ForecastEvaluationRecord
from app.services.evaluation.forecast_engine import DeterministicForecastEvaluationEngine
from app.services.evaluation.repository import (
    EvaluationRepository,
    ForecastEvaluationCandidate,
    ForecastEvaluationPersistence,
    TradingPositionLineage,
)
from app.services.evaluation.trading_engine import PaperTradingEvaluationEngine
from app.services.position_monitoring.service import position_projection_fingerprint
from app.services.position_sizing.repository import portfolio_state_fingerprint

_MAX_EVALUATION_RANGE_DAYS = 3660
_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JsonValue])


@dataclass(frozen=True)
class ForecastEvaluationRunResult:
    """Counts and policy identity returned by one bounded materialization run."""

    purpose: ForecastPurpose
    start_date: date
    end_date: date
    examined: int
    eligible: int
    persisted: int
    replayed: int
    skip_counts: dict[str, int]
    evaluator_name: str
    evaluator_version: str
    evaluator_fingerprint: str


@dataclass(frozen=True)
class ForecastModelPerformance:
    """One model's descriptive score and complete reliability table."""

    summary: ModelEvaluationSummary
    calibration: ForecastCalibrationReport


@dataclass(frozen=True)
class ForecastPerformanceResult:
    """Current canonical forecast performance, kept separate by purpose and model."""

    purpose: ForecastPurpose
    evaluation_count: int
    unique_event_count: int
    model_count: int
    models: tuple[ForecastModelPerformance, ...]
    evaluator_name: str
    evaluator_version: str
    evaluator_fingerprint: str
    warnings: tuple[str, ...]


class ForecastEvaluationService:
    """Materialize immutable forecast scores and aggregate current canonical facts."""

    def __init__(
        self,
        *,
        repository: EvaluationRepository,
        policy: ForecastEvaluationPolicy | None = None,
    ) -> None:
        self.repository = repository
        self.engine = DeterministicForecastEvaluationEngine(policy)

    async def run(
        self,
        *,
        purpose: ForecastPurpose,
        start_date: date,
        end_date: date,
        event_id: UUID | None,
        model_version_id: UUID | None,
        limit: int,
        offset: int,
    ) -> ForecastEvaluationRunResult:
        self._validate_date_range(start_date, end_date)
        candidates = await self.repository.list_forecast_candidates(
            purpose=purpose,
            start_date=start_date,
            end_date=end_date,
            event_id=event_id,
            model_version_id=model_version_id,
            limit=limit,
            offset=offset,
        )
        evaluated_at = await self.repository.database_time()
        skip_counts: Counter[str] = Counter()
        persistence: list[ForecastEvaluationPersistence] = []
        for candidate in candidates:
            reason = self._skip_reason(candidate, purpose)
            if reason is not None:
                skip_counts[reason] += 1
                continue
            source = self._evaluation_input(candidate, purpose, evaluated_at)
            persistence.append(
                ForecastEvaluationPersistence(
                    source=source,
                    evaluation=self.engine.evaluate(source),
                    event_date=candidate.event.event_date,
                )
            )
        persisted = await self.repository.persist_forecast_evaluations(persistence)
        return ForecastEvaluationRunResult(
            purpose=purpose,
            start_date=start_date,
            end_date=end_date,
            examined=len(candidates),
            eligible=len(persistence),
            persisted=persisted,
            replayed=len(persistence) - persisted,
            skip_counts=dict(sorted(skip_counts.items())),
            evaluator_name=self.engine.policy.policy_name,
            evaluator_version=self.engine.policy_version,
            evaluator_fingerprint=self.engine.policy_fingerprint,
        )

    async def performance(
        self,
        *,
        purpose: ForecastPurpose,
        start_date: date | None,
        end_date: date | None,
        model_version_ids: tuple[UUID, ...] | None,
    ) -> ForecastPerformanceResult:
        if start_date is not None and end_date is not None:
            self._validate_date_range(start_date, end_date)
        if model_version_ids is not None:
            await self._require_model_versions(model_version_ids)
        records = await self.repository.list_current_forecast_evaluations(
            purpose=purpose,
            start_date=start_date,
            end_date=end_date,
            model_version_ids=model_version_ids,
            evaluator_version=self.engine.policy_version,
        )
        evaluations = tuple(self._domain_evaluation(record) for record in records)
        summaries = self.engine.summarize_models(evaluations)
        grouped: dict[UUID, list[ForecastEvaluation]] = defaultdict(list)
        for evaluation in evaluations:
            grouped[evaluation.model_version_id].append(evaluation)
        models = tuple(
            ForecastModelPerformance(
                summary=summary,
                calibration=self.engine.calibrate(grouped[summary.model_version_id]),
            )
            for summary in summaries
        )
        warnings = (
            (
                (
                    "historical_replay is a retrospective chronological simulation; "
                    "the source schema does not preserve when prior final results first became available"
                ),
            )
            if purpose is ForecastPurpose.HISTORICAL_REPLAY
            else ()
        )
        return ForecastPerformanceResult(
            purpose=purpose,
            evaluation_count=len(evaluations),
            unique_event_count=len({item.sports_event_id for item in evaluations}),
            model_count=len(models),
            models=models,
            evaluator_name=self.engine.policy.policy_name,
            evaluator_version=self.engine.policy_version,
            evaluator_fingerprint=self.engine.policy_fingerprint,
            warnings=warnings,
        )

    async def compare(
        self,
        *,
        purpose: ForecastPurpose,
        model_a_version_id: UUID,
        model_b_version_id: UUID,
        start_date: date | None,
        end_date: date | None,
    ) -> PairedModelComparison:
        if start_date is not None and end_date is not None:
            self._validate_date_range(start_date, end_date)
        await self._require_model_versions((model_a_version_id, model_b_version_id))
        records = await self.repository.list_current_forecast_evaluations(
            purpose=purpose,
            start_date=start_date,
            end_date=end_date,
            model_version_ids=(model_a_version_id, model_b_version_id),
            evaluator_version=self.engine.policy_version,
        )
        return self.engine.compare_models(
            tuple(self._domain_evaluation(record) for record in records),
            model_a_version_id=model_a_version_id,
            model_b_version_id=model_b_version_id,
            purpose=purpose,
        )

    @staticmethod
    def _skip_reason(
        candidate: ForecastEvaluationCandidate,
        purpose: ForecastPurpose,
    ) -> str | None:
        forecast = candidate.forecast
        event = candidate.event
        if event.status != "final":
            return "not_final"
        if event.home_score is None or event.away_score is None:
            return "incomplete_score"
        if event.home_score == event.away_score:
            return "tied_score"
        if event.postponed:
            return "postponed"
        if event.league != "nba":
            return "unsupported_league"
        if (
            forecast.home_team_id != event.home_team_id
            or forecast.away_team_id != event.away_team_id
        ):
            return "team_mismatch"
        if purpose is ForecastPurpose.OPERATIONAL:
            if (
                forecast.forecast_as_of != forecast.generated_at
                or forecast.forecast_as_of >= event.scheduled_start_time
                or forecast.generated_at >= event.scheduled_start_time
            ):
                return "forecast_after_tip"
        elif (
            forecast.forecast_as_of != event.scheduled_start_time
            or forecast.generated_at < forecast.forecast_as_of
        ):
            return "historical_cutoff_mismatch"
        return None

    async def _require_model_versions(self, ids: tuple[UUID, ...]) -> None:
        requested = frozenset(ids)
        existing = await self.repository.existing_model_version_ids(tuple(requested))
        missing = requested - existing
        if missing:
            missing_text = ", ".join(sorted(str(item) for item in missing))
            raise LookupError(f"model version not found: {missing_text}")

    @staticmethod
    def _evaluation_input(
        candidate: ForecastEvaluationCandidate,
        purpose: ForecastPurpose,
        evaluated_at: datetime,
    ) -> ForecastEvaluationInput:
        forecast = candidate.forecast
        event = candidate.event
        if event.home_score is None or event.away_score is None:
            raise ValueError("eligible evaluation result must have complete scores")
        model = forecast.model_version
        return ForecastEvaluationInput(
            forecast_id=forecast.id,
            sports_event_id=forecast.sports_event_id,
            model_version_id=forecast.model_version_id,
            model_name=model.model_name,
            model_version=model.model_version,
            purpose=purpose,
            forecast_input_fingerprint=forecast.input_fingerprint,
            model_configuration_fingerprint=model.configuration_fingerprint,
            home_team_id=forecast.home_team_id,
            away_team_id=forecast.away_team_id,
            home_win_probability=forecast.home_win_probability,
            forecast_as_of=forecast.forecast_as_of,
            forecast_generated_at=forecast.generated_at,
            result_provider_name=event.provider_name,
            result_league=event.league,
            result_status="final",
            result_postponed=event.postponed,
            result_event_date=event.event_date,
            result_scheduled_start_time=event.scheduled_start_time,
            result_home_team_id=event.home_team_id,
            result_away_team_id=event.away_team_id,
            result_home_score=event.home_score,
            result_away_score=event.away_score,
            result_source_last_seen_at=event.last_seen_at,
            evaluated_at=evaluated_at,
        )

    @staticmethod
    def _domain_evaluation(record: ForecastEvaluationRecord) -> ForecastEvaluation:
        model = record.model_version
        return ForecastEvaluation(
            forecast_id=record.base_forecast_id,
            sports_event_id=record.sports_event_id,
            model_version_id=record.model_version_id,
            model_name=model.model_name,
            model_version=model.model_version,
            purpose=ForecastPurpose(record.purpose),
            home_win_probability=record.home_win_probability,
            home_won=record.home_won,
            result_home_score=record.result_home_score,
            result_away_score=record.result_away_score,
            brier_score=record.brier_score,
            predicted_home_win=record.predicted_home_win,
            prediction_correct=record.correct,
            result_scheduled_start_time=record.result_scheduled_start_time,
            result_source_last_seen_at=record.result_source_last_seen_at,
            outcome_fingerprint=record.outcome_fingerprint,
            policy_name=record.policy_name,
            policy_version=record.policy_version,
            policy_fingerprint=record.policy_fingerprint,
            input_fingerprint=record.input_fingerprint,
            evaluated_at=record.evaluated_at,
            audit_snapshot=_JSON_OBJECT_ADAPTER.validate_python(record.audit_snapshot),
        )

    @staticmethod
    def _validate_date_range(start_date: date, end_date: date) -> None:
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        if (end_date - start_date).days + 1 > _MAX_EVALUATION_RANGE_DAYS:
            raise ValueError(
                f"evaluation date range cannot exceed {_MAX_EVALUATION_RANGE_DAYS} days"
            )


class TradingPerformanceService:
    """Derive read-only paper performance from the portfolio-locked ledger."""

    def __init__(
        self,
        *,
        repository: EvaluationRepository,
        policy: TradingEvaluationPolicy | None = None,
    ) -> None:
        self.repository = repository
        self.engine = PaperTradingEvaluationEngine(policy)

    async def evaluate(self, portfolio_id: UUID) -> TradingPerformanceEvaluation:
        try:
            sources = await self.repository.load_trading_performance_sources(portfolio_id)
            if sources is None:
                raise LookupError("portfolio not found")
            if sources.portfolio.execution_mode != "paper" or sources.portfolio.currency != "USD":
                raise ValueError("evaluation accepts only USD paper portfolios")
            snapshots = tuple(
                self._snapshot(
                    record, sources.portfolio.starting_bankroll, sources.fallback_snapshot_ids
                )
                for record in sources.snapshots
            )
            positions = tuple(self._position_fact(item) for item in sources.positions)
            result = self.engine.evaluate(
                TradingEvaluationInput(
                    portfolio_id=portfolio_id,
                    execution_mode="paper",
                    currency="USD",
                    snapshots=snapshots,
                    positions=positions,
                    evaluated_at=sources.evaluated_at,
                )
            )
            await self.repository.rollback()
            return result
        except Exception:
            await self.repository.rollback()
            raise

    @staticmethod
    def _position_fact(source: TradingPositionLineage) -> PositionPerformanceFact:
        position = source.position
        trade = source.trade
        proposal = source.proposal
        risk = source.risk_decision
        opportunity = source.opportunity
        model = source.model_version
        if trade.executed_at is None or trade.adjusted_edge is None or trade.total_cost is None:
            raise RuntimeError("filled position is missing entry execution economics")
        if position.original_total_cost_basis != trade.total_cost:
            raise RuntimeError("position original basis does not match its filled trade")
        if position.initial_quantity != trade.executed_quantity:
            raise RuntimeError("position original quantity does not match its filled trade")
        TradingPerformanceService._validate_entry_lineage(source)
        price_quantum = Decimal("0.000001")
        expected_raw_edge = (trade.model_probability - trade.reference_price).quantize(
            price_quantum
        )
        expected_effective_cost = (trade.total_cost / trade.executed_quantity).quantize(
            price_quantum,
            rounding=ROUND_UP,
        )
        expected_adjusted_edge = (trade.model_probability - expected_effective_cost).quantize(
            price_quantum
        )
        if (
            trade.raw_edge != expected_raw_edge
            or trade.effective_unit_cost != expected_effective_cost
            or trade.adjusted_edge != expected_adjusted_edge
        ):
            raise RuntimeError("position entry edge economics are inconsistent")
        TradingPerformanceService._validate_position_events(source)
        market_snapshot = opportunity.source_snapshot.get("market")
        if not isinstance(market_snapshot, dict):
            raise RuntimeError("opening opportunity is missing immutable market provenance")
        market_type = market_snapshot.get("market_type")
        if not isinstance(market_type, str) or not market_type:
            raise RuntimeError("opening opportunity is missing immutable market type")
        status = TradingPositionStatus(position.status)
        terminal_at = (
            position.closed_at if status is TradingPositionStatus.CLOSED else position.settled_at
        )
        return PositionPerformanceFact(
            position_id=position.id,
            opening_trade_id=trade.id,
            portfolio_id=position.portfolio_id,
            status=status,
            original_total_cost_basis=position.original_total_cost_basis,
            realized_pnl=position.realized_pnl,
            unrealized_pnl=position.unrealized_pnl,
            raw_entry_edge=trade.raw_edge,
            adjusted_entry_edge=trade.adjusted_edge,
            executed_at=trade.executed_at,
            terminal_at=terminal_at,
            lineage=EntryLineage(
                model_version_id=model.id,
                model_name=model.model_name,
                model_version=model.model_version,
                model_configuration_fingerprint=model.configuration_fingerprint,
                opportunity_strategy_name=opportunity.strategy_name,
                opportunity_strategy_version=opportunity.strategy_version,
                opportunity_policy_fingerprint=opportunity.policy_fingerprint,
                sizing_strategy_name=proposal.strategy_name,
                sizing_strategy_version=proposal.strategy_version,
                sizing_policy_fingerprint=proposal.policy_fingerprint,
                risk_policy_name=risk.risk_policy_name,
                risk_policy_version=risk.risk_policy_version,
                risk_policy_fingerprint=risk.risk_policy_fingerprint,
                execution_policy_name=trade.execution_policy_name,
                execution_policy_version=trade.execution_policy_version,
                execution_policy_fingerprint=trade.execution_policy_fingerprint,
                market_type=market_type,
            ),
        )

    @staticmethod
    def _snapshot(
        record: object,
        portfolio_starting_bankroll: Decimal,
        fallback_snapshot_ids: frozenset[UUID],
    ) -> TradingEvaluationSnapshot:
        from app.models.portfolio import PortfolioSnapshotRecord

        if not isinstance(record, PortfolioSnapshotRecord):
            raise TypeError("trading performance snapshot source is invalid")
        if record.starting_bankroll != portfolio_starting_bankroll:
            raise RuntimeError("snapshot starting bankroll does not match its portfolio")
        if record.execution_mode != "paper" or record.currency != "USD":
            raise RuntimeError("trading performance accepts only USD paper snapshots")
        domain_snapshot = PortfolioSnapshot(
            id=record.id,
            portfolio_id=record.portfolio_id,
            sequence=record.sequence,
            mode=PortfolioMode(record.execution_mode),
            currency=record.currency,
            starting_bankroll=record.starting_bankroll,
            current_bankroll=record.current_bankroll,
            cash_balance=record.cash_balance,
            reserved_capital=record.reserved_capital,
            committed_capital=record.committed_capital,
            available_bankroll=record.available_bankroll,
            realized_pnl=record.realized_pnl,
            open_position_value=record.open_position_value,
            unrealized_pnl=record.unrealized_pnl,
            total_portfolio_value=record.total_portfolio_value,
            previous_snapshot_id=record.previous_snapshot_id,
            reason=PortfolioSnapshotReason(record.reason),
            state_fingerprint=record.state_fingerprint,
            captured_at=record.captured_at,
        )
        if portfolio_state_fingerprint(domain_snapshot) != record.state_fingerprint:
            raise RuntimeError("portfolio snapshot state fingerprint is inconsistent")
        return TradingEvaluationSnapshot(
            id=record.id,
            portfolio_id=record.portfolio_id,
            sequence=record.sequence,
            previous_snapshot_id=record.previous_snapshot_id,
            execution_mode=cast(Literal["paper"], record.execution_mode),
            currency=cast(Literal["USD"], record.currency),
            starting_bankroll=record.starting_bankroll,
            realized_pnl=record.realized_pnl,
            unrealized_pnl=record.unrealized_pnl,
            total_portfolio_value=record.total_portfolio_value,
            state_fingerprint=record.state_fingerprint,
            captured_at=record.captured_at,
            includes_non_executable_mark=record.id in fallback_snapshot_ids,
        )

    @staticmethod
    def _validate_entry_lineage(source: TradingPositionLineage) -> None:
        position = source.position
        trade = source.trade
        proposal = source.proposal
        risk = source.risk_decision
        opportunity = source.opportunity
        forecast = source.forecast
        model = source.model_version
        portfolio_ids = {
            position.portfolio_id,
            trade.portfolio_id,
            proposal.portfolio_id,
            risk.portfolio_id,
        }
        if len(portfolio_ids) != 1:
            raise RuntimeError("position entry records cross portfolio boundaries")
        if not (
            trade.status == "filled"
            and trade.action == "buy"
            and trade.execution_mode == position.execution_mode == risk.execution_mode == "paper"
            and trade.position_size_proposal_id == proposal.id == risk.position_size_proposal_id
            and trade.risk_decision_id == risk.id
            and trade.opportunity_id
            == proposal.opportunity_id
            == risk.opportunity_id
            == opportunity.id
            and trade.market_id
            == position.market_id
            == proposal.market_id
            == risk.market_id
            == opportunity.market_id
            and trade.outcome_team_id
            == position.outcome_team_id
            == proposal.outcome_team_id
            == risk.outcome_team_id
            == opportunity.outcome_team_id
            and trade.direction
            == position.direction
            == proposal.direction
            == risk.direction
            == opportunity.direction
            and trade.base_forecast_id
            == risk.base_forecast_id
            == opportunity.base_forecast_id
            == forecast.id
            and forecast.model_version_id == opportunity.model_version_id == model.id
            and trade.sizing_strategy_version == proposal.strategy_version
            and risk.proposal_strategy_name == proposal.strategy_name
            and risk.proposal_strategy_version == proposal.strategy_version
            and trade.risk_policy_version == risk.risk_policy_version
        ):
            raise RuntimeError("position entry policy and source lineage is inconsistent")

    @staticmethod
    def _validate_position_events(source: TradingPositionLineage) -> None:
        position = source.position
        events = source.events
        if not events:
            if position.realized_pnl != Decimal("0.00") or position.version != 0:
                raise RuntimeError("position projection is missing its event history")
            if position.status != "open":
                raise RuntimeError("terminal position is missing its terminal event")
            return
        first = events[0]
        if not (
            first.position_version_before == 0
            and first.status_before == "open"
            and first.quantity_before == position.initial_quantity
            and first.gross_cost_basis_before == position.original_gross_cost_basis
            and first.entry_fees_before == position.original_entry_fees
            and first.total_cost_basis_before == position.original_total_cost_basis
            and first.realized_pnl_before == Decimal("0.00")
            and first.position_projection_fingerprint_before == position.input_fingerprint
        ):
            raise RuntimeError("position event history does not start from the opening projection")
        for previous, current in zip(events, events[1:], strict=False):
            if not (
                previous.position_version_after == current.position_version_before
                and previous.status_after == current.status_before
                and previous.quantity_after == current.quantity_before
                and previous.gross_cost_basis_after == current.gross_cost_basis_before
                and previous.entry_fees_after == current.entry_fees_before
                and previous.total_cost_basis_after == current.total_cost_basis_before
                and previous.realized_pnl_cumulative == current.realized_pnl_before
                and previous.position_projection_fingerprint_after
                == current.position_projection_fingerprint_before
            ):
                raise RuntimeError("position event history is not contiguous")
        latest = events[-1]
        if not (
            latest.position_version_after == position.version
            and latest.status_after == position.status
            and latest.quantity_after == position.quantity
            and latest.gross_cost_basis_after == position.gross_cost_basis
            and latest.entry_fees_after == position.entry_fees
            and latest.total_cost_basis_after == position.total_cost_basis
            and latest.after_mark_price == position.mark_price
            and latest.after_mark_basis == position.mark_basis
            and latest.after_market_value == position.market_value
            and latest.after_unrealized_pnl == position.unrealized_pnl
            and latest.realized_pnl_cumulative == position.realized_pnl
            and latest.position_projection_fingerprint_after == position.projection_fingerprint
            and position_projection_fingerprint(position) == position.projection_fingerprint
        ):
            raise RuntimeError("latest position event does not match the current projection")
        terminal = tuple(item for item in events if item.decision in {"close", "settle"})
        if position.status == "open" and terminal:
            raise RuntimeError("open position cannot contain a terminal event")
        if position.status in {"closed", "settled"}:
            expected = "close" if position.status == "closed" else "settle"
            terminal_time = (
                position.closed_at if position.status == "closed" else position.settled_at
            )
            if (
                len(terminal) != 1
                or latest.decision != expected
                or latest.executed_at != terminal_time
            ):
                raise RuntimeError("terminal position must have one matching terminal event")
