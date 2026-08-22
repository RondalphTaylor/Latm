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
    MLB = "mlb"


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
    mlb_api_base_url: str = "https://statsapi.mlb.com/api/v1"
    baseball_savant_base_url: str = "https://baseballsavant.mlb.com"
    sports_provider_max_pages: int = Field(default=10, ge=1, le=100)
    sports_provider_request_interval_seconds: float = Field(default=12.1, ge=0.0, le=60.0)
    mlb_provider_request_interval_seconds: float = Field(default=0.25, ge=0.0, le=60.0)
    baseball_savant_request_timeout_seconds: float = Field(default=30.0, gt=0.0, le=120.0)
    baseball_savant_request_interval_seconds: float = Field(default=1.0, ge=0.0, le=60.0)
    baseball_savant_lookback_days: int = Field(default=30, ge=1, le=90)
    baseball_savant_max_response_bytes: int = Field(
        default=20_000_000,
        ge=100_000,
        le=100_000_000,
    )
    baseball_savant_max_rows: int = Field(default=50_000, ge=100, le=250_000)
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
    paper_starting_bankroll: Decimal = Field(
        default=Decimal("1000.00"),
        gt=Decimal("0"),
        max_digits=18,
        decimal_places=2,
    )
    position_sizing_candidate_min_raw_edge: Decimal = Field(
        default=Decimal("0.08"), ge=Decimal("0"), le=Decimal("1"), decimal_places=6
    )
    position_sizing_strong_min_raw_edge: Decimal = Field(
        default=Decimal("0.12"), ge=Decimal("0"), le=Decimal("1"), decimal_places=6
    )
    position_sizing_very_strong_min_raw_edge: Decimal = Field(
        default=Decimal("0.18"), ge=Decimal("0"), le=Decimal("1"), decimal_places=6
    )
    position_sizing_candidate_exposure_fraction: Decimal = Field(
        default=Decimal("0.02"), gt=Decimal("0"), lt=Decimal("0.10"), decimal_places=6
    )
    position_sizing_strong_exposure_fraction: Decimal = Field(
        default=Decimal("0.05"), gt=Decimal("0"), lt=Decimal("0.10"), decimal_places=6
    )
    position_sizing_very_strong_exposure_fraction: Decimal = Field(
        default=Decimal("0.08"), gt=Decimal("0"), lt=Decimal("0.10"), decimal_places=6
    )
    position_sizing_max_exposure_fraction: Decimal = Field(
        default=Decimal("0.08"), gt=Decimal("0"), lt=Decimal("0.10"), decimal_places=6
    )
    risk_auto_approve_exposure_max: Decimal = Field(
        default=Decimal("0.10"), gt=Decimal("0"), le=Decimal("1"), decimal_places=10
    )
    risk_high_confidence_auto_approve_max: Decimal = Field(
        default=Decimal("0.40"), gt=Decimal("0"), le=Decimal("1"), decimal_places=10
    )
    risk_min_raw_edge: Decimal = Field(
        default=Decimal("0.08"), ge=Decimal("0"), le=Decimal("1"), decimal_places=10
    )
    risk_min_match_confidence: Decimal = Field(
        default=Decimal("0.90"), ge=Decimal("0"), le=Decimal("1"), decimal_places=10
    )
    risk_max_market_price_age_seconds: int = Field(default=900, ge=1, le=86400)
    risk_max_operational_forecast_age_seconds: int = Field(default=86400, ge=1, le=604800)
    risk_authorization_ttl_seconds: int = Field(default=300, ge=1, le=3600)
    paper_slippage_bps: Decimal = Field(
        default=Decimal("25.00"), ge=Decimal("0"), le=Decimal("10000"), decimal_places=2
    )
    paper_fee_bps: Decimal = Field(
        default=Decimal("10.00"), ge=Decimal("0"), le=Decimal("10000"), decimal_places=2
    )
    position_monitor_min_hold_edge: Decimal = Field(
        default=Decimal("0.03"),
        ge=Decimal("0"),
        le=Decimal("1"),
        decimal_places=6,
    )
    position_monitor_reduce_fraction: Decimal = Field(
        default=Decimal("0.50"),
        gt=Decimal("0"),
        lt=Decimal("1"),
        decimal_places=6,
    )
    position_monitor_max_market_price_age_seconds: int = Field(
        default=900,
        ge=1,
        le=86400,
    )
    position_monitor_max_operational_forecast_age_seconds: int = Field(
        default=86400,
        ge=1,
        le=604800,
    )
    paper_exit_slippage_bps: Decimal = Field(
        default=Decimal("25.00"), ge=Decimal("0"), le=Decimal("10000"), decimal_places=2
    )
    paper_exit_fee_bps: Decimal = Field(
        default=Decimal("10.00"), ge=Decimal("0"), le=Decimal("10000"), decimal_places=2
    )
    evaluation_calibration_bin_count: int = Field(default=10, ge=2, le=50)

    @model_validator(mode="after")
    def validate_opportunity_thresholds(self) -> Settings:
        if self.opportunity_watch_min_raw_edge >= self.opportunity_trade_candidate_min_raw_edge:
            raise ValueError("opportunity watch threshold must be below trade-candidate threshold")
        return self

    @model_validator(mode="after")
    def validate_position_sizing_policy(self) -> Settings:
        if not (
            self.position_sizing_candidate_min_raw_edge
            < self.position_sizing_strong_min_raw_edge
            < self.position_sizing_very_strong_min_raw_edge
        ):
            raise ValueError("position-sizing edge bands must be strictly increasing")
        if not (
            self.position_sizing_candidate_exposure_fraction
            < self.position_sizing_strong_exposure_fraction
            < self.position_sizing_very_strong_exposure_fraction
            <= self.position_sizing_max_exposure_fraction
            < Decimal("0.10")
        ):
            raise ValueError("position-sizing exposure bands must increase and remain below 10%")
        return self

    @model_validator(mode="after")
    def validate_risk_policy(self) -> Settings:
        if not (
            self.risk_auto_approve_exposure_max
            < self.risk_high_confidence_auto_approve_max
            <= Decimal("1")
        ):
            raise ValueError("risk exposure thresholds must increase within 100%")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance for dependency injection."""
    return Settings()
