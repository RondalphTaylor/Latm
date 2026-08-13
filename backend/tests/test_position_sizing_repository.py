from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import cast
from uuid import UUID

from sqlalchemy import Table
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ClauseElement, Executable

from app.models.portfolio import (
    PortfolioRecord,
    PortfolioSnapshotRecord,
    PositionSizeProposalRecord,
)
from app.services.position_sizing.repository import (
    PositionSizingRepository,
    portfolio_record_id,
    portfolio_snapshot_record_id,
)


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


def test_database_models_enforce_paper_accounting_and_pre_risk_state() -> None:
    portfolio = cast(Table, PortfolioRecord.__table__)
    snapshot = cast(Table, PortfolioSnapshotRecord.__table__)
    proposal = cast(Table, PositionSizeProposalRecord.__table__)
    portfolio_constraints = {item.name for item in portfolio.constraints}
    snapshot_constraints = {item.name for item in snapshot.constraints}
    proposal_constraints = {item.name for item in proposal.constraints}

    assert {
        "uq_portfolios_idempotency_key",
        "ck_portfolios_paper_only",
        "ck_portfolios_starting_bankroll",
    } <= portfolio_constraints
    assert {
        "uq_portfolio_snapshots_sequence",
        "ck_portfolio_snapshots_current_bankroll",
        "ck_portfolio_snapshots_cash_balance",
        "ck_portfolio_snapshots_available_bankroll",
        "ck_portfolio_snapshots_created_state",
    } <= snapshot_constraints
    assert {
        "uq_position_size_proposals_semantic_input",
        "fk_position_size_proposals_snapshot_portfolio",
        "ck_position_size_proposals_paper_only",
        "ck_position_size_proposals_state",
        "ck_position_size_proposals_actual_exposure",
        "ck_position_size_proposals_times",
    } <= proposal_constraints


def test_portfolio_and_initial_snapshot_ids_are_stable() -> None:
    portfolio_id = portfolio_record_id("primary")

    assert portfolio_id == portfolio_record_id("primary")
    assert portfolio_id != portfolio_record_id("other")
    assert portfolio_snapshot_record_id(portfolio_id, 0) == portfolio_snapshot_record_id(
        portfolio_id, 0
    )
    assert portfolio_snapshot_record_id(portfolio_id, 0) != portfolio_snapshot_record_id(
        portfolio_id, 1
    )


def test_proposal_history_query_forwards_filters_and_ordering() -> None:
    session = RecordingSession()
    repository = PositionSizingRepository(cast(AsyncSession, session))
    portfolio_id = UUID("80000000-0000-0000-0000-000000000001")

    asyncio.run(
        repository.list_proposals(
            portfolio_id=portfolio_id,
            opportunity_id=UUID("80000000-0000-0000-0000-000000000002"),
            market_id=UUID("80000000-0000-0000-0000-000000000003"),
            direction="yes",
            strategy_version="1.0.0+cfg.abcdef123456",
            limit=25,
            offset=2,
        )
    )

    sql = str(session.statements[0])
    assert "position_size_proposals.portfolio_id" in sql
    assert "position_size_proposals.opportunity_id" in sql
    assert "position_size_proposals.market_id" in sql
    assert "position_size_proposals.direction" in sql
    assert "position_size_proposals.strategy_version" in sql
    assert "position_size_proposals.proposed_at DESC" in sql
