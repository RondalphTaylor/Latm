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
    assert settings.matching_min_confidence == Decimal("0.90")
    assert settings.matching_ambiguity_margin == Decimal("0.10")
    assert settings.matching_time_window_hours == 36


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
