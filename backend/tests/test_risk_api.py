from __future__ import annotations

from typing import cast
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.risk import get_risk_repository, get_risk_service
from app.domain.risk import RiskDecisionType, RiskPolicy
from app.main import create_app
from app.models.risk import RiskDecisionRecord
from app.services.risk.engine import DeterministicRiskEngine
from app.services.risk.repository import RiskRepository, risk_decision_record_id
from app.services.risk.service import RiskRunResult, RiskService
from tests.test_risk_service import NOW, risk_context


def decision_record() -> RiskDecisionRecord:
    context = risk_context()
    service = RiskService(
        repository=cast(RiskRepository, object()),
        policy=RiskPolicy(),
        runtime_trading_mode="paper",
        active_sizing_strategy_version=context.proposal.strategy_version,
        clock=lambda: NOW,
    )
    decision = DeterministicRiskEngine(RiskPolicy()).evaluate(
        service._evaluation_input(context, NOW)
    )
    return RiskDecisionRecord(
        id=risk_decision_record_id(decision),
        **{
            **decision.model_dump(mode="python"),
            "decision": decision.decision.value,
            "escalation_band": decision.escalation_band.value,
            "failed_rules": list(decision.failed_rules),
            "check_results": [item.model_dump(mode="json") for item in decision.check_results],
            "market_event_match_id": context.latest_match.id,
            "market_price_id": context.latest_price.id,
            "base_forecast_id": context.latest_forecast.id,
        },
    )


class FakeRiskRepository:
    def __init__(self) -> None:
        self.record = decision_record()
        self.arguments: dict[str, object] | None = None

    async def list_decisions(self, **kwargs: object) -> list[RiskDecisionRecord]:
        self.arguments = kwargs
        proposal_id = kwargs.get("proposal_id")
        return (
            []
            if proposal_id not in {None, self.record.position_size_proposal_id}
            else [self.record]
        )

    async def get_decision(self, decision_id: UUID) -> RiskDecisionRecord | None:
        return self.record if decision_id == self.record.id else None

    async def list_proposal_ids(self, *, proposal_id: UUID | None, **_: object) -> list[UUID]:
        if proposal_id == self.record.position_size_proposal_id:
            return [proposal_id]
        return []


class FakeRiskService:
    async def run(self, **_: object) -> RiskRunResult:
        return RiskRunResult(
            risk_policy_name="mvp_risk",
            risk_policy_version="1.0.0+cfg.abcdef123456",
            examined=1,
            generated=1,
            persisted=1,
            decision_counts={"auto_approve": 1},
        )


def api_client(repository: FakeRiskRepository) -> tuple[FastAPI, TestClient]:
    application = create_app()
    application.dependency_overrides[get_risk_repository] = lambda: repository
    application.dependency_overrides[get_risk_service] = lambda: FakeRiskService()
    return application, TestClient(application)


def test_run_list_detail_and_proposal_history_expose_risk_audit_only() -> None:
    repository = FakeRiskRepository()
    _, client = api_client(repository)
    record = repository.record

    with client:
        run = client.post(
            f"/risk-decisions/run?proposal_id={record.position_size_proposal_id}&limit=25"
        )
        listed = client.get(
            f"/risk-decisions?portfolio_id={record.portfolio_id}"
            f"&market_id={record.market_id}&decision=auto_approve"
            "&latest_only=true&unexpired_only=true&limit=25&offset=2"
        )
        detail = client.get(f"/risk-decisions/{record.id}")
        history = client.get(
            f"/position-size-proposals/{record.position_size_proposal_id}/risk-decisions"
        )

    assert run.status_code == 200
    assert run.json()["decision_counts"] == {"auto_approve": 1}
    assert listed.status_code == 200
    assert listed.json()[0]["decision"] == "auto_approve"
    assert listed.json()[0]["confidence_basis"] == "not_available"
    assert listed.json()[0]["liquidity_basis"] == "not_evaluated_phase7"
    assert listed.json()[0]["check_results"]
    assert detail.status_code == 200
    assert history.status_code == 200
    assert repository.arguments is not None


def test_unknown_decision_and_proposal_return_404() -> None:
    repository = FakeRiskRepository()
    _, client = api_client(repository)
    unknown = UUID("84000000-0000-0000-0000-000000000099")

    with client:
        decision = client.get(f"/risk-decisions/{unknown}")
        proposal = client.get(f"/position-size-proposals/{unknown}/risk-decisions")

    assert decision.status_code == 404
    assert proposal.status_code == 404


def test_decision_enum_filter_is_validated() -> None:
    repository = FakeRiskRepository()
    _, client = api_client(repository)

    with client:
        invalid = client.get("/risk-decisions?decision=execute")

    assert invalid.status_code == 422
    assert repository.record.decision == RiskDecisionType.AUTO_APPROVE.value
