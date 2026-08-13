from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

from app.domain.opportunities import OpportunityPolicy
from app.domain.portfolio import (
    PortfolioDefinition,
    PortfolioSnapshot,
    PositionSizeProposal,
)
from app.models.opportunities import OpportunityRecord
from app.models.portfolio import PortfolioRecord, PortfolioSnapshotRecord
from app.services.forecasting.elo import source_event_fingerprint
from app.services.opportunities.repository import OpportunityRepository
from app.services.opportunities.service import OpportunityDetectionService
from app.services.position_sizing.repository import (
    CurrentOpportunityContext,
    PortfolioBundle,
    PositionSizingRepository,
    ProposalPersistResult,
)
from app.services.position_sizing.service import PaperPortfolioService, PositionSizingService
from tests.test_opportunity_service import FakeOpportunityRepository, source_bundle

NOW = datetime(2026, 8, 11, 12, tzinfo=UTC)
PORTFOLIO_ID = UUID("70000000-0000-0000-0000-000000000001")
SNAPSHOT_ID = UUID("70000000-0000-0000-0000-000000000002")


def portfolio_bundle() -> PortfolioBundle:
    portfolio = PortfolioRecord(
        id=PORTFOLIO_ID,
        idempotency_key="primary",
        name="Primary Paper Portfolio",
        execution_mode="paper",
        currency="USD",
        starting_bankroll=Decimal("1000.00"),
        status="active",
        is_active=True,
        creation_fingerprint="a" * 64,
        created_at=NOW,
    )
    snapshot = PortfolioSnapshotRecord(
        id=SNAPSHOT_ID,
        portfolio_id=PORTFOLIO_ID,
        sequence=0,
        execution_mode="paper",
        currency="USD",
        starting_bankroll=Decimal("1000.00"),
        current_bankroll=Decimal("1000.00"),
        cash_balance=Decimal("1000.00"),
        reserved_capital=Decimal("0.00"),
        committed_capital=Decimal("0.00"),
        available_bankroll=Decimal("1000.00"),
        realized_pnl=Decimal("0.00"),
        reason="created",
        state_fingerprint="b" * 64,
        captured_at=NOW,
    )
    return PortfolioBundle(portfolio=portfolio, snapshot=snapshot)


def opportunity_context() -> CurrentOpportunityContext:
    bundle = source_bundle()
    assert bundle.price is not None and bundle.forecast is not None
    assert bundle.event is not None
    bundle.price.retrieved_at = NOW - timedelta(minutes=2)
    bundle.forecast.generated_at = NOW - timedelta(minutes=10)
    bundle.market.close_time = NOW + timedelta(hours=2)
    bundle.event.scheduled_start_time = NOW + timedelta(hours=2)
    bundle.forecast.input_features["source_event_fingerprint"] = source_event_fingerprint(
        event_id=bundle.event.id,
        scheduled_start_time=bundle.event.scheduled_start_time,
        home_team_id=bundle.event.home_team_id,
        away_team_id=bundle.event.away_team_id,
        event_status=bundle.event.status,
    )
    fake = FakeOpportunityRepository([bundle])

    result = asyncio.run(
        OpportunityDetectionService(
            repository=cast(OpportunityRepository, fake),
            policy=OpportunityPolicy(),
            clock=lambda: NOW,
        ).run(
            start_date=NOW.date(),
            end_date=NOW.date(),
            market_id=None,
            limit=10,
            offset=0,
        )
    )
    assert result.generated == 2
    decision = fake.decisions[0]
    record = OpportunityRecord(
        id=UUID("70000000-0000-0000-0000-000000000003"),
        **decision.model_dump(mode="python"),
    )
    return CurrentOpportunityContext(
        opportunity=record,
        market=bundle.market,
        event=bundle.event,
        forecast=bundle.forecast,
    )


class FakePositionSizingRepository:
    def __init__(
        self,
        *,
        contexts: list[CurrentOpportunityContext] | None = None,
        bundle: PortfolioBundle | None = None,
    ) -> None:
        self.contexts = contexts or []
        self.bundle = bundle or portfolio_bundle()
        self.proposals: list[PositionSizeProposal] = []
        self.definition: PortfolioDefinition | None = None
        self.initial_snapshot: PortfolioSnapshot | None = None
        self.created = True

    async def get_portfolio(self, portfolio_id: UUID) -> PortfolioBundle | None:
        return self.bundle if portfolio_id == self.bundle.portfolio.id else None

    async def list_current_opportunity_contexts(
        self, **_: object
    ) -> list[CurrentOpportunityContext]:
        return self.contexts

    async def persist_proposals(
        self, proposals: list[PositionSizeProposal]
    ) -> ProposalPersistResult:
        self.proposals = list(proposals)
        return ProposalPersistResult(inserted=len(proposals), invalidated=0)

    async def create_portfolio(
        self,
        definition: PortfolioDefinition,
        initial_snapshot: PortfolioSnapshot,
    ) -> tuple[PortfolioBundle, bool]:
        self.definition = definition
        self.initial_snapshot = initial_snapshot
        return self.bundle, self.created


