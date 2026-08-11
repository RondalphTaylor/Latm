from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingMode(StrEnum):
    """Execution modes permitted by the current safety boundary."""

    PAPER = "paper"


class PredictionMarketProviderName(StrEnum):
    """Prediction-market providers available in the current read-only build."""

    KALSHI = "kalshi"


class SportsDataProviderName(StrEnum):
    """Sports-data providers available in the current read-only build."""

    BALLDONTLIE = "balldontlie"


class Settings(BaseSettings):
    """Typed application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: SecretStr
    trading_mode: TradingMode = TradingMode.PAPER
    prediction_market_provider: PredictionMarketProviderName = PredictionMarketProviderName.KALSHI
    kalshi_api_base_url: str = "https://external-api.kalshi.com/trade-api/v2"
    provider_request_timeout_seconds: float = Field(default=10.0, gt=0.0, le=60.0)
    provider_max_retries: int = Field(default=2, ge=0, le=5)
    provider_max_pages: int = Field(default=50, ge=1, le=500)
    sports_data_provider: SportsDataProviderName = SportsDataProviderName.BALLDONTLIE
    balldontlie_api_key: SecretStr | None = None
    balldontlie_api_base_url: str = "https://api.balldontlie.io/v1"
    sports_provider_max_pages: int = Field(default=10, ge=1, le=100)
    sports_provider_request_interval_seconds: float = Field(default=12.1, ge=0.0, le=60.0)
    matching_min_confidence: Decimal = Field(
        default=Decimal("0.90"), ge=Decimal("0"), le=Decimal("1")
    )
    matching_ambiguity_margin: Decimal = Field(
        default=Decimal("0.10"), ge=Decimal("0"), le=Decimal("1")
    )
    matching_time_window_hours: int = Field(default=36, ge=1, le=168)
    opportunity_watch_min_raw_edge: Decimal = Field(
        default=Decimal("0.03"),
        ge=Decimal("0"),
        le=Decimal("1"),
        decimal_places=6,
    )
    opportunity_trade_candidate_min_raw_edge: Decimal = Field(
        default=Decimal("0.08"),
        ge=Decimal("0"),
        le=Decimal("1"),
        decimal_places=6,
    )
    opportunity_max_market_price_age_seconds: int = Field(
        default=900,
        ge=1,
        le=86400,
    )
    opportunity_max_operational_forecast_age_seconds: int = Field(
        default=86400,
        ge=1,
        le=604800,
    )

    @model_validator(mode="after")
    def validate_opportunity_thresholds(self) -> Settings:
        if self.opportunity_watch_min_raw_edge >= self.opportunity_trade_candidate_min_raw_edge:
            raise ValueError("opportunity watch threshold must be below trade-candidate threshold")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance for dependency injection."""
    return Settings()
