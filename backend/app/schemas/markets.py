from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.markets import SportsMarketType
from app.domain.sports import SportsLeague
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


class MarketResolutionResponse(BaseModel):
    """Latest validated official binary settlement returned by the API."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    result: str
    yes_payout: Decimal
    no_payout: Decimal
    resolution_type: str
    source: str
    settled_at: datetime
    retrieved_at: datetime
    input_fingerprint: str


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
    sports_league: SportsLeague | None
    sports_market_type: SportsMarketType | None
    sports_classification_method: str | None
    sports_classification_version: str | None
    sports_classification_fingerprint: str | None
    open_time: datetime | None
    close_time: datetime | None
    occurrence_time: datetime | None
    provider_created_at: datetime | None
    provider_updated_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    outcomes: tuple[MarketOutcomeResponse, ...]
    latest_price: MarketPriceResponse | None
    latest_resolution: MarketResolutionResponse | None

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
        latest_resolution_record = record.resolutions[0] if record.resolutions else None
        latest_resolution = None
        if latest_resolution_record is not None:
            latest_resolution = MarketResolutionResponse(
                id=latest_resolution_record.id,
                result=latest_resolution_record.result,
                yes_payout=latest_resolution_record.yes_payout,
                no_payout=latest_resolution_record.no_payout,
                resolution_type=latest_resolution_record.resolution_type,
                source=latest_resolution_record.source,
                settled_at=latest_resolution_record.settled_at,
                retrieved_at=latest_resolution_record.retrieved_at,
                input_fingerprint=latest_resolution_record.input_fingerprint,
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
            sports_league=(
                SportsLeague(record.sports_league) if record.sports_league is not None else None
            ),
            sports_market_type=(
                SportsMarketType(record.sports_market_type)
                if record.sports_market_type is not None
                else None
            ),
            sports_classification_method=record.sports_classification_method,
            sports_classification_version=record.sports_classification_version,
            sports_classification_fingerprint=record.sports_classification_fingerprint,
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
            latest_resolution=latest_resolution,
        )


class MarketIngestionResponse(BaseModel):
    """Summary returned after a read-only provider ingestion run."""

    model_config = ConfigDict(frozen=True)

    provider: str
    fetched: int
    nba_markets: int
    mlb_markets: int
    selected_league: SportsLeague | None
    persisted: int
