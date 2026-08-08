from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest

from app.domain.forecasts import BaseForecast, EloConfiguration, ForecastPurpose
from app.models.sports import SportsEventRecord
from app.services.forecasting.service import BaseForecastService

HOME_ID = UUID("0a136788-a98f-4589-810b-400c636aba8c")
AWAY_ID = UUID("0f72285d-eb95-49a5-a876-c4c1a08caa74")
TARGET_ID = UUID("6e523a45-70ce-4555-9364-9b2b2708f511")
HISTORY_ID = UUID("f35a9425-7541-447d-9d7b-a49cb71ad12b")
RUN_AT = datetime(2026, 8, 1, 12, tzinfo=UTC)
TIP_TIME = datetime(2026, 8, 2, 23, tzinfo=UTC)


def event_record(
    *,
    event_id: UUID,
    start: datetime,
    status: str,
    home_score: int | None,
    away_score: int | None,
) -> SportsEventRecord:
    return SportsEventRecord(
        id=event_id,
        provider_name="balldontlie",
        provider_event_id=str(event_id),
        league="nba",
        season=2025,
        event_date=start.date(),
        scheduled_start_time=start,
        status=status,
        status_detail=status,
        period=4 if status == "final" else 0,
        clock=None,
        postseason=False,
        postponed=False,
        tournament_stage=None,
        home_team_id=HOME_ID,
        away_team_id=AWAY_ID,
        home_score=home_score,
        away_score=away_score,
        venue=None,
        raw_data={},
        first_seen_at=start,
        last_seen_at=start + timedelta(hours=3),
    )


class FakeForecastRepository:
    def __init__(self, *, include_target: bool = True, persisted: int = 1) -> None:
        self.targets = (
            [
                event_record(
                    event_id=TARGET_ID,
                    start=TIP_TIME,
                    status="scheduled",
                    home_score=None,
                    away_score=None,
                )
            ]
            if include_target
            else []
        )
        self.history = [
            event_record(
                event_id=HISTORY_ID,
                start=TIP_TIME - timedelta(days=2),
                status="final",
                home_score=110,
                away_score=100,
            )
        ]
        self.persisted = persisted
        self.calls: dict[str, object] = {}
        self.forecasts: tuple[BaseForecast, ...] = ()

    async def list_forecast_targets(self, **kwargs: object) -> list[SportsEventRecord]:
        self.calls["targets"] = kwargs
        return self.targets

    async def list_final_history(self, **kwargs: object) -> list[SportsEventRecord]:
        self.calls["history"] = kwargs
        return self.history

    async def persist_forecasts(
        self,
        forecasts: tuple[BaseForecast, ...],
        **kwargs: object,
    ) -> int:
        self.calls["persist"] = kwargs
        self.forecasts = forecasts
        return self.persisted


def service(repository: FakeForecastRepository) -> BaseForecastService:
    return BaseForecastService(
        repository=repository,  # type: ignore[arg-type]
        sports_provider_name="balldontlie",
        clock=lambda: RUN_AT,
    )


def test_operational_run_uses_generation_time_cutoff_and_persists_forecast() -> None:
    repository = FakeForecastRepository()

    result = asyncio.run(
        service(repository).run(
            purpose=ForecastPurpose.OPERATIONAL,
            start_date=TIP_TIME.date(),
            end_date=TIP_TIME.date(),
            event_id=TARGET_ID,
            limit=10,
            offset=0,
        )
    )

    assert result.examined == 1
    assert result.generated == 1
    assert result.persisted == 1
    assert result.training_games_processed == 1
    assert repository.calls["targets"] == {
        "provider_name": "balldontlie",
        "purpose": ForecastPurpose.OPERATIONAL,
        "start_date": TIP_TIME.date(),
        "end_date": TIP_TIME.date(),
        "run_at": RUN_AT,
        "event_id": TARGET_ID,
        "limit": 10,
        "offset": 0,
    }
    assert repository.calls["history"] == {
        "provider_name": "balldontlie",
        "before": RUN_AT,
    }
    assert repository.forecasts[0].forecast_as_of == RUN_AT
    assert repository.forecasts[0].purpose is ForecastPurpose.OPERATIONAL
    assert isinstance(repository.calls["persist"], dict)
    assert repository.calls["persist"]["configuration"] == EloConfiguration()


def test_historical_replay_uses_target_tip_as_strict_cutoff() -> None:
    repository = FakeForecastRepository()
    repository.targets[0].status = "final"
    repository.targets[0].home_score = 90
    repository.targets[0].away_score = 100

    result = asyncio.run(
        service(repository).run(
            purpose=ForecastPurpose.HISTORICAL_REPLAY,
            start_date=TIP_TIME.date(),
            end_date=TIP_TIME.date(),
            event_id=None,
            limit=250,
            offset=0,
        )
    )

    assert result.purpose is ForecastPurpose.HISTORICAL_REPLAY
    assert repository.calls["history"] == {
        "provider_name": "balldontlie",
        "before": TIP_TIME,
    }
    assert repository.forecasts[0].forecast_as_of == TIP_TIME
    assert repository.forecasts[0].sports_event_id == TARGET_ID


def test_empty_target_batch_is_safe_and_does_not_load_history_or_write() -> None:
    repository = FakeForecastRepository(include_target=False)

    result = asyncio.run(
        service(repository).run(
            purpose=ForecastPurpose.OPERATIONAL,
            start_date=TIP_TIME.date(),
            end_date=TIP_TIME.date(),
            event_id=None,
            limit=250,
            offset=0,
        )
    )

    assert result.examined == 0
    assert result.generated == 0
    assert result.persisted == 0
    assert "history" not in repository.calls
    assert "persist" not in repository.calls


@pytest.mark.parametrize(
    ("start_date", "end_date", "message"),
    [
        (date(2026, 8, 2), date(2026, 8, 1), "must not be after"),
        (date(2026, 8, 1), date(2026, 9, 1), "cannot exceed 31"),
    ],
)
def test_invalid_ranges_fail_before_repository_calls(
    start_date: date,
    end_date: date,
    message: str,
) -> None:
    repository = FakeForecastRepository()

    with pytest.raises(ValueError, match=message):
        asyncio.run(
            service(repository).run(
                purpose=ForecastPurpose.OPERATIONAL,
                start_date=start_date,
                end_date=end_date,
                event_id=None,
                limit=250,
                offset=0,
            )
        )

    assert repository.calls == {}
