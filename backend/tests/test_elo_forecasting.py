from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain.forecasts import (
    EloConfiguration,
    ForecastPurpose,
    ForecastTargetInput,
    HistoricalGameInput,
)
from app.services.forecasting.elo import (
    EloForecastModel,
    configuration_fingerprint,
    effective_model_version,
)

HOME_ID = UUID("b5656876-2403-4bca-bf7c-6623fb2e85df")
AWAY_ID = UUID("393a6a49-2467-49ce-8e25-8fe86c6223b2")
THIRD_ID = UUID("91db8f7f-d159-443a-8c1f-8c77d164768b")
TARGET_ID = UUID("8c133c7e-995e-4908-b645-ee7df42d9958")
TIP_TIME = datetime(2026, 8, 1, 23, tzinfo=UTC)


def game(
    *,
    event_id: UUID,
    start: datetime,
    home_id: UUID = HOME_ID,
    away_id: UUID = AWAY_ID,
    home_score: int | None = 110,
    away_score: int | None = 100,
) -> HistoricalGameInput:
    return HistoricalGameInput(
        event_id=event_id,
        scheduled_start_time=start,
        home_team_id=home_id,
        away_team_id=away_id,
        home_score=home_score,
        away_score=away_score,
        source_last_seen_at=start + timedelta(hours=3),
    )


def target(
    *,
    start: datetime = TIP_TIME,
    cutoff: datetime | None = None,
    home_id: UUID = HOME_ID,
    away_id: UUID = AWAY_ID,
) -> ForecastTargetInput:
    return ForecastTargetInput(
        event_id=TARGET_ID,
        scheduled_start_time=start,
        home_team_id=home_id,
        away_team_id=away_id,
        event_status="final",
        purpose=ForecastPurpose.HISTORICAL_REPLAY,
        history_cutoff=cutoff or start,
        source_last_seen_at=start + timedelta(hours=3),
    )


def test_standard_elo_probability_formula_and_complements() -> None:
    neutral = EloForecastModel(EloConfiguration(home_court_advantage=Decimal("0")))
    home_court = EloForecastModel()

    assert neutral.home_win_probability(Decimal("1500"), Decimal("1500")) == Decimal("0.500000")
    assert neutral.home_win_probability(Decimal("1900"), Decimal("1500")) == Decimal("0.909091")
    assert home_court.home_win_probability(Decimal("1500"), Decimal("1500")) == Decimal("0.640065")

    forecast = home_court.forecast_many((target(),), ())
    assert forecast[0].home_win_probability + forecast[0].away_win_probability == Decimal("1")
    assert Decimal("0") <= forecast[0].home_win_probability <= Decimal("1")


def test_rating_update_is_zero_sum_and_upsets_move_more() -> None:
    model = EloForecastModel(EloConfiguration(home_court_advantage=Decimal("0")))
    favorite_home, favorite_away = model.update_ratings(
        Decimal("1700"), Decimal("1500"), home_won=True
    )
    upset_home, upset_away = model.update_ratings(Decimal("1700"), Decimal("1500"), home_won=False)

    assert favorite_home + favorite_away == Decimal("3200.0000")
    assert upset_home + upset_away == Decimal("3200.0000")
    assert favorite_home - Decimal("1700") < Decimal("1700") - upset_home


def test_replay_is_order_independent_and_excludes_target_and_future_results() -> None:
    earlier = game(
        event_id=UUID("77b217de-f4a7-40f6-a27c-b14ce82be284"),
        start=TIP_TIME - timedelta(days=2),
    )
    target_result = game(event_id=TARGET_ID, start=TIP_TIME, home_score=80, away_score=120)
    future = game(
        event_id=UUID("2d1c1d09-ea6f-4fee-9827-bcd393a1f836"),
        start=TIP_TIME + timedelta(days=1),
        home_score=70,
        away_score=130,
    )
    model = EloForecastModel(generated_at=TIP_TIME + timedelta(days=10))

    first = model.forecast_many((target(),), (future, target_result, earlier))[0]
    shuffled = model.forecast_many((target(),), (earlier, future, target_result))[0]

    assert first.input_fingerprint == shuffled.input_fingerprint
    assert first.training_games_processed == 1
    assert first.home_team_rating > Decimal("1500")
    assert first.latest_training_event_time == earlier.scheduled_start_time


def test_simultaneous_games_do_not_leak_and_bad_finals_are_audited() -> None:
    same_time = game(event_id=UUID("959cfda1-5c74-4697-b285-a4870473cc08"), start=TIP_TIME)
    tied = game(
        event_id=UUID("2a053c88-b2d5-4863-826c-e7a1305e76e3"),
        start=TIP_TIME - timedelta(days=2),
        home_score=100,
        away_score=100,
    )
    incomplete = game(
        event_id=UUID("86250b8d-f1fb-43f2-a238-28e3a9207247"),
        start=TIP_TIME - timedelta(days=1),
        home_id=THIRD_ID,
        home_score=None,
        away_score=None,
    )

    forecast = EloForecastModel().forecast_many((target(),), (same_time, incomplete, tied))[0]

    assert forecast.training_games_seen == 2
    assert forecast.training_games_processed == 0
    assert forecast.skipped_tied_games == 1
    assert forecast.skipped_incomplete_games == 1
    assert forecast.home_prior_games == 0


def test_semantic_fingerprints_ignore_generation_time_but_change_with_history() -> None:
    prior = game(
        event_id=UUID("36772f03-6535-498b-8b5e-099bc4196dcb"),
        start=TIP_TIME - timedelta(days=1),
    )
    corrected = prior.model_copy(update={"home_score": 90, "away_score": 100})
    first = EloForecastModel(generated_at=TIP_TIME).forecast_many((target(),), (prior,))[0]
    rerun = EloForecastModel(generated_at=TIP_TIME + timedelta(days=1)).forecast_many(
        (target(),), (prior,)
    )[0]
    changed = EloForecastModel(generated_at=TIP_TIME).forecast_many((target(),), (corrected,))[0]

    assert first.input_fingerprint == rerun.input_fingerprint
    assert first.training_data_fingerprint == rerun.training_data_fingerprint
    assert first.generated_at != rerun.generated_at
    assert changed.input_fingerprint != first.input_fingerprint
    assert changed.home_win_probability != first.home_win_probability


def test_effective_version_fingerprints_every_configuration_value() -> None:
    baseline = EloConfiguration()
    changed = baseline.model_copy(update={"k_factor": Decimal("21")})

    assert len(configuration_fingerprint(baseline)) == 64
    assert configuration_fingerprint(changed) != configuration_fingerprint(baseline)
    assert effective_model_version(changed) != effective_model_version(baseline)


def test_forecast_inputs_reject_naive_times_and_invalid_teams() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        target(start=TIP_TIME.replace(tzinfo=None))
    with pytest.raises(ValidationError, match="distinct"):
        target(home_id=HOME_ID, away_id=HOME_ID)
