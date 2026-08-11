from __future__ import annotations

import asyncio
from collections.abc import Sequence
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import Table
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ClauseElement, Executable

from app.domain.opportunities import (
    OpportunityDirection,
    OpportunityPolicy,
    OpportunityStatus,
)
from app.models.opportunities import OpportunityRecord
from app.services.opportunities.engine import RawEdgeOpportunityEngine
from app.services.opportunities.repository import (
    OpportunityRepository,
    opportunity_record_id,
)
from tests.test_opportunity_engine import evaluation_input


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


def test_database_model_declares_audit_and_classification_constraints() -> None:
    table = cast(Table, OpportunityRecord.__table__)
    constraints = {constraint.name for constraint in table.constraints}

    assert {
        "uq_opportunities_semantic_input",
        "ck_opportunities_probability_range",
        "ck_opportunities_raw_edge",
        "ck_opportunities_status_edge",
        "ck_opportunities_orientation",
        "ck_opportunities_valid_until",
    } <= constraints


def test_opportunity_ids_are_stable_and_direction_specific() -> None:
    engine = RawEdgeOpportunityEngine(OpportunityPolicy())
    yes = engine.evaluate(evaluation_input(market_probability=Decimal("0.50")))
    no_source = evaluation_input(
        market_probability=Decimal("0.50"),
        direction=OpportunityDirection.NO,
    )
    no = engine.evaluate(no_source)

    assert opportunity_record_id(yes) == opportunity_record_id(yes)
    assert opportunity_record_id(yes) != opportunity_record_id(no)


def test_latest_list_ranks_before_status_and_model_filters() -> None:
    session = RecordingSession()
    repository = OpportunityRepository(cast(AsyncSession, session))

    asyncio.run(
        repository.list_opportunities(
            latest_only=True,
            current_only=True,
            status=OpportunityStatus.WATCH,
            direction=OpportunityDirection.YES,
            market_id=UUID("30000000-0000-0000-0000-000000000001"),
            sports_event_id=None,
            model_name="nba_elo",
            model_version=None,
            limit=25,
            offset=2,
        )
    )

    sql = str(session.statements[0])
    assert "row_number() OVER (PARTITION BY opportunities.market_id" in sql
    assert "opportunities.direction" in sql
    assert "opportunities.strategy_version" in sql
    assert "opportunities.model_version_id" in sql
    assert "opportunities.status" in sql
    assert "model_versions.model_name" in sql
    assert "opportunities.valid_until" in sql
    assert "market_prices.retrieved_at DESC" in sql
    assert "market_event_matches.evaluated_at DESC" in sql
