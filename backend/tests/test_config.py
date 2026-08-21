from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.config import (
    PredictionMarketProviderName,
    Settings,
    SportsDataProviderName,
    TradingMode,
)

TEST_DATABASE_URL = "postgresql+asyncpg://test:test@localhost:5432/test"


def test_trading_mode_defaults_to_paper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRADING_MODE", raising=False)

    settings = Settings(database_url=TEST_DATABASE_URL, _env_file=None)

    assert settings.trading_mode is TradingMode.PAPER
    assert settings.prediction_market_provider is PredictionMarketProviderName.KALSHI
    assert settings.sports_data_provider is SportsDataProviderName.BALLDONTLIE
    assert settings.balldontlie_api_key is None
    assert settings.mlb_api_base_url == "https://statsapi.mlb.com/api/v1"
    assert settings.mlb_provider_request_interval_seconds == 0.25
    assert settings.matching_min_confidence == Decimal("0.90")
    assert settings.matching_ambiguity_margin == Decimal("0.10")
    assert settings.matching_time_window_hours == 36
    assert settings.opportunity_watch_min_raw_edge == Decimal("0.03")
    assert settings.opportunity_trade_candidate_min_raw_edge == Decimal("0.08")
    assert settings.opportunity_max_market_price_age_seconds == 900
    assert settings.opportunity_max_operational_forecast_age_seconds == 86400
    assert settings.paper_starting_bankroll == Decimal("1000.00")
    assert settings.position_sizing_candidate_min_raw_edge == Decimal("0.08")
    assert settings.position_sizing_strong_min_raw_edge == Decimal("0.12")
    assert settings.position_sizing_very_strong_min_raw_edge == Decimal("0.18")
    assert settings.position_sizing_candidate_exposure_fraction == Decimal("0.02")
    assert settings.position_sizing_strong_exposure_fraction == Decimal("0.05")
    assert settings.position_sizing_very_strong_exposure_fraction == Decimal("0.08")
    assert settings.position_sizing_max_exposure_fraction == Decimal("0.08")
    assert settings.risk_auto_approve_exposure_max == Decimal("0.10")
    assert settings.risk_high_confidence_auto_approve_max == Decimal("0.40")
    assert settings.risk_min_raw_edge == Decimal("0.08")
    assert settings.risk_min_match_confidence == Decimal("0.90")
    assert settings.risk_max_market_price_age_seconds == 900
    assert settings.risk_max_operational_forecast_age_seconds == 86400
    assert settings.risk_authorization_ttl_seconds == 300
    assert settings.paper_slippage_bps == Decimal("25.00")
    assert settings.paper_fee_bps == Decimal("10.00")


def test_database_url_can_be_loaded_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = "postgresql+asyncpg://example:example@postgres:5432/example"
    monkeypatch.setenv("DATABASE_URL", database_url)

    settings = Settings(_env_file=None)

    assert settings.database_url.get_secret_value() == database_url


def test_live_trading_mode_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRADING_MODE", "live")

    with pytest.raises(ValidationError):
        Settings(database_url=TEST_DATABASE_URL, _env_file=None)


def test_unknown_prediction_market_provider_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PREDICTION_MARKET_PROVIDER", "unknown")

    with pytest.raises(ValidationError):
        Settings(database_url=TEST_DATABASE_URL, _env_file=None)


def test_unknown_sports_data_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPORTS_DATA_PROVIDER", "unknown")

    with pytest.raises(ValidationError):
        Settings(database_url=TEST_DATABASE_URL, _env_file=None)


