from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.markets import PredictionMarketRecord


class MarketOutcomeResponse(BaseModel):
    """Normalized market outcome returned by the API."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    provider_outcome_id: str
    side: str
    label: str


class MarketPriceResponse(BaseModel):
    """Latest normalized market-price snapshot returned by the API."""

    model_config = ConfigDict(frozen=True)

    yes_bid: Decimal | None
    yes_ask: Decimal | None
    no_bid: Decimal | None
    no_ask: Decimal | None
    last_price: Decimal | None
    volume: Decimal | None
    volume_24h: Decimal | None
    open_interest: Decimal | None
    liquidity: Decimal | None
    retrieved_at: datetime


class MarketResponse(BaseModel):
    """Persisted provider-neutral prediction market returned by the API."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    provider_name: str
    provider_market_id: str
    provider_event_id: str | None
    series_ticker: str | None
    category: str | None
    market_type: str
    title: str
    subtitle: str | None
    rules_primary: str | None
    rules_secondary: str | None
    status: str
    is_nba: bool
    open_time: datetime | None
    close_time: datetime | None
    occurrence_time: datetime | None
    provider_created_at: datetime | None
    provider_updated_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    outcomes: tuple[MarketOutcomeResponse, ...]
    latest_price: MarketPriceResponse | None

    @classmethod
    def from_record(cls, record: PredictionMarketRecord) -> MarketResponse:
        """Build a stable response without exposing raw provider payloads."""
        latest_price_record = record.prices[0] if record.prices else None
        latest_price = None
        if latest_price_record is not None:
            latest_price = MarketPriceResponse(
                yes_bid=latest_price_record.yes_bid,
                yes_ask=latest_price_record.yes_ask,
                no_bid=latest_price_record.no_bid,
                no_ask=latest_price_record.no_ask,
                last_price=latest_price_record.last_price,
                volume=latest_price_record.volume,
                volume_24h=latest_price_record.volume_24h,
                open_interest=latest_price_record.open_interest,
                liquidity=latest_price_record.liquidity,
                retrieved_at=latest_price_record.retrieved_at,
            )
        return cls(
            id=record.id,
            provider_name=record.provider_name,
            provider_market_id=record.provider_market_id,
            provider_event_id=record.provider_event_id,
            series_ticker=record.series_ticker,
            category=record.category,
            market_type=record.market_type,
            title=record.title,
            subtitle=record.subtitle,
            rules_primary=record.rules_primary,
            rules_secondary=record.rules_secondary,
            status=record.status,
            is_nba=record.is_nba,
            open_time=record.open_time,
            close_time=record.close_time,
            occurrence_time=record.occurrence_time,
            provider_created_at=record.provider_created_at,
            provider_updated_at=record.provider_updated_at,
            first_seen_at=record.first_seen_at,
            last_seen_at=record.last_seen_at,
            outcomes=tuple(
                MarketOutcomeResponse(
                    id=outcome.id,
                    provider_outcome_id=outcome.provider_outcome_id,
                    side=outcome.side,
                    label=outcome.label,
                )
                for outcome in sorted(record.outcomes, key=lambda item: item.side, reverse=True)
            ),
            latest_price=latest_price,
        )


class MarketIngestionResponse(BaseModel):
    """Summary returned after a read-only provider ingestion run."""

    model_config = ConfigDict(frozen=True)

    provider: str
    fetched: int
    nba_markets: int
    persisted: int
