from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from uuid import UUID

from app.domain.position_monitoring import PositionMonitoringPolicy
from app.models.execution import PaperPositionRecord, PositionEventRecord
from app.models.forecasts import BaseForecastRecord
from app.models.markets import (
    MarketPriceRecord,
    MarketResolutionRecord,
    PredictionMarketRecord,
)
from app.models.matching import MarketEventMatchRecord
from app.models.portfolio import PortfolioSnapshotRecord
from app.models.sports import SportsEventRecord
from app.schemas.execution import PaperPositionResponse
from app.services.position_monitoring.repository import (
    PortfolioPositionTotals,
    PositionLineage,
    PositionMonitoringRepository,
    PositionMonitoringSources,
)
from app.services.position_monitoring.service import PositionMonitoringService
from tests.test_execution_api import (
    FORECAST_ID,
    MARKET_ID,
    NOW,
    PORTFOLIO_ID,
    POSITION_ID,
    PRICE_ID,
    TEAM_ID,
    position_record,
    snapshot_record,
    trade_record,
)

EVENT_ID = UUID("87000000-0000-0000-0000-000000000001")
OTHER_TEAM_ID = UUID("87000000-0000-0000-0000-000000000002")
RESOLUTION_ID = UUID("87000000-0000-0000-0000-000000000003")


class FakeMonitoringRepository:
    def __init__(
        self,
        *,
        bid: Decimal = Decimal("0.5300"),
        model_probability: Decimal = Decimal("0.640000"),
        resolution: MarketResolutionRecord | None = None,
        market_status: str = "open",
    ) -> None:
        self.position = position_record()
        self.trade = trade_record()
        self.snapshot = snapshot_record()
        self.portfolio = SimpleNamespace(id=PORTFOLIO_ID)
        self.market = SimpleNamespace(id=MARKET_ID, status=market_status)
        self.event = SimpleNamespace(
            id=EVENT_ID,
            status="scheduled",
            postponed=False,
            scheduled_start_time=NOW + timedelta(hours=2),
        )
        self.match = SimpleNamespace(
            id=self.trade.market_event_match_id,
            sports_event_id=EVENT_ID,
            status="matched",
            automatic_trading_eligible=True,
        )
        self.forecast = SimpleNamespace(
            id=FORECAST_ID,
            sports_event_id=EVENT_ID,
            model_version_id=UUID("87000000-0000-0000-0000-000000000004"),
            purpose="operational",
            home_team_id=TEAM_ID,
            away_team_id=OTHER_TEAM_ID,
            home_win_probability=model_probability,
            away_win_probability=Decimal("1") - model_probability,
            generated_at=NOW,
        )
        self.price = SimpleNamespace(
            id=PRICE_ID,
            yes_bid=bid,
            no_bid=Decimal("1") - bid,
            retrieved_at=NOW,
        )
        self.resolutions: tuple[MarketResolutionRecord, ...] = (
            (resolution,) if resolution is not None else ()
        )
        self.events: dict[tuple[UUID, str, str], PositionEventRecord] = {}
        self.latest_event: PositionEventRecord | None = None
        self.commits = 0
        self.rollbacks = 0

    async def get_lineage(self, position_id: UUID) -> PositionLineage | None:
        if position_id != POSITION_ID:
            return None
        return PositionLineage(
            position=self.position,
            opening_trade=self.trade,
            opening_match=cast(MarketEventMatchRecord, self.match),
            opening_forecast=cast(BaseForecastRecord, self.forecast),
        )

    async def lock_portfolio(self, _: UUID) -> object:
        return self.portfolio

    async def lock_market(self, _: UUID) -> object:
        return self.market

    async def lock_event(self, _: UUID) -> object:
        return self.event

    async def lock_position(self, _: UUID) -> PaperPositionRecord:
        return self.position

    async def lock_latest_snapshot(self, _: UUID) -> PortfolioSnapshotRecord:
        return self.snapshot

    async def lock_sources(self, **_: object) -> PositionMonitoringSources:
        return PositionMonitoringSources(
            market=cast(PredictionMarketRecord, self.market),
            event=cast(SportsEventRecord, self.event),
            latest_match=cast(MarketEventMatchRecord, self.match),
            latest_price=cast(MarketPriceRecord, self.price),
            latest_forecast=cast(BaseForecastRecord, self.forecast),
            resolutions=self.resolutions,
        )

    async def database_time(self) -> datetime:
        return NOW + timedelta(minutes=1)

    async def portfolio_position_totals(self, _: UUID) -> PortfolioPositionTotals:
        open_position = self.position.status == "open"
        return PortfolioPositionTotals(
            committed_capital=(
                self.position.total_cost_basis if open_position else Decimal("0.00")
            ),
            open_position_value=(self.position.market_value if open_position else Decimal("0.00")),
            unrealized_pnl=(self.position.unrealized_pnl if open_position else Decimal("0.00")),
            realized_pnl=self.position.realized_pnl,
        )

    async def get_event_by_input(self, **kwargs: object) -> PositionEventRecord | None:
        key = (
            cast(UUID, kwargs["position_id"]),
            cast(str, kwargs["policy_version"]),
            cast(str, kwargs["input_fingerprint"]),
        )
        return self.events.get(key)

    async def stage_event(
        self,
        *,
        event: PositionEventRecord,
        snapshot: PortfolioSnapshotRecord | None,
    ) -> None:
        self.events[(event.position_id, event.policy_version, event.input_fingerprint)] = event
        self.latest_event = event
        if snapshot is not None:
            self.snapshot = snapshot

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def get_snapshot(self, _: UUID) -> PortfolioSnapshotRecord:
        return self.snapshot

    async def latest_event_for_position(self, _: UUID) -> PositionEventRecord | None:
        return self.latest_event


