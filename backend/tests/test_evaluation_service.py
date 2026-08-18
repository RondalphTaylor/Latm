from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

import pytest

from app.domain.forecasts import ForecastPurpose
from app.models.forecasts import BaseForecastRecord, ModelVersionRecord
from app.models.sports import SportsEventRecord
from app.services.evaluation.repository import (
    EvaluationRepository,
    ForecastEvaluationCandidate,
    ForecastEvaluationPersistence,
)
from app.services.evaluation.service import ForecastEvaluationService

NOW = datetime(2026, 8, 18, 16, tzinfo=UTC)
TIP = NOW - timedelta(days=1)
HOME_ID = UUID("c1000000-0000-0000-0000-000000000001")
AWAY_ID = UUID("c1000000-0000-0000-0000-000000000002")
EVENT_ID = UUID("c1000000-0000-0000-0000-000000000003")
MODEL_ID = UUID("c1000000-0000-0000-0000-000000000004")
FORECAST_ID = UUID("c1000000-0000-0000-0000-000000000005")


class FakeEvaluationRepository:
    def __init__(self, candidate: ForecastEvaluationCandidate) -> None:
        self.candidate = candidate
        self.persisted: list[ForecastEvaluationPersistence] = []

    async def list_forecast_candidates(self, **_: object) -> list[ForecastEvaluationCandidate]:
        return [self.candidate]

    async def database_time(self) -> datetime:
        return NOW

    async def persist_forecast_evaluations(self, items: list[ForecastEvaluationPersistence]) -> int:
        self.persisted.extend(items)
        return len(items)


def _candidate(*, status: str = "final") -> ForecastEvaluationCandidate:
    model = ModelVersionRecord(
        id=MODEL_ID,
        model_name="nba_elo",
        model_version="test-v1",
        algorithm="elo",
        configuration={},
        configuration_fingerprint="1" * 64,
        formula="test",
        description="test",
        created_at=TIP - timedelta(days=1),
    )
    forecast = BaseForecastRecord(
        id=FORECAST_ID,
        sports_event_id=EVENT_ID,
        model_version_id=MODEL_ID,
        purpose="operational",
        home_team_id=HOME_ID,
        away_team_id=AWAY_ID,
        home_win_probability=Decimal("0.600000"),
        away_win_probability=Decimal("0.400000"),
        home_team_rating=Decimal("1510.0000"),
        away_team_rating=Decimal("1490.0000"),
        adjusted_rating_difference=Decimal("120.0000"),
        training_data_fingerprint="2" * 64,
        input_fingerprint="3" * 64,
        input_features={},
        training_games_seen=1,
        training_games_processed=1,
        skipped_tied_games=0,
        skipped_incomplete_games=0,
        home_prior_games=1,
        away_prior_games=1,
        latest_training_event_time=TIP - timedelta(days=2),
        forecast_as_of=TIP - timedelta(hours=1),
        source_event_last_seen_at=TIP - timedelta(days=1),
        generated_at=TIP - timedelta(hours=1),
    )
    forecast.model_version = model
    event = SportsEventRecord(
        id=EVENT_ID,
        provider_name="balldontlie",
        provider_event_id="test-event",
        league="nba",
        season=2026,
        event_date=TIP.date(),
        scheduled_start_time=TIP,
        status=status,
        status_detail=status,
        period=4,
        clock=None,
        postseason=False,
        postponed=False,
        tournament_stage=None,
        home_team_id=HOME_ID,
        away_team_id=AWAY_ID,
        home_score=110,
        away_score=100,
        venue=None,
        raw_data={},
        first_seen_at=TIP - timedelta(days=1),
        last_seen_at=TIP + timedelta(hours=3),
    )
    return ForecastEvaluationCandidate(forecast=forecast, event=event)


async def _run_scores_and_materializes_one_final_forecast() -> None:
    repository = FakeEvaluationRepository(_candidate())
    service = ForecastEvaluationService(
        repository=cast(EvaluationRepository, repository),
    )

    result = await service.run(
        purpose=ForecastPurpose.OPERATIONAL,
        start_date=TIP.date(),
        end_date=TIP.date(),
        event_id=EVENT_ID,
        model_version_id=MODEL_ID,
        limit=10,
        offset=0,
    )

    assert result.examined == 1
    assert result.eligible == 1
    assert result.persisted == 1
    assert result.replayed == 0
    assert repository.persisted[0].event_date == TIP.date()
    assert repository.persisted[0].evaluation.brier_score == Decimal("0.160000000000")


def test_run_scores_and_materializes_one_final_forecast() -> None:
    asyncio.run(_run_scores_and_materializes_one_final_forecast())


async def _latest_nonfinal_forecast_candidate_is_skipped_without_fallback() -> None:
    repository = FakeEvaluationRepository(_candidate(status="scheduled"))
    service = ForecastEvaluationService(repository=cast(EvaluationRepository, repository))

    result = await service.run(
        purpose=ForecastPurpose.OPERATIONAL,
        start_date=TIP.date(),
        end_date=TIP.date(),
        event_id=None,
        model_version_id=None,
        limit=10,
        offset=0,
    )

    assert result.eligible == 0
    assert result.skip_counts == {"not_final": 1}
    assert repository.persisted == []


def test_latest_nonfinal_forecast_candidate_is_skipped_without_fallback() -> None:
    asyncio.run(_latest_nonfinal_forecast_candidate_is_skipped_without_fallback())


async def _run_rejects_reversed_or_excessive_date_ranges() -> None:
    service = ForecastEvaluationService(
        repository=cast(EvaluationRepository, FakeEvaluationRepository(_candidate()))
    )
    with pytest.raises(ValueError, match="start_date"):
        await service.run(
            purpose=ForecastPurpose.OPERATIONAL,
            start_date=date(2026, 8, 2),
            end_date=date(2026, 8, 1),
            event_id=None,
            model_version_id=None,
            limit=10,
            offset=0,
        )
    with pytest.raises(ValueError, match="3660"):
        await service.run(
            purpose=ForecastPurpose.OPERATIONAL,
            start_date=date(2010, 1, 1),
            end_date=date(2026, 8, 1),
            event_id=None,
            model_version_id=None,
            limit=10,
            offset=0,
        )


def test_run_rejects_reversed_or_excessive_date_ranges() -> None:
    asyncio.run(_run_rejects_reversed_or_excessive_date_ranges())
