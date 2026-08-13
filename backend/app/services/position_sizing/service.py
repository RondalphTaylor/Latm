from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from app.domain.opportunities import OpportunityOutcomeInput, OpportunityTeamInput
from app.domain.portfolio import (
    PortfolioDefinition,
    PortfolioMode,
    PortfolioSnapshot,
    PortfolioSnapshotReason,
    PortfolioStatus,
    PositionSizeProposal,
    PositionSizingInput,
    PositionSizingPolicy,
)
from app.models.portfolio import PortfolioSnapshotRecord
from app.services.forecasting.elo import source_event_fingerprint
from app.services.opportunities.orientation import resolve_outcome_orientation
from app.services.position_sizing.engine import RulesPositionSizer
from app.services.position_sizing.repository import (
    CurrentOpportunityContext,
    PortfolioBundle,
    PositionSizingRepository,
    portfolio_creation_fingerprint,
    portfolio_record_id,
    portfolio_snapshot_record_id,
    portfolio_state_fingerprint,
)

_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JsonValue])


class PortfolioCreationResult(BaseModel):
    """Idempotent portfolio creation result."""

    model_config = ConfigDict(frozen=True)

    portfolio_id: UUID
    created: bool


class PositionSizingRunResult(BaseModel):
    """Audit summary for one bounded advisory sizing run."""

    model_config = ConfigDict(frozen=True)

    portfolio_id: UUID
    portfolio_snapshot_id: UUID
    strategy_name: str
    strategy_version: str
    examined: int = Field(ge=0)
    generated: int = Field(ge=0)
    persisted: int = Field(ge=0)
    invalidated_before_persist: int = Field(ge=0)
    band_counts: dict[str, int]
    skip_counts: dict[str, int]


