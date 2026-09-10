from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest

from app.domain.position_monitoring import PositionMonitoringAction, PositionMonitoringPolicy
from app.models.markets import MarketResolutionRecord
from app.services.position_monitoring.repository import PositionMonitoringRepository
from app.services.position_monitoring.service import PositionMonitoringService
from tests.test_execution_api import MARKET_ID, NOW, POSITION_ID
from tests.test_position_monitoring_engine import accounting_state, engine, monitoring_input
from tests.test_position_monitoring_service import FakeMonitoringRepository, service


def _resolution(payout: str = "0.500000", identifier: int = 801) -> MarketResolutionRecord:
    yes = Decimal(payout)
    return MarketResolutionRecord(
        id=UUID(int=identifier),
        market_id=MARKET_ID,
        result="scalar",
        yes_payout=yes,
        no_payout=Decimal("1") - yes,
        resolution_type="fractional_binary",
        source="official_provider",
        settled_at=NOW,
        retrieved_at=NOW,
        input_fingerprint=f"{identifier:064x}",
        source_snapshot={"provider_result": "scalar"},
    )


@pytest.mark.parametrize("direction", ["yes", "no"])
def test_half_payout_service_settlement_and_replay(direction: str) -> None:
    repository = FakeMonitoringRepository(resolution=_resolution(), market_status="finalized")
    repository.position.direction = direction
    repository.trade.direction = direction
    monitoring = service(repository)
    first = asyncio.run(monitoring.evaluate(POSITION_ID))
    assert first.created is True
    assert first.event.decision == "settle"
    assert first.event.settlement_payout_per_contract == Decimal("0.500000")
    assert first.event.net_proceeds == Decimal("18.00")
    assert first.position.quantity == 0 and first.position.status == "settled"
    assert first.position.realized_pnl == Decimal("-1.91")
    assert first.snapshot is not None
    assert first.snapshot.cash_balance == Decimal("998.09")
    assert first.snapshot.current_bankroll == Decimal("998.09")
    before_version = first.position.version
    replay = asyncio.run(monitoring.evaluate(POSITION_ID))
    assert replay.created is False and replay.event.id == first.event.id
    assert replay.position.version == before_version
    assert replay.snapshot is not None and replay.snapshot.id == first.snapshot.id
    assert repository.commits == 1 and len(repository.events) == 1


@pytest.mark.parametrize(("direction", "proceeds"), [("yes", "11.99"), ("no", "24.00")])
def test_fractional_service_directional_payout_floors_to_cents(
    direction: str,
    proceeds: str,
) -> None:
    repository = FakeMonitoringRepository(
        resolution=_resolution("0.333333"), market_status="finalized"
    )
    repository.position.direction = direction
    repository.trade.direction = direction
    result = asyncio.run(service(repository).evaluate(POSITION_ID))
    assert result.event.net_proceeds == Decimal(proceeds)
    assert result.position.realized_pnl == Decimal(proceeds) - Decimal("19.91")
    assert result.snapshot is not None
    assert result.snapshot.cash_balance == Decimal("980.09") + Decimal(proceeds)


def test_partial_reduction_then_fractional_service_settles_remaining_only() -> None:
    repository = FakeMonitoringRepository(
        bid=Decimal("0.6000"), model_probability=Decimal("0.620000")
    )
    monitoring = service(repository)
    reduced = asyncio.run(monitoring.evaluate(POSITION_ID))
    assert reduced.event.decision == "reduce" and reduced.position.quantity == 18
    prior_realized = reduced.position.realized_pnl
    remaining_basis = reduced.position.total_cost_basis
    assert reduced.snapshot is not None
    prior_cash = reduced.snapshot.cash_balance
    repository.market.status = "finalized"
    repository.resolutions = (_resolution(),)
    settled = asyncio.run(monitoring.evaluate(POSITION_ID))
    assert settled.event.action_quantity == 18
    assert settled.event.net_proceeds == Decimal("9.00")
    assert settled.event.allocated_total_cost_basis == remaining_basis
    assert settled.position.realized_pnl == prior_realized + Decimal("9.00") - remaining_basis
    assert settled.position.quantity == 0 and settled.position.disposed_quantity == 36
    assert settled.snapshot is not None and settled.snapshot.cash_balance == prior_cash + Decimal(
        "9"
    )
    replay = asyncio.run(monitoring.evaluate(POSITION_ID))
    assert replay.created is False and len(repository.events) == 2


def test_pure_fractional_settlement_preserves_partial_accounting() -> None:
    state = accounting_state(
        disposed_quantity=4,
        remaining_quantity=6,
        remaining_gross=Decimal("2.40"),
        remaining_fees=Decimal("0.06"),
        market_value=Decimal("2.40"),
        unrealized_pnl=Decimal("-0.06"),
        realized_pnl=Decimal("0.50"),
    )
    result = engine().evaluate(
        monitoring_input(
            position=state,
            official_resolution_id=UUID(int=801),
            official_resolution_is_final=True,
            official_held_side_payout=Decimal("0.333333"),
        )
    )
    assert result.action is PositionMonitoringAction.SETTLE and result.economics is not None
    assert result.economics.net_proceeds == Decimal("1.99")
    assert result.economics.realized_pnl_increment == Decimal("-0.47")
    assert result.after.realized_pnl == Decimal("0.03")
    assert result.after.disposed_quantity == 10 and result.after.remaining_quantity == 0


def test_fractional_resolution_cannot_bypass_nonpaper_guard() -> None:
    repository = FakeMonitoringRepository(resolution=_resolution(), market_status="finalized")
    monitoring = PositionMonitoringService(
        repository=cast(PositionMonitoringRepository, repository),
        policy=PositionMonitoringPolicy(),
        runtime_trading_mode="live",
    )
    result = asyncio.run(monitoring.evaluate(POSITION_ID))
    assert result.event.decision == "hold" and result.event.reason_code == "paper_only"
    assert result.position.quantity == 36 and result.position.status == "open"
    assert result.snapshot is None


@pytest.mark.parametrize("conflict", [False, True])
def test_missing_or_conflicting_fractional_resolution_never_settles(conflict: bool) -> None:
    repository = FakeMonitoringRepository(market_status="finalized")
    if conflict:
        repository.resolutions = (_resolution(), _resolution("0.333333", 802))
    result = asyncio.run(service(repository).evaluate(POSITION_ID))
    assert result.event.decision == "hold"
    assert result.position.quantity == 36 and result.position.status == "open"
    assert result.position.realized_pnl == Decimal("0.00")
    assert result.snapshot is None
