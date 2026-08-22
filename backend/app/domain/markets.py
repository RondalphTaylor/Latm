from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from app.domain.sports import SportsLeague

ProbabilityPrice = Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"))]
NonNegativeDecimal = Annotated[Decimal, Field(ge=Decimal("0"))]


class OutcomeSide(StrEnum):
    """Normalized sides for a binary prediction market."""

    YES = "yes"
    NO = "no"


class MarketStatusFilter(StrEnum):
    """Statuses accepted by the Kalshi public event endpoint."""

    UNOPENED = "unopened"
    OPEN = "open"
    CLOSED = "closed"
    SETTLED = "settled"


class SportsMarketType(StrEnum):
    """Supported sports contract shapes with explicit provider metadata."""

    SINGLE_GAME_WINNER = "single_game_winner"


class SportsMarketClassification(BaseModel):
    """Versioned structured classification for a supported sports market."""

    model_config = ConfigDict(frozen=True)

    league: SportsLeague
    sports_market_type: SportsMarketType
    method: str = Field(min_length=1, max_length=50)
    version: str = Field(min_length=1, max_length=50)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


class MarketOutcome(BaseModel):
    """A provider-independent outcome offered by a prediction market."""

    model_config = ConfigDict(frozen=True)

    provider_outcome_id: str = Field(min_length=1, max_length=100)
    side: OutcomeSide
    label: str = Field(min_length=1)


class MarketPrice(BaseModel):
    """A point-in-time normalized market-price snapshot."""

    model_config = ConfigDict(frozen=True)

    yes_bid: ProbabilityPrice | None = None
    yes_ask: ProbabilityPrice | None = None
    no_bid: ProbabilityPrice | None = None
    no_ask: ProbabilityPrice | None = None
    last_price: ProbabilityPrice | None = None
    volume: NonNegativeDecimal | None = None
    volume_24h: NonNegativeDecimal | None = None
    open_interest: NonNegativeDecimal | None = None
    liquidity: NonNegativeDecimal | None = None
    retrieved_at: datetime


class BinaryMarketResolution(BaseModel):
    """Official provider settlement for one standard binary market."""

    model_config = ConfigDict(frozen=True)

    result: OutcomeSide
    yes_payout: ProbabilityPrice
    no_payout: ProbabilityPrice
    resolution_type: str = Field(default="standard_binary", pattern=r"^standard_binary$")
    source: str = Field(default="official_provider", pattern=r"^official_provider$")
    settled_at: datetime
    retrieved_at: datetime
    source_snapshot: dict[str, JsonValue]

    @field_validator("settled_at", "retrieved_at")
    @classmethod
    def times_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("market resolution times must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_standard_binary_payout(self) -> BinaryMarketResolution:
        if self.settled_at > self.retrieved_at:
            raise ValueError("market settlement cannot postdate its retrieval")
        if self.yes_payout + self.no_payout != Decimal("1"):
            raise ValueError("binary settlement payouts must sum to one")
        if self.result is OutcomeSide.YES and (
            self.yes_payout != Decimal("1") or self.no_payout != Decimal("0")
        ):
            raise ValueError("a YES result requires a one-dollar YES payout")
        if self.result is OutcomeSide.NO and (
            self.yes_payout != Decimal("0") or self.no_payout != Decimal("1")
        ):
            raise ValueError("a NO result requires a one-dollar NO payout")
        return self


class PredictionMarket(BaseModel):
    """Provider-independent prediction-market representation."""

    model_config = ConfigDict(frozen=True)

    provider_name: str = Field(min_length=1, max_length=50)
    provider_market_id: str = Field(min_length=1, max_length=200)
    provider_event_id: str | None = Field(default=None, max_length=200)
    series_ticker: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=100)
    market_type: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1)
    subtitle: str | None = None
    rules_primary: str | None = None
    rules_secondary: str | None = None
    status: str = Field(min_length=1, max_length=50)
    open_time: datetime | None = None
    close_time: datetime | None = None
    occurrence_time: datetime | None = None
    provider_created_at: datetime | None = None
    provider_updated_at: datetime | None = None
    outcomes: tuple[MarketOutcome, ...]
    price: MarketPrice | None = None
    resolution: BinaryMarketResolution | None = None
    raw_data: dict[str, JsonValue]
    retrieved_at: datetime