def test_balldontlie_api_key_is_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BALLDONTLIE_API_KEY", "private-test-key")

    settings = Settings(database_url=TEST_DATABASE_URL, _env_file=None)

    assert settings.balldontlie_api_key is not None
    assert settings.balldontlie_api_key.get_secret_value() == "private-test-key"
    assert "private-test-key" not in repr(settings)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MATCHING_MIN_CONFIDENCE", "1.01"),
        ("MATCHING_AMBIGUITY_MARGIN", "-0.01"),
        ("MATCHING_TIME_WINDOW_HOURS", "0"),
    ],
)
def test_invalid_matching_policy_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings(database_url=TEST_DATABASE_URL, _env_file=None)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("OPPORTUNITY_WATCH_MIN_RAW_EDGE", "-0.01"),
        ("OPPORTUNITY_TRADE_CANDIDATE_MIN_RAW_EDGE", "1.01"),
        ("OPPORTUNITY_MAX_MARKET_PRICE_AGE_SECONDS", "0"),
        ("OPPORTUNITY_MAX_OPERATIONAL_FORECAST_AGE_SECONDS", "604801"),
    ],
)
def test_invalid_opportunity_policy_value_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings(database_url=TEST_DATABASE_URL, _env_file=None)


def test_opportunity_thresholds_must_be_strictly_ordered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPPORTUNITY_WATCH_MIN_RAW_EDGE", "0.08")
    monkeypatch.setenv("OPPORTUNITY_TRADE_CANDIDATE_MIN_RAW_EDGE", "0.08")

    with pytest.raises(ValidationError, match="watch threshold"):
        Settings(database_url=TEST_DATABASE_URL, _env_file=None)


def test_opportunity_thresholds_fit_persisted_six_decimal_precision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPPORTUNITY_WATCH_MIN_RAW_EDGE", "0.0300001")

    with pytest.raises(ValidationError):
        Settings(database_url=TEST_DATABASE_URL, _env_file=None)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PAPER_STARTING_BANKROLL", "0"),
        ("PAPER_STARTING_BANKROLL", "1000.001"),
        ("POSITION_SIZING_CANDIDATE_MIN_RAW_EDGE", "-0.01"),
        ("POSITION_SIZING_MAX_EXPOSURE_FRACTION", "0.10"),
        ("POSITION_SIZING_STRONG_EXPOSURE_FRACTION", "0.1234567"),
    ],
)
def test_invalid_portfolio_and_sizing_settings_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings(database_url=TEST_DATABASE_URL, _env_file=None)


def test_position_sizing_settings_must_be_strictly_ordered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POSITION_SIZING_STRONG_MIN_RAW_EDGE", "0.08")

    with pytest.raises(ValidationError, match="edge bands"):
        Settings(database_url=TEST_DATABASE_URL, _env_file=None)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("RISK_AUTO_APPROVE_EXPOSURE_MAX", "0"),
        ("RISK_HIGH_CONFIDENCE_AUTO_APPROVE_MAX", "1.01"),
        ("RISK_MIN_RAW_EDGE", "1.01"),
        ("RISK_MIN_MATCH_CONFIDENCE", "-0.01"),
        ("RISK_MAX_MARKET_PRICE_AGE_SECONDS", "0"),
        ("RISK_MAX_OPERATIONAL_FORECAST_AGE_SECONDS", "604801"),
        ("RISK_AUTHORIZATION_TTL_SECONDS", "0"),
    ],
)
def test_invalid_risk_settings_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings(database_url=TEST_DATABASE_URL, _env_file=None)


def test_risk_exposure_thresholds_must_be_strictly_ordered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RISK_AUTO_APPROVE_EXPOSURE_MAX", "0.40")
    monkeypatch.setenv("RISK_HIGH_CONFIDENCE_AUTO_APPROVE_MAX", "0.40")

    with pytest.raises(ValidationError, match="risk exposure thresholds"):
        Settings(database_url=TEST_DATABASE_URL, _env_file=None)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PAPER_SLIPPAGE_BPS", "-0.01"),
        ("PAPER_SLIPPAGE_BPS", "10000.01"),
        ("PAPER_FEE_BPS", "-0.01"),
        ("PAPER_FEE_BPS", "0.001"),
    ],
)
def test_invalid_paper_execution_settings_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings(database_url=TEST_DATABASE_URL, _env_file=None)


@pytest.mark.parametrize("value", ["1", "51"])
def test_invalid_evaluation_calibration_bin_count_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("EVALUATION_CALIBRATION_BIN_COUNT", value)

    with pytest.raises(ValidationError):
        Settings(database_url=TEST_DATABASE_URL, _env_file=None)
