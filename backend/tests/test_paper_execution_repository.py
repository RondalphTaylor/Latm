from __future__ import annotations

import asyncio
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import PaperPositionRecord, PaperTradeRecord
from app.models.portfolio import PortfolioSnapshotRecord
from app.services.execution.repository import PaperExecutionRepository


def test_execution_models_expose_single_use_and_open_intent_backstops() -> None:
    trade_table = cast(Table, PaperTradeRecord.__table__)
    position_table = cast(Table, PaperPositionRecord.__table__)
    trade_constraints = {item.name for item in trade_table.constraints if item.name is not None}
    position_constraints = {
        item.name for item in position_table.constraints if item.name is not None
    }
    position_indexes = {item.name for item in position_table.indexes}

    assert "uq_trades_risk_decision" in trade_constraints
    assert "ck_trades_terminal_state" in trade_constraints
    assert "ck_trades_fill_accounting" in trade_constraints
    assert "uq_positions_opening_trade" in position_constraints
    assert "ck_positions_accounting" in position_constraints
    assert "uq_positions_open_portfolio_market" in position_indexes


def test_atomic_fill_commits_once_after_two_flushes() -> None:
    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    repository = PaperExecutionRepository(cast(AsyncSession, session))

    asyncio.run(
        repository.persist_fill(
            snapshot=cast(PortfolioSnapshotRecord, object()),
            trade=cast(PaperTradeRecord, object()),
            position=cast(PaperPositionRecord, object()),
        )
    )

    assert session.add.call_count == 3
    assert session.flush.await_count == 2
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


def test_atomic_fill_rolls_back_every_effect_when_persistence_fails() -> None:
    session = MagicMock(spec=AsyncSession)
    session.flush = AsyncMock(side_effect=[None, RuntimeError("injected failure")])
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    repository = PaperExecutionRepository(cast(AsyncSession, session))

    with pytest.raises(RuntimeError, match="injected failure"):
        asyncio.run(
            repository.persist_fill(
                snapshot=cast(PortfolioSnapshotRecord, object()),
                trade=cast(PaperTradeRecord, object()),
                position=cast(PaperPositionRecord, object()),
            )
        )

    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()
