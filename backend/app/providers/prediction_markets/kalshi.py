from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, field_validator

from app.domain.markets import (
    MarketOutcome,
    MarketPrice,
    MarketStatusFilter,
    OutcomeSide,
    PredictionMarket,
)
from app.providers.prediction_markets.base import (
    ProviderResponseError,
    ProviderUnavailableError,
)


class KalshiMarketPayload(BaseModel):
    """Validated subset of a Kalshi market response."""

    model_config = ConfigDict(extra="allow")

    ticker: str = Field(min_length=1)
    event_ticker: str | None = None
    market_type: str = "binary"
    title: str | None = None
    subtitle: str | None = None
    yes_sub_title: str | None = None
    no_sub_title: str | None = None
    status: str | None = None
    rules_primary: str | None = None
    rules_secondary: str | None = None
    created_time: datetime | None = None
    updated_time: datetime | None = None
    open_time: datetime | None = None
    close_time: datetime | None = None
    occurrence_datetime: datetime | None = None
    yes_bid_dollars: Decimal | None = None
    yes_ask_dollars: Decimal | None = None
    no_bid_dollars: Decimal | None = None
    no_ask_dollars: Decimal | None = None
    last_price_dollars: Decimal | None = None
    volume_fp: Decimal | None = None
    volume_24h_fp: Decimal | None = None
    open_interest_fp: Decimal | None = None
    liquidity_dollars: Decimal | None = None

    @field_validator(
        "yes_bid_dollars",
        "yes_ask_dollars",
        "no_bid_dollars",
        "no_ask_dollars",
        "last_price_dollars",
        "volume_fp",
        "volume_24h_fp",
        "open_interest_fp",
        "liquidity_dollars",
        mode="before",
    )
    @classmethod
    def empty_decimal_is_missing(cls, value: object) -> object:
        """Treat provider empty strings as absent optional numeric fields."""
        return None if value == "" else value


class KalshiEventPayload(BaseModel):
    """Validated subset of a Kalshi event with nested markets."""

    model_config = ConfigDict(extra="allow")

    event_ticker: str = Field(min_length=1)
    series_ticker: str | None = None
    title: str = Field(min_length=1)
    sub_title: str | None = None
    category: str | None = None
    status: str | None = None
    markets: list[KalshiMarketPayload] = Field(default_factory=list)
    product_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    last_updated_ts: datetime | None = None


class KalshiEventsResponse(BaseModel):
    """Cursor-paginated Kalshi events response."""

    model_config = ConfigDict(extra="ignore")

    events: list[KalshiEventPayload]
    cursor: str = ""


class KalshiMarketResponse(BaseModel):
    """Kalshi single-market response wrapper."""

    model_config = ConfigDict(extra="ignore")

    market: KalshiMarketPayload


def _json_dict(model: BaseModel) -> dict[str, JsonValue]:
    value = model.model_dump(mode="json")
    return {str(key): item for key, item in value.items()}


def normalize_kalshi_market(
    market: KalshiMarketPayload,
    *,
    event: KalshiEventPayload | None,
    retrieved_at: datetime,
) -> PredictionMarket:
    """Convert one Kalshi market payload into the provider-neutral domain model."""
    price_values = (
        market.yes_bid_dollars,
        market.yes_ask_dollars,
        market.no_bid_dollars,
        market.no_ask_dollars,
        market.last_price_dollars,
        market.volume_fp,
        market.volume_24h_fp,
        market.open_interest_fp,
        market.liquidity_dollars,
    )
    price = None
    if any(value is not None for value in price_values):
        price = MarketPrice(
            yes_bid=market.yes_bid_dollars,
            yes_ask=market.yes_ask_dollars,
            no_bid=market.no_bid_dollars,
            no_ask=market.no_ask_dollars,
            last_price=market.last_price_dollars,
            volume=market.volume_fp,
            volume_24h=market.volume_24h_fp,
            open_interest=market.open_interest_fp,
            liquidity=market.liquidity_dollars,
            retrieved_at=retrieved_at,
        )

    raw_data: dict[str, JsonValue] = {"market": _json_dict(market)}
    if event is not None:
        raw_data["event"] = _json_dict(event.model_copy(update={"markets": []}))

    normalized_title = (
        market.title
        or (event.title if event else None)
        or market.subtitle
        or market.yes_sub_title
        or market.ticker
    )

    return PredictionMarket(
        provider_name=KalshiPredictionMarketProvider.name,
        provider_market_id=market.ticker,
        provider_event_id=market.event_ticker or (event.event_ticker if event else None),
        series_ticker=event.series_ticker if event else None,
        category=event.category if event else None,
        market_type=market.market_type,
        title=normalized_title,
        subtitle=market.subtitle or (event.sub_title if event else None),
        rules_primary=market.rules_primary,
        rules_secondary=market.rules_secondary,
        status=market.status or (event.status if event and event.status else "unknown"),
        open_time=market.open_time,
        close_time=market.close_time,
        occurrence_time=market.occurrence_datetime,
        provider_created_at=market.created_time,
        provider_updated_at=market.updated_time or (event.last_updated_ts if event else None),
        outcomes=(
            MarketOutcome(
                provider_outcome_id=OutcomeSide.YES.value,
                side=OutcomeSide.YES,
                label=market.yes_sub_title or "Yes",
            ),
            MarketOutcome(
                provider_outcome_id=OutcomeSide.NO.value,
                side=OutcomeSide.NO,
                label=market.no_sub_title or "No",
            ),
        ),
        price=price,
        raw_data=raw_data,
        retrieved_at=retrieved_at,
    )


