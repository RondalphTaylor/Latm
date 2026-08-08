from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue

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
    raw_data: dict[str, JsonValue]
    retrieved_at: datetime
