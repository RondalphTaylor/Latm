from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.execution import (
    get_paper_execution_repository,
    get_paper_execution_service,
)
from app.main import create_app
from app.models.execution import PaperPositionRecord, PaperTradeRecord
from app.models.portfolio import PortfolioSnapshotRecord
from app.services.execution.service import (
    PaperExecutionConflictError,
    PaperExecutionResult,
)

NOW = datetime(2026, 8, 17, 12, 2, tzinfo=UTC)
TRADE_ID = UUID("86000000-0000-0000-0000-000000000001")
RISK_ID = UUID("86000000-0000-0000-0000-000000000002")
PROPOSAL_ID = UUID("86000000-0000-0000-0000-000000000003")
PORTFOLIO_ID = UUID("86000000-0000-0000-0000-000000000004")
SNAPSHOT_BEFORE_ID = UUID("86000000-0000-0000-0000-000000000005")
SNAPSHOT_AFTER_ID = UUID("86000000-0000-0000-0000-000000000006")
OPPORTUNITY_ID = UUID("86000000-0000-0000-0000-000000000007")
MARKET_ID = UUID("86000000-0000-0000-0000-000000000008")
TEAM_ID = UUID("86000000-0000-0000-0000-000000000009")
MATCH_ID = UUID("86000000-0000-0000-0000-000000000010")
PRICE_ID = UUID("86000000-0000-0000-0000-000000000011")
FORECAST_ID = UUID("86000000-0000-0000-0000-000000000012")
POSITION_ID = UUID("86000000-0000-0000-0000-000000000013")
UNKNOWN_ID = UUID("86000000-0000-0000-0000-000000000099")


def trade_record() -> PaperTradeRecord:
    return PaperTradeRecord(
        id=TRADE_ID,
        risk_decision_id=RISK_ID,
        position_size_proposal_id=PROPOSAL_ID,
        portfolio_id=PORTFOLIO_ID,
        portfolio_snapshot_before_id=SNAPSHOT_BEFORE_ID,
        portfolio_snapshot_after_id=SNAPSHOT_AFTER_ID,
        opportunity_id=OPPORTUNITY_ID,
        market_id=MARKET_ID,
        outcome_team_id=TEAM_ID,
        market_event_match_id=MATCH_ID,
        market_price_id=PRICE_ID,
        base_forecast_id=FORECAST_ID,
        execution_mode="paper",
        action="buy",
        direction="yes",
        status="filled",
        reason_code="paper_entry_filled",
        reason="Automatic risk authorization filled in paper mode.",
        failed_rules=[],
        check_results=[
            {
                "rule": "paper_runtime_mode",
                "passed": True,
                "actual": "paper",
                "expected": "paper",
                "detail": "Only paper execution is available.",
            }
        ],
        proposed_capital=Decimal("20.00"),
        reference_price=Decimal("0.550000"),
        execution_price=Decimal("0.552500"),
        slippage_bps=Decimal("25.00"),
        slippage_amount_per_contract=Decimal("0.002500"),
        requested_quantity=36,
        executed_quantity=36,
        reference_gross_cost=Decimal("19.80"),
        gross_cost=Decimal("19.89"),
        slippage_cost=Decimal("0.09"),
        fee_bps=Decimal("10.00"),
        fee_amount=Decimal("0.02"),
        total_cost=Decimal("19.91"),
        unused_capital=Decimal("0.09"),
        effective_unit_cost=Decimal("0.553056"),
        model_probability=Decimal("0.640000"),
        raw_edge=Decimal("0.090000"),
        adjusted_edge=Decimal("0.086944"),
        mark_price=Decimal("0.530000"),
        mark_basis="directional_bid",
        market_value=Decimal("19.08"),
        unrealized_pnl=Decimal("-0.83"),
        sizing_strategy_version="1.0.0+cfg.sizing",
        risk_policy_version="1.0.0+cfg.risk",
        execution_policy_name="paper_immediate_fill",
        execution_policy_version="1.0.0+cfg.execution",
        execution_policy_fingerprint="a" * 64,
        risk_input_fingerprint="b" * 64,
        input_fingerprint="c" * 64,
        attempted_at=NOW,
        executed_at=NOW,
        audit_snapshot={"fill_model": "immediate"},
    )


