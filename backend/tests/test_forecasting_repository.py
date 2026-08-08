from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import Table
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ClauseElement, Executable

from app.domain.forecasts import ForecastPurpose
from app.models.forecasts import BaseForecastRecord, ModelVersionRecord
from app.services.forecasting.repository import (
    ForecastRepository,
    model_version_record_id,
)


class ScalarResult:
    def __init__(self, values: Sequence[object]) -> None:
        self._values = list(values)

    def all(self) -> list[object]:
        return self._values

    def unique(self) -> ScalarResult:
        return self

    def one_or_none(self) -> object | None:
        return self._values[0] if self._values else None


class RecordingSession:
    def __init__(self) -> None:
        self.statements: list[ClauseElement] = []

    async def scalars(self, statement: Executable) -> ScalarResult:
        self.statements.append(cast(ClauseElement, statement))
        return ScalarResult([])


def test_database_models_declare_reproducibility_constraints() -> None:
    model_table = cast(Table, ModelVersionRecord.__table__)
    forecast_table = cast(Table, BaseForecastRecord.__table__)
    model_constraints = {constraint.name for constraint in model_table.constraints}
    forecast_constraints = {constraint.name for constraint in forecast_table.constraints}

    assert {
        "uq_model_versions_identity",
        "ck_model_versions_fingerprint_length",
    } <= model_constraints
    assert {
        "uq_base_forecasts_semantic_input",
        "ck_base_forecasts_probability_range",
        "ck_base_forecasts_probability_sum",
        "ck_base_forecasts_distinct_teams",
        "ck_base_forecasts_purpose",
        "ck_base_forecasts_counts",
        "ck_base_forecasts_fingerprint_lengths",
    } <= forecast_constraints


def test_model_registry_ids_are_stable_and_parameter_specific() -> None:
    first = model_version_record_id("nba_elo", "1.0.0+cfg.aaaaaaaaaaaa")

    assert first == model_version_record_id("nba_elo", "1.0.0+cfg.aaaaaaaaaaaa")
    assert first != model_version_record_id("nba_elo", "1.0.0+cfg.bbbbbbbbbbbb")


def test_operational_target_query_requires_latest_eligible_match() -> None:
    session = RecordingSession()
    repository = ForecastRepository(cast(AsyncSession, session))
    run_at = datetime(2026, 8, 1, 12, tzinfo=UTC)

    asyncio.run(
        repository.list_forecast_targets(
            provider_name="balldontlie",
            purpose=ForecastPurpose.OPERATIONAL,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            run_at=run_at,
            event_id=None,
            limit=25,
            offset=2,
        )
    )

    sql = str(session.statements[0])
    assert "row_number() OVER (PARTITION BY market_event_matches.market_id" in sql
    assert "market_event_matches.automatic_trading_eligible" in sql
    assert "sports_events.status" in sql
    assert "sports_events.scheduled_start_time >" in sql
    assert "sports_events.postponed IS false" in sql


def test_historical_targets_and_training_history_are_final_and_provider_scoped() -> None:
    session = RecordingSession()
    repository = ForecastRepository(cast(AsyncSession, session))
    cutoff = datetime(2026, 8, 2, 23, tzinfo=UTC)

    asyncio.run(
        repository.list_forecast_targets(
            provider_name="balldontlie",
            purpose=ForecastPurpose.HISTORICAL_REPLAY,
            start_date=cutoff.date(),
            end_date=cutoff.date(),
            run_at=cutoff,
            event_id=UUID("097a5608-2ba1-4aa1-8096-07a8bc2ff24b"),
            limit=25,
            offset=0,
        )
    )
    asyncio.run(repository.list_final_history(provider_name="balldontlie", before=cutoff))

    target_sql, history_sql = (str(statement) for statement in session.statements)
    assert "sports_events.status" in target_sql
    assert "sports_events.home_score IS NOT NULL" in target_sql
    assert "sports_events.home_score != sports_events.away_score" in target_sql
    assert "sports_events.provider_name" in history_sql
    assert "sports_events.scheduled_start_time <" in history_sql
    assert "sports_events.status" in history_sql


def test_latest_forecast_query_ranks_before_filters() -> None:
    session = RecordingSession()
    repository = ForecastRepository(cast(AsyncSession, session))

    asyncio.run(
        repository.list_forecasts(
            latest_only=True,
            purpose=ForecastPurpose.OPERATIONAL,
            sports_event_id=None,
            model_name="nba_elo",
            model_version=None,
            limit=100,
            offset=0,
        )
    )

    sql = str(session.statements[0])
    assert "row_number() OVER (PARTITION BY base_forecasts.sports_event_id" in sql
    assert "base_forecasts.purpose" in sql
    assert "model_versions.model_name" in sql
