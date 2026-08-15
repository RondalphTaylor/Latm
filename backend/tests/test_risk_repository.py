from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import cast
from uuid import UUID

from sqlalchemy import Table
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ClauseElement, Executable

from app.domain.risk import RiskDecisionType, RiskPolicy
from app.models.risk import RiskDecisionRecord
from app.services.risk.engine import DeterministicRiskEngine
from app.services.risk.repository import RiskRepository, risk_decision_record_id
from tests.test_risk_engine import risk_input


class ScalarResult:
    def __init__(self, values: Sequence[object]) -> None:
        self._values = list(values)

    def all(self) -> list[object]:
        return self._values

    def unique(self) -> ScalarResult:
        return self


class RecordingSession:
    def __init__(self) -> None:
        self.statements: list[ClauseElement] = []

    async def scalars(self, statement: Executable) -> ScalarResult:
        self.statements.append(cast(ClauseElement, statement))
        return ScalarResult([])


def test_risk_model_enforces_append_only_paper_authorization_invariants() -> None:
    table = cast(Table, RiskDecisionRecord.__table__)
    constraints = {item.name for item in table.constraints}

    assert {
        "uq_risk_decisions_semantic_input",
        "ck_risk_decisions_paper_only",
        "ck_risk_decisions_direction",
        "ck_risk_decisions_outcome_consistency",
        "ck_risk_decisions_evidence_bases",
        "ck_risk_decisions_check_counts",
    } <= constraints


def test_risk_decision_ids_are_semantically_stable() -> None:
    decision = DeterministicRiskEngine(RiskPolicy()).evaluate(risk_input())

    assert risk_decision_record_id(decision) == risk_decision_record_id(decision)
    changed = decision.model_copy(update={"input_fingerprint": "f" * 64})
    assert risk_decision_record_id(changed) != risk_decision_record_id(decision)


def test_history_query_ranks_before_filtering_and_names_expiry_honestly() -> None:
    session = RecordingSession()
    repository = RiskRepository(cast(AsyncSession, session))

    asyncio.run(
        repository.list_decisions(
            latest_only=True,
            unexpired_only=True,
            current_at=risk_input().evaluated_at,
            proposal_id=UUID("83000000-0000-0000-0000-000000000001"),
            portfolio_id=UUID("83000000-0000-0000-0000-000000000002"),
            market_id=UUID("83000000-0000-0000-0000-000000000003"),
            decision=RiskDecisionType.AUTO_APPROVE,
            risk_policy_version="1.0.0+cfg.abcdef123456",
            limit=25,
            offset=2,
        )
    )

    sql = str(session.statements[0])
    assert "row_number() OVER" in sql
    assert "risk_decisions.authorization_valid_until >" in sql
    assert "risk_decisions.position_size_proposal_id" in sql
    assert "risk_decisions.portfolio_id" in sql
    assert "risk_decisions.market_id" in sql
    assert "risk_decisions.decision" in sql
    assert "risk_decisions.risk_policy_version" in sql