def position_record() -> PaperPositionRecord:
    return PaperPositionRecord(
        id=POSITION_ID,
        opening_trade_id=TRADE_ID,
        portfolio_id=PORTFOLIO_ID,
        market_id=MARKET_ID,
        outcome_team_id=TEAM_ID,
        market_price_id=PRICE_ID,
        execution_mode="paper",
        direction="yes",
        status="open",
        quantity=36,
        average_entry_price=Decimal("0.552500"),
        gross_cost_basis=Decimal("19.89"),
        entry_fees=Decimal("0.02"),
        total_cost_basis=Decimal("19.91"),
        mark_price=Decimal("0.530000"),
        mark_basis="directional_bid",
        market_value=Decimal("19.08"),
        unrealized_pnl=Decimal("-0.83"),
        realized_pnl=Decimal("0.00"),
        input_fingerprint="c" * 64,
        opened_at=NOW,
        updated_at=NOW,
    )


def snapshot_record() -> PortfolioSnapshotRecord:
    return PortfolioSnapshotRecord(
        id=SNAPSHOT_AFTER_ID,
        portfolio_id=PORTFOLIO_ID,
        sequence=1,
        execution_mode="paper",
        currency="USD",
        starting_bankroll=Decimal("1000.00"),
        current_bankroll=Decimal("1000.00"),
        cash_balance=Decimal("980.09"),
        reserved_capital=Decimal("0.00"),
        committed_capital=Decimal("19.91"),
        available_bankroll=Decimal("980.09"),
        realized_pnl=Decimal("0.00"),
        open_position_value=Decimal("19.08"),
        unrealized_pnl=Decimal("-0.83"),
        total_portfolio_value=Decimal("999.17"),
        previous_snapshot_id=SNAPSHOT_BEFORE_ID,
        reason="paper_entry_filled",
        state_fingerprint="d" * 64,
        captured_at=NOW,
    )


def execution_result(*, created: bool) -> PaperExecutionResult:
    return PaperExecutionResult(
        trade=trade_record(),
        position=position_record(),
        snapshot=snapshot_record(),
        created=created,
    )


class FakeExecutionService:
    def __init__(
        self,
        results: list[PaperExecutionResult] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.results = results or []
        self.error = error
        self.risk_decision_ids: list[UUID] = []

    async def execute(self, risk_decision_id: UUID) -> PaperExecutionResult:
        self.risk_decision_ids.append(risk_decision_id)
        if self.error is not None:
            raise self.error
        if not self.results:
            raise AssertionError("fake execution service has no result")
        return self.results.pop(0)


class FakeExecutionRepository:
    def __init__(self) -> None:
        self.trade = trade_record()
        self.position = position_record()
        self.trade_filters: dict[str, object] | None = None
        self.position_filters: dict[str, object] | None = None

    async def list_trades(self, **kwargs: object) -> list[PaperTradeRecord]:
        self.trade_filters = kwargs
        return [self.trade]

    async def get_trade(self, trade_id: UUID) -> PaperTradeRecord | None:
        return self.trade if trade_id == self.trade.id else None

    async def list_positions(self, **kwargs: object) -> list[PaperPositionRecord]:
        self.position_filters = kwargs
        return [self.position]

    async def get_position(self, position_id: UUID) -> PaperPositionRecord | None:
        return self.position if position_id == self.position.id else None


def api_client(
    *,
    service: FakeExecutionService | None = None,
    repository: FakeExecutionRepository | None = None,
) -> tuple[FastAPI, TestClient]:
    application = create_app()
    if service is not None:
        application.dependency_overrides[get_paper_execution_service] = lambda: service
    if repository is not None:
        application.dependency_overrides[get_paper_execution_repository] = lambda: repository
    return application, TestClient(application)


def test_post_execution_success_and_replay_return_complete_terminal_shape() -> None:
    service = FakeExecutionService(
        results=[execution_result(created=True), execution_result(created=False)]
    )
    _, client = api_client(service=service)

    with client:
        created = client.post(f"/paper-execution/run?risk_decision_id={RISK_ID}")
        replayed = client.post(f"/paper-execution/run?risk_decision_id={RISK_ID}")

    assert created.status_code == 200
    assert replayed.status_code == 200
    assert created.json()["created"] is True
    assert replayed.json()["created"] is False
    assert created.json()["trade"]["id"] == replayed.json()["trade"]["id"] == str(TRADE_ID)
    assert created.json()["trade"]["status"] == "filled"
    assert created.json()["trade"]["execution_mode"] == "paper"
    assert created.json()["trade"]["action"] == "buy"
    assert created.json()["position"]["id"] == str(POSITION_ID)
    assert created.json()["position"]["status"] == "open"
    assert created.json()["portfolio_snapshot"]["id"] == str(SNAPSHOT_AFTER_ID)
    assert created.json()["portfolio_snapshot"]["reason"] == "paper_entry_filled"
    assert service.risk_decision_ids == [RISK_ID, RISK_ID]


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_detail"),
    [
        (LookupError("risk decision not found"), 404, "risk decision not found"),
        (
            PaperExecutionConflictError("automatic approval required"),
            409,
            "automatic approval required",
        ),
    ],
)
def test_post_execution_maps_missing_and_conflicting_authorizations(
    error: Exception,
    expected_status: int,
    expected_detail: str,
) -> None:
    service = FakeExecutionService(error=error)
    _, client = api_client(service=service)

    with client:
        response = client.post(f"/paper-execution/run?risk_decision_id={RISK_ID}")

    assert response.status_code == expected_status
    assert response.json() == {"detail": expected_detail}