def test_position_sizing_service_generates_advisory_without_mutating_balance() -> None:
    repository = FakePositionSizingRepository(contexts=[opportunity_context()])
    service = PositionSizingService(
        repository=cast(PositionSizingRepository, repository),
        clock=lambda: NOW,
    )

    result = asyncio.run(
        service.run(
            portfolio_id=PORTFOLIO_ID,
            opportunity_id=None,
            limit=10,
            offset=0,
        )
    )

    assert result.examined == 1
    assert result.generated == 1
    assert result.persisted == 1
    assert result.band_counts == {"candidate": 1}
    assert repository.proposals[0].proposed_capital == Decimal("20.00")
    assert repository.proposals[0].state.value == "awaiting_risk"
    assert repository.bundle.snapshot.available_bankroll == Decimal("1000.00")


def test_missing_current_candidate_is_audited_without_historical_fallback() -> None:
    repository = FakePositionSizingRepository()
    service = PositionSizingService(
        repository=cast(PositionSizingRepository, repository),
        clock=lambda: NOW,
    )

    result = asyncio.run(
        service.run(
            portfolio_id=PORTFOLIO_ID,
            opportunity_id=UUID("70000000-0000-0000-0000-000000000099"),
            limit=10,
            offset=0,
        )
    )

    assert result.generated == 0
    assert result.skip_counts == {"opportunity_not_current_trade_candidate": 1}


def test_changed_event_or_orientation_is_rejected_before_sizing() -> None:
    event_changed = opportunity_context()
    event_changed.event.scheduled_start_time += timedelta(minutes=1)
    orientation_changed = opportunity_context()
    orientation_changed.market.title = "Will Boston win by 10 points?"
    repository = FakePositionSizingRepository(contexts=[event_changed, orientation_changed])
    service = PositionSizingService(
        repository=cast(PositionSizingRepository, repository),
        clock=lambda: NOW,
    )

    result = asyncio.run(
        service.run(
            portfolio_id=PORTFOLIO_ID,
            opportunity_id=None,
            limit=10,
            offset=0,
        )
    )

    assert result.generated == 0
    assert result.skip_counts == {
        "event_changed_since_opportunity": 1,
        "opportunity_orientation_changed": 1,
    }


def test_portfolio_creation_uses_default_once_and_builds_untouched_snapshot() -> None:
    repository = FakePositionSizingRepository()
    service = PaperPortfolioService(
        repository=cast(PositionSizingRepository, repository),
        default_starting_bankroll=Decimal("1000.00"),
        clock=lambda: NOW,
    )

    _, result = asyncio.run(
        service.create(
            idempotency_key=" primary ",
            name=" Primary Paper Portfolio ",
            starting_bankroll=None,
        )
    )

    assert result.created is True
    assert repository.definition is not None
    assert repository.definition.starting_bankroll == Decimal("1000.00")
    assert repository.initial_snapshot is not None
    assert repository.initial_snapshot.available_bankroll == Decimal("1000.00")
    assert repository.initial_snapshot.reserved_capital == Decimal("0.00")
    assert repository.initial_snapshot.committed_capital == Decimal("0.00")
    assert len(repository.initial_snapshot.state_fingerprint) == 64


def test_portfolio_creation_normalizes_equivalent_bankroll_scales() -> None:
    fingerprints: list[str] = []
    for bankroll in (Decimal("1000"), Decimal("1000.0"), Decimal("1000.00")):
        repository = FakePositionSizingRepository()
        service = PaperPortfolioService(
            repository=cast(PositionSizingRepository, repository),
            default_starting_bankroll=Decimal("1000.00"),
            clock=lambda: NOW,
        )

        asyncio.run(
            service.create(
                idempotency_key="scaled-bankroll",
                name="Scaled Bankroll",
                starting_bankroll=bankroll,
            )
        )

        assert repository.definition is not None
        assert str(repository.definition.starting_bankroll) == "1000.00"
        fingerprints.append(repository.definition.creation_fingerprint)

    assert len(set(fingerprints)) == 1


def test_unknown_or_inactive_portfolio_fails_safely() -> None:
    repository = FakePositionSizingRepository()
    service = PositionSizingService(
        repository=cast(PositionSizingRepository, repository),
        clock=lambda: NOW,
    )

    try:
        asyncio.run(
            service.run(
                portfolio_id=UUID("70000000-0000-0000-0000-000000000098"),
                opportunity_id=None,
                limit=10,
                offset=0,
            )
        )
    except LookupError as exc:
        assert str(exc) == "portfolio not found"
    else:
        raise AssertionError("unknown portfolio should fail")