class KalshiPredictionMarketProvider:
    """Read-only adapter for Kalshi public production market data."""

    name = "kalshi"

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        max_retries: int,
        max_pages: int,
        retry_backoff_seconds: float = 0.25,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds)
        self._max_retries = max_retries
        self._max_pages = max_pages
        self._retry_backoff_seconds = retry_backoff_seconds
        self._transport = transport

    async def _get_json(
        self,
        client: httpx.AsyncClient,
        path: str,
        *,
        params: dict[str, str | int | bool] | None = None,
    ) -> dict[str, Any]:
        for attempt in range(self._max_retries + 1):
            try:
                response = await client.get(path, params=params)
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                if response.is_error:
                    raise ProviderResponseError(
                        f"Kalshi returned HTTP {response.status_code} for {path}"
                    )
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ProviderResponseError("Kalshi returned a non-object JSON response")
                return payload
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                if attempt >= self._max_retries:
                    raise ProviderUnavailableError(
                        f"Kalshi remained unavailable after {attempt + 1} attempt(s)"
                    ) from exc
                await asyncio.sleep(self._retry_backoff_seconds * (2**attempt))
            except ValueError as exc:
                raise ProviderResponseError("Kalshi returned invalid JSON") from exc
        raise AssertionError("provider retry loop exited unexpectedly")

    async def list_markets(
        self,
        *,
        status: MarketStatusFilter | None = None,
    ) -> list[PredictionMarket]:
        """Retrieve all pages of Kalshi events and normalize their nested markets."""
        markets: dict[str, PredictionMarket] = {}
        cursor = ""
        seen_cursors: set[str] = set()
        retrieved_at = datetime.now(UTC)

        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            transport=self._transport,
        ) as client:
            for _ in range(self._max_pages):
                params: dict[str, str | int | bool] = {
                    "limit": 200,
                    "with_nested_markets": True,
                }
                if cursor:
                    params["cursor"] = cursor
                if status is not None:
                    params["status"] = status.value

                raw_payload = await self._get_json(client, "/events", params=params)
                try:
                    payload = KalshiEventsResponse.model_validate(raw_payload)
                except ValidationError as exc:
                    raise ProviderResponseError("Kalshi events response failed validation") from exc

                for event in payload.events:
                    for market in event.markets:
                        try:
                            normalized = normalize_kalshi_market(
                                market,
                                event=event,
                                retrieved_at=retrieved_at,
                            )
                        except ValidationError as exc:
                            raise ProviderResponseError(
                                f"Kalshi market {market.ticker} failed normalization"
                            ) from exc
                        markets[normalized.provider_market_id] = normalized

                if not payload.cursor:
                    return list(markets.values())
                if payload.cursor in seen_cursors:
                    raise ProviderResponseError("Kalshi returned a repeated pagination cursor")
                seen_cursors.add(payload.cursor)
                cursor = payload.cursor

        raise ProviderResponseError(
            f"Kalshi pagination exceeded the configured {self._max_pages}-page limit"
        )

    async def get_market(self, provider_market_id: str) -> PredictionMarket:
        """Retrieve and normalize one Kalshi market by provider ticker."""
        retrieved_at = datetime.now(UTC)
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            transport=self._transport,
        ) as client:
            raw_payload = await self._get_json(client, f"/markets/{provider_market_id}")
        try:
            payload = KalshiMarketResponse.model_validate(raw_payload)
        except ValidationError as exc:
            raise ProviderResponseError("Kalshi market response failed validation") from exc
        try:
            return normalize_kalshi_market(payload.market, event=None, retrieved_at=retrieved_at)
        except ValidationError as exc:
            raise ProviderResponseError(
                f"Kalshi market {provider_market_id} failed normalization"
            ) from exc
