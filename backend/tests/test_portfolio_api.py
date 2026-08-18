from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.portfolio import (
    get_portfolio_service,
    get_position_sizing_repository,
    get_position_sizing_service,
)
from app.domain.portfolio import PositionSizingPolicy
from app.main import create_app
from app.models.portfolio import PositionSizeProposalRecord
from app.schemas.portfolio import PortfolioSnapshotResponse
from app.services.position_sizing.engine import RulesPositionSizer
from app.services.position_sizing.repository import PortfolioBundle
from app.services.position_sizing.service import (
    PortfolioCreationResult,
    PositionSizingRunResult,
)
from tests.test_position_sizing_engine import sizing_input
from tests.test_position_sizing_service import portfolio_bundle

NOW = datetime(2026, 8, 11, 12, tzinfo=UTC)
PROPOSAL_ID = UUID("90000000-0000-0000-0000-000000000001")


def proposal_record() -> PositionSizeProposalRecord:
    proposal = (
        RulesPositionSizer(PositionSizingPolicy())
        .evaluate(sizing_input(raw_edge=Decimal("0.080000")))
        .proposal
    )
    assert proposal is not None
    values = proposal.model_dump(mode="python")
    values["execution_mode"] = proposal.mode.value
    values["state"] = proposal.state.value
    values["confidence_basis"] = proposal.confidence_basis.value
    del values["mode"]
    return PositionSizeProposalRecord(id=PROPOSAL_ID, **values)


class FakeRepository:
    def __init__(self) -> None:
        self.bundle = portfolio_bundle()
        self.proposal = proposal_record()
        self.proposal_arguments: dict[str, object] | None = None

    async def list_portfolios(self, **_: object) -> list[PortfolioBundle]:
        return [self.bundle]

    async def get_portfolio(self, portfolio_id: UUID) -> PortfolioBundle | None:
        return self.bundle if portfolio_id == self.bundle.portfolio.id else None

    async def list_portfolio_snapshots(self, **_: object) -> list[object]:
        return [self.bundle.snapshot]

    async def list_proposals(self, **kwargs: object) -> list[PositionSizeProposalRecord]:
        self.proposal_arguments = kwargs
        return [self.proposal]

    async def get_proposal(self, proposal_id: UUID) -> PositionSizeProposalRecord | None:
        return self.proposal if proposal_id == self.proposal.id else None


class FakePortfolioService:
    async def create(self, **_: object) -> tuple[PortfolioBundle, PortfolioCreationResult]:
        bundle = portfolio_bundle()
        return bundle, PortfolioCreationResult(portfolio_id=bundle.portfolio.id, created=True)


class FakeSizingService:
    async def run(
        self,
        *,
        portfolio_id: UUID,
        opportunity_id: UUID | None,
        limit: int,
        offset: int,
    ) -> PositionSizingRunResult:
        return PositionSizingRunResult(
            portfolio_id=portfolio_id,
            portfolio_snapshot_id=portfolio_bundle().snapshot.id,
            strategy_name="raw_edge_bands",
            strategy_version="1.0.0+cfg.abcdef123456",
            examined=1,
            generated=1,
            persisted=1,
            invalidated_before_persist=0,
            band_counts={"candidate": 1},
            skip_counts={},
        )


def api_client(repository: FakeRepository) -> tuple[FastAPI, TestClient]:
    application = create_app()
    application.dependency_overrides[get_position_sizing_repository] = lambda: repository
    application.dependency_overrides[get_portfolio_service] = lambda: FakePortfolioService()
    application.dependency_overrides[get_position_sizing_service] = lambda: FakeSizingService()
    return application, TestClient(application)


def test_create_list_detail_and_snapshot_routes_are_paper_only() -> None:
    repository = FakeRepository()
    _, client = api_client(repository)
    portfolio_id = repository.bundle.portfolio.id

    with client:
        created = client.post("/portfolios", json={})
        listed = client.get("/portfolios")
        detail = client.get(f"/portfolios/{portfolio_id}")
        snapshots = client.get(f"/portfolios/{portfolio_id}/snapshots")
        live = client.post("/portfolios", json={"execution_mode": "live"})

    assert created.status_code == 200
    assert created.json()["created"] is True
    assert created.json()["execution_mode"] == "paper"
    assert created.json()["latest_snapshot"]["available_bankroll"] == "1000.00"
    assert listed.status_code == 200
    assert detail.status_code == 200
    assert snapshots.status_code == 200
    assert live.status_code == 422


def test_sizing_run_and_proposal_history_expose_pre_risk_audit() -> None:
    repository = FakeRepository()
    _, client = api_client(repository)
    portfolio_id = repository.bundle.portfolio.id
    opportunity_id = repository.proposal.opportunity_id

    with client:
        run = client.post(
            f"/position-sizing/run?portfolio_id={portfolio_id}"
            f"&opportunity_id={opportunity_id}&limit=25&offset=2"
        )
        proposals = client.get(
            f"/position-size-proposals?portfolio_id={portfolio_id}"
            f"&opportunity_id={opportunity_id}&direction=yes"
            "&strategy_version=1.0.0%2Bcfg.abcdef123456&limit=25&offset=2"
        )
        detail = client.get(f"/position-size-proposals/{PROPOSAL_ID}")

    assert run.status_code == 200
    assert run.json()["persisted"] == 1
    assert proposals.status_code == 200
    assert proposals.json()[0]["state"] == "awaiting_risk"
    assert proposals.json()[0]["confidence_basis"] == "not_available"
    assert proposals.json()[0]["proposed_capital"] == "20.00"
    assert detail.status_code == 200
    assert repository.proposal_arguments == {
        "portfolio_id": portfolio_id,
        "opportunity_id": opportunity_id,
        "market_id": None,
        "direction": "yes",
        "strategy_version": "1.0.0+cfg.abcdef123456",
        "limit": 25,
        "offset": 2,
    }


def test_snapshot_schema_preserves_legitimate_zero_equity_values() -> None:
    record = portfolio_bundle().snapshot
    record.current_bankroll = Decimal("1000.00")
    record.cash_balance = Decimal("0.00")
    record.committed_capital = Decimal("1000.00")
    record.available_bankroll = Decimal("0.00")
    record.open_position_value = Decimal("0.00")
    record.unrealized_pnl = Decimal("-1000.00")
    record.total_portfolio_value = Decimal("0.00")

    response = PortfolioSnapshotResponse.from_record(record)

    assert response.open_position_value == Decimal("0.00")
    assert response.unrealized_pnl == Decimal("-1000.00")
    assert response.total_portfolio_value == Decimal("0.00")


def test_unknown_portfolio_and_proposal_return_404() -> None:
    repository = FakeRepository()
    _, client = api_client(repository)
    unknown = UUID("90000000-0000-0000-0000-000000000099")

    with client:
        portfolio = client.get(f"/portfolios/{unknown}")
        proposal = client.get(f"/position-size-proposals/{unknown}")

    assert portfolio.status_code == 404
    assert proposal.status_code == 404