def test_trade_and_position_lists_forward_filters_and_details_return_404() -> None:
    repository = FakeExecutionRepository()
    _, client = api_client(repository=repository)

    with client:
        trades = client.get(
            f"/trades?portfolio_id={PORTFOLIO_ID}&market_id={MARKET_ID}"
            f"&risk_decision_id={RISK_ID}&status=filled&direction=yes&limit=25&offset=2"
        )
        trade = client.get(f"/trades/{TRADE_ID}")
        missing_trade = client.get(f"/trades/{UNKNOWN_ID}")
        positions = client.get(
            f"/positions?portfolio_id={PORTFOLIO_ID}&market_id={MARKET_ID}"
            "&status=open&direction=yes&limit=30&offset=3"
        )
        position = client.get(f"/positions/{POSITION_ID}")
        missing_position = client.get(f"/positions/{UNKNOWN_ID}")

    assert trades.status_code == trade.status_code == 200
    assert trades.json()[0]["id"] == trade.json()["id"] == str(TRADE_ID)
    assert missing_trade.status_code == 404
    assert missing_trade.json() == {"detail": "trade not found"}
    assert positions.status_code == position.status_code == 200
    assert positions.json()[0]["id"] == position.json()["id"] == str(POSITION_ID)
    assert missing_position.status_code == 404
    assert missing_position.json() == {"detail": "position not found"}
    assert repository.trade_filters == {
        "portfolio_id": PORTFOLIO_ID,
        "market_id": MARKET_ID,
        "risk_decision_id": RISK_ID,
        "status": "filled",
        "direction": "yes",
        "limit": 25,
        "offset": 2,
    }
    assert repository.position_filters == {
        "portfolio_id": PORTFOLIO_ID,
        "market_id": MARKET_ID,
        "status": "open",
        "direction": "yes",
        "limit": 30,
        "offset": 3,
    }


@pytest.mark.parametrize(
    "path",
    [
        "/trades?status=pending",
        "/trades?direction=buy",
        "/trades?limit=0",
        "/trades?limit=501",
        "/trades?offset=-1",
        "/positions?status=closed",
        "/positions?direction=sell",
        "/positions?limit=0",
        "/positions?limit=501",
        "/positions?offset=-1",
    ],
)
def test_invalid_enums_directions_and_pagination_are_rejected(path: str) -> None:
    repository = FakeExecutionRepository()
    _, client = api_client(repository=repository)

    with client:
        response = client.get(path)

    assert response.status_code == 422
    assert repository.trade_filters is None
    assert repository.position_filters is None


def test_execution_contract_exposes_no_live_or_provider_order_controls() -> None:
    service = FakeExecutionService(results=[execution_result(created=True)])
    application, client = api_client(service=service)
    operation = application.openapi()["paths"]["/paper-execution/run"]["post"]

    assert [parameter["name"] for parameter in operation["parameters"]] == ["risk_decision_id"]
    assert "requestBody" not in operation

    with client:
        response = client.post(
            f"/paper-execution/run?risk_decision_id={RISK_ID}"
            "&trading_mode=live&order_type=limit&provider_order_id=external"
        )

    assert response.status_code == 200
    assert service.risk_decision_ids == [RISK_ID]
    payload = response.json()
    assert payload["trade"]["execution_mode"] == "paper"
    assert payload["trade"]["action"] == "buy"
    assert "order_type" not in payload["trade"]
    assert "provider_order_id" not in payload["trade"]