class PaperPortfolioService:
    """Create immutable paper portfolios without reset or live-mode paths."""

    def __init__(
        self,
        *,
        repository: PositionSizingRepository,
        default_starting_bankroll: Decimal,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._default_starting_bankroll = default_starting_bankroll
        self._clock = clock or (lambda: datetime.now(UTC))

    async def create(
        self,
        *,
        idempotency_key: str,
        name: str,
        starting_bankroll: Decimal | None,
    ) -> tuple[PortfolioBundle, PortfolioCreationResult]:
        """Create or return one exact paper-portfolio definition."""
        created_at = self._clock()
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("portfolio clock must return a timezone-aware datetime")
        normalized_key = idempotency_key.strip()
        normalized_name = name.strip()
        if not normalized_key or not normalized_name:
            raise ValueError("portfolio idempotency key and name cannot be blank")
        bankroll = (
            self._default_starting_bankroll if starting_bankroll is None else starting_bankroll
        )
        bankroll = bankroll.quantize(Decimal("0.01"))
        portfolio_id = portfolio_record_id(normalized_key)
        creation_fingerprint = portfolio_creation_fingerprint(
            idempotency_key=normalized_key,
            name=normalized_name,
            starting_bankroll=bankroll,
        )
        definition = PortfolioDefinition(
            id=portfolio_id,
            idempotency_key=normalized_key,
            name=normalized_name,
            starting_bankroll=bankroll,
            creation_fingerprint=creation_fingerprint,
            created_at=created_at,
        )
        snapshot = PortfolioSnapshot(
            id=portfolio_snapshot_record_id(portfolio_id, 0),
            portfolio_id=portfolio_id,
            sequence=0,
            starting_bankroll=bankroll,
            current_bankroll=bankroll,
            cash_balance=bankroll,
            reserved_capital=Decimal("0.00"),
            committed_capital=Decimal("0.00"),
            available_bankroll=bankroll,
            realized_pnl=Decimal("0.00"),
            reason=PortfolioSnapshotReason.CREATED,
            state_fingerprint="0" * 64,
            captured_at=created_at,
        )
        snapshot = snapshot.model_copy(
            update={"state_fingerprint": portfolio_state_fingerprint(snapshot)}
        )
        bundle, created = await self._repository.create_portfolio(definition, snapshot)
        return bundle, PortfolioCreationResult(portfolio_id=portfolio_id, created=created)


class PositionSizingService:
    """Create advisory paper allocations from current Phase 5 opportunities."""

    def __init__(
        self,
        *,
        repository: PositionSizingRepository,
        policy: PositionSizingPolicy | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._policy = policy or PositionSizingPolicy()
        self._sizer = RulesPositionSizer(self._policy)
        self._clock = clock or (lambda: datetime.now(UTC))

    async def run(
        self,
        *,
        portfolio_id: UUID,
        opportunity_id: UUID | None,
        limit: int,
        offset: int,
    ) -> PositionSizingRunResult:
        """Size a bounded current-candidate set without changing portfolio balances."""
        proposed_at = self._clock()
        if proposed_at.tzinfo is None or proposed_at.utcoffset() is None:
            raise ValueError("position-sizing clock must return a timezone-aware datetime")
        bundle = await self._repository.get_portfolio(portfolio_id)
        if bundle is None:
            raise LookupError("portfolio not found")
        if (
            bundle.portfolio.execution_mode != PortfolioMode.PAPER.value
            or bundle.portfolio.status != PortfolioStatus.ACTIVE.value
            or not bundle.portfolio.is_active
        ):
            raise ValueError("portfolio is not an active paper portfolio")
        balance_before = self._snapshot_domain(bundle.snapshot)
        contexts = await self._repository.list_current_opportunity_contexts(
            as_of=proposed_at,
            opportunity_id=opportunity_id,
            limit=limit,
            offset=offset,
        )
        skips: Counter[str] = Counter()
        proposals: list[PositionSizeProposal] = []
        bands: Counter[str] = Counter()
        if opportunity_id is not None and not contexts:
            skips["opportunity_not_current_trade_candidate"] += 1
        for context in contexts:
            semantic_skip = self._semantic_skip_reason(context)
            if semantic_skip is not None:
                skips[semantic_skip] += 1
                continue
            opportunity = context.opportunity
            source = PositionSizingInput(
                portfolio_snapshot_id=bundle.snapshot.id,
                portfolio=balance_before,
                opportunity_id=opportunity.id,
                market_id=opportunity.market_id,
                outcome_team_id=opportunity.outcome_team_id,
                direction=opportunity.direction,
                reference_price=opportunity.market_probability,
                model_probability=opportunity.model_probability,
                raw_edge=opportunity.raw_edge,
                opportunity_status=opportunity.status,
                opportunity_strategy_name=opportunity.strategy_name,
                opportunity_strategy_version=opportunity.strategy_version,
                opportunity_input_fingerprint=opportunity.input_fingerprint,
                opportunity_evaluated_at=opportunity.evaluated_at,
                opportunity_valid_until=opportunity.valid_until,
                proposed_at=proposed_at,
                source_snapshot=_JSON_OBJECT_ADAPTER.validate_python(opportunity.source_snapshot),
            )
            evaluation = self._sizer.evaluate(source)
            if evaluation.proposal is None:
                if evaluation.skip_reason is None:
                    raise RuntimeError("sizing evaluation returned neither proposal nor reason")
                skips[evaluation.skip_reason] += 1
                continue
            proposals.append(evaluation.proposal)
            sizing_snapshot = evaluation.proposal.audit_snapshot["sizing"]
            if not isinstance(sizing_snapshot, dict):
                raise RuntimeError("sizing audit snapshot is malformed")
            band = sizing_snapshot.get("band")
            if not isinstance(band, str):
                raise RuntimeError("sizing audit snapshot is missing its band")
            bands[band] += 1
        persisted = await self._repository.persist_proposals(proposals)
        balance_after = await self._repository.get_portfolio(portfolio_id)
        if balance_after is None or self._snapshot_domain(balance_after.snapshot) != balance_before:
            raise RuntimeError("position sizing mutated the paper portfolio balance")
        if persisted.invalidated:
            skips["opportunity_invalidated_before_persist"] += persisted.invalidated
        return PositionSizingRunResult(
            portfolio_id=portfolio_id,
            portfolio_snapshot_id=bundle.snapshot.id,
            strategy_name=self._policy.strategy_name,
            strategy_version=self._sizer.strategy_version,
            examined=len(contexts),
            generated=len(proposals),
            persisted=persisted.inserted,
            invalidated_before_persist=persisted.invalidated,
            band_counts=dict(sorted(bands.items())),
            skip_counts=dict(sorted(skips.items())),
        )

    @staticmethod
    def _semantic_skip_reason(context: CurrentOpportunityContext) -> str | None:
        opportunity, market, event, forecast = (
            context.opportunity,
            context.market,
            context.event,
            context.forecast,
        )
        current_event_fingerprint = source_event_fingerprint(
            event_id=event.id,
            scheduled_start_time=event.scheduled_start_time,
            home_team_id=event.home_team_id,
            away_team_id=event.away_team_id,
            event_status=event.status,
        )
        if forecast.input_features.get("source_event_fingerprint") != current_event_fingerprint:
            return "event_changed_since_opportunity"
        orientation = resolve_outcome_orientation(
            home_team=OpportunityTeamInput(
                id=event.home_team.id,
                abbreviation=event.home_team.abbreviation,
                city=event.home_team.city,
                name=event.home_team.name,
                full_name=event.home_team.full_name,
            ),
            away_team=OpportunityTeamInput(
                id=event.away_team.id,
                abbreviation=event.away_team.abbreviation,
                city=event.away_team.city,
                name=event.away_team.name,
                full_name=event.away_team.full_name,
            ),
            outcomes=tuple(
                OpportunityOutcomeInput(id=item.id, side=item.side, label=item.label)
                for item in market.outcomes
            ),
            market_title=market.title,
            market_type=market.market_type,
        )
        if (
            orientation is None
            or orientation.input_fingerprint != opportunity.orientation_fingerprint
            or orientation.yes_team_id != opportunity.yes_team_id
            or orientation.no_team_id != opportunity.no_team_id
        ):
            return "opportunity_orientation_changed"
        return None

    @staticmethod
    def _snapshot_domain(record: PortfolioSnapshotRecord) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            id=record.id,
            portfolio_id=record.portfolio_id,
            sequence=record.sequence,
            mode=record.execution_mode,
            currency=record.currency,
            starting_bankroll=record.starting_bankroll,
            current_bankroll=record.current_bankroll,
            cash_balance=record.cash_balance,
            reserved_capital=record.reserved_capital,
            committed_capital=record.committed_capital,
            available_bankroll=record.available_bankroll,
            realized_pnl=record.realized_pnl,
            reason=record.reason,
            state_fingerprint=record.state_fingerprint,
            captured_at=record.captured_at,
        )