def service(repository: FakeMonitoringRepository) -> PositionMonitoringService:
    return PositionMonitoringService(
        repository=cast(PositionMonitoringRepository, repository),
        policy=PositionMonitoringPolicy(),
        runtime_trading_mode="paper",
    )


def test_hold_is_audited_and_same_source_replays_without_snapshot() -> None:
    repository = FakeMonitoringRepository()
    monitoring = service(repository)

    first = asyncio.run(monitoring.evaluate(POSITION_ID))
    replay = asyncio.run(monitoring.evaluate(POSITION_ID))

    assert first.created is True
    assert first.event.decision == "hold"
    assert first.event.reason_code == "minimum_hold_edge_met"
    assert first.event.state_changed is False
    assert first.snapshot is None
    assert first.position.version == 0
    assert replay.created is False
    assert replay.event.id == first.event.id
    assert repository.commits == 1


def test_weakened_edge_reduces_once_and_reconciles_partial_basis() -> None:
    repository = FakeMonitoringRepository(
        bid=Decimal("0.6000"),
        model_probability=Decimal("0.620000"),
    )
    monitoring = service(repository)

    first = asyncio.run(monitoring.evaluate(POSITION_ID))
    replay = asyncio.run(monitoring.evaluate(POSITION_ID))

    assert first.event.decision == "reduce"
    assert first.event.action_quantity == 18
    assert first.event.exit_price == Decimal("0.597500")
    assert first.event.net_proceeds == Decimal("10.73")
    assert first.event.allocated_total_cost_basis == Decimal("9.95")
    assert first.event.realized_pnl_increment == Decimal("0.78")
    assert first.position.quantity == 18
    assert first.position.total_cost_basis == Decimal("9.96")
    assert first.position.realized_pnl == Decimal("0.78")
    assert first.snapshot is not None
    assert first.snapshot.current_bankroll == Decimal("1000.78")
    assert first.snapshot.committed_capital == Decimal("9.96")
    assert first.snapshot.cash_balance == Decimal("990.82")
    assert replay.created is False
    assert replay.event.id == first.event.id
    assert replay.position.quantity == 18


def test_nonpositive_edge_closes_and_realizes_exit_pnl() -> None:
    repository = FakeMonitoringRepository(
        bid=Decimal("0.7000"),
        model_probability=Decimal("0.640000"),
    )

    result = asyncio.run(service(repository).evaluate(POSITION_ID))

    assert result.event.decision == "close"
    assert result.position.status == "closed"
    assert PaperPositionResponse.from_record(result.position).status.value == "closed"
    assert result.position.quantity == 0
    assert result.position.mark_basis == "exit_execution"
    assert result.position.closed_at == NOW + timedelta(minutes=1)
    assert result.snapshot is not None
    assert result.snapshot.reason == "paper_position_closed"
    assert result.snapshot.committed_capital == Decimal("0.00")
    assert result.snapshot.open_position_value == Decimal("0.00")
    assert result.snapshot.unrealized_pnl == Decimal("0.00")


def test_official_resolution_settles_without_using_sports_score() -> None:
    resolution = MarketResolutionRecord(
        id=RESOLUTION_ID,
        market_id=MARKET_ID,
        result="yes",
        yes_payout=Decimal("1.000000"),
        no_payout=Decimal("0.000000"),
        resolution_type="standard_binary",
        source="official_provider",
        settled_at=NOW,
        retrieved_at=NOW,
        input_fingerprint="f" * 64,
        source_snapshot={"provider_result": "yes"},
    )
    repository = FakeMonitoringRepository(
        bid=Decimal("0.1000"),
        model_probability=Decimal("0.000000"),
        resolution=resolution,
        market_status="finalized",
    )

    result = asyncio.run(service(repository).evaluate(POSITION_ID))

    assert result.event.decision == "settle"
    assert result.event.market_resolution_id == RESOLUTION_ID
    assert result.event.settlement_payout_per_contract == Decimal("1.000000")
    assert result.event.exit_price is None
    assert result.position.status == "settled"
    assert PaperPositionResponse.from_record(result.position).status.value == "settled"
    assert result.position.mark_basis == "settlement_payout"
    assert result.position.realized_pnl == Decimal("16.09")
    assert result.snapshot is not None
    assert result.snapshot.current_bankroll == Decimal("1016.09")
    assert result.snapshot.cash_balance == Decimal("1016.09")
    assert result.snapshot.reason == "paper_position_settled"


def test_closed_market_without_typed_resolution_stays_pending() -> None:
    repository = FakeMonitoringRepository(market_status="closed")

    result = asyncio.run(service(repository).evaluate(POSITION_ID))

    assert result.event.decision == "hold"
    assert result.event.reason_code == "market_closed_unresolved"
    assert result.event.all_required_checks_passed is False
    assert result.position.status == "open"
    assert result.snapshot is None


def test_unknown_position_is_not_found() -> None:
    repository = FakeMonitoringRepository()

    try:
        asyncio.run(service(repository).evaluate(UUID(int=0)))
    except LookupError as exc:
        assert str(exc) == "position not found"
    else:
        raise AssertionError("unknown position should raise LookupError")
