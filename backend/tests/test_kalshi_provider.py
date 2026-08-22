from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from app.domain.markets import MarketStatusFilter
from app.providers.prediction_markets.base import (
    ProviderResponseError,
    ProviderUnavailableError,
)
from app.providers.prediction_markets.kalshi import (
    KalshiEventPayload,
    KalshiMarketPayload,
    KalshiPredictionMarketProvider,
    normalize_kalshi_market,
)


def market_payload(*, ticker: str = "KXNBAGAME-26AUG01BOSNYK-BOS") -> dict[str, object]:
    return {
        "ticker": ticker,
        "event_ticker": "KXNBAGAME-26AUG01BOSNYK",
        "market_type": "binary",
        "title": "Boston Celtics at New York Knicks winner?",
        "subtitle": "Boston at New York",
        "yes_sub_title": "Boston Celtics",
        "no_sub_title": "New York Knicks",
        "status": "open",
        "rules_primary": "Resolves Yes if Boston wins.",
        "created_time": "2026-08-01T12:00:00Z",
        "updated_time": "2026-08-01T12:01:00Z",
        "open_time": "2026-08-01T12:00:00Z",
        "close_time": "2026-08-02T00:00:00Z",
        "occurrence_datetime": "2026-08-02T00:30:00Z",
        "yes_bid_dollars": "0.5400",
        "yes_ask_dollars": "0.5600",
        "no_bid_dollars": "0.4400",
        "no_ask_dollars": "0.4600",
        "last_price_dollars": "0.5500",
        "volume_fp": "125.00",
        "volume_24h_fp": "40.00",
        "open_interest_fp": "80.00",
        "liquidity_dollars": "0.00",
    }


def event_payload(
    *,
    ticker: str = "KXNBAGAME-26AUG01BOSNYK",
    market_ticker: str = "KXNBAGAME-26AUG01BOSNYK-BOS",
) -> dict[str, object]:
    return {
        "event_ticker": ticker,
        "series_ticker": "KXNBAGAME",
        "title": "Boston at New York",
        "sub_title": "NBA game",
        "category": "Sports",
        "status": "open",
        "last_updated_ts": "2026-08-01T12:01:00Z",
        "product_metadata": {"league": "NBA"},
        "markets": [market_payload(ticker=market_ticker)],
    }


def provider_for(
    transport: httpx.AsyncBaseTransport, *, retries: int = 0
) -> KalshiPredictionMarketProvider:
    return KalshiPredictionMarketProvider(
        base_url="https://example.test/trade-api/v2",
        timeout_seconds=1.0,
        max_retries=retries,
        max_pages=5,
        retry_backoff_seconds=0,
        transport=transport,
    )


def test_normalizes_current_dollar_fields_and_preserves_raw_payload() -> None:
    event = KalshiEventPayload.model_validate(event_payload())
    market = event.markets[0]
    retrieved_at = datetime(2026, 8, 1, 13, tzinfo=UTC)

    normalized = normalize_kalshi_market(market, event=event, retrieved_at=retrieved_at)

    assert normalized.provider_name == "kalshi"
    assert normalized.provider_market_id == "KXNBAGAME-26AUG01BOSNYK-BOS"
    assert normalized.series_ticker == "KXNBAGAME"
    assert [outcome.side.value for outcome in normalized.outcomes] == ["yes", "no"]
    assert normalized.price is not None
    assert normalized.price.yes_bid == Decimal("0.5400")
    assert normalized.price.volume == Decimal("125.00")
    assert normalized.raw_data["market"]
    assert normalized.raw_data["event"]


def test_normalization_accepts_missing_optional_price_fields() -> None:
    payload = market_payload()
    for field in (
        "yes_bid_dollars",
        "yes_ask_dollars",
        "no_bid_dollars",
        "no_ask_dollars",
        "last_price_dollars",
        "volume_fp",
        "volume_24h_fp",
        "open_interest_fp",
        "liquidity_dollars",
    ):
        payload.pop(field)
    payload.pop("yes_sub_title")
    payload.pop("no_sub_title")
    market = KalshiMarketPayload.model_validate(payload)

    normalized = normalize_kalshi_market(
        market,
        event=None,
        retrieved_at=datetime(2026, 8, 1, tzinfo=UTC),
    )

    assert normalized.price is None
    assert [outcome.label for outcome in normalized.outcomes] == ["Yes", "No"]


@pytest.mark.parametrize("terminal_status", ["settled", "finalized"])
def test_normalizes_explicit_consistent_official_binary_resolution(
    terminal_status: str,
) -> None:
    payload = market_payload()
    payload.update(
        {
            "status": terminal_status,
            "result": "yes",
            "settlement_value_dollars": "1.000000",
            "settlement_ts": "2026-08-01T12:30:00Z",
        }
    )

    normalized = normalize_kalshi_market(
        KalshiMarketPayload.model_validate(payload),
        event=None,
        retrieved_at=datetime(2026, 8, 1, 13, tzinfo=UTC),
    )

    assert normalized.resolution is not None
    assert normalized.resolution.result.value == "yes"
    assert normalized.resolution.yes_payout == Decimal("1.000000")
    assert normalized.resolution.no_payout == Decimal("0.000000")
    assert normalized.resolution.source == "official_provider"


def test_normalizes_explicit_no_result_with_zero_yes_payout() -> None:
    payload = market_payload()
    payload.update(
        {
            "status": "finalized",
            "result": "no",
            "settlement_value_dollars": "0.000000",
            "settlement_ts": "2026-08-01T12:30:00Z",
        }
    )

    normalized = normalize_kalshi_market(
        KalshiMarketPayload.model_validate(payload),
        event=None,
        retrieved_at=datetime(2026, 8, 1, 13, tzinfo=UTC),
    )

    assert normalized.resolution is not None
    assert normalized.resolution.result.value == "no"
    assert normalized.resolution.yes_payout == Decimal("0.000000")
    assert normalized.resolution.no_payout == Decimal("1.000000")


@pytest.mark.parametrize(
    ("updates", "extra"),
    [
        ({"status": "open", "result": "yes", "settlement_value_dollars": "1"}, {}),
        ({"status": "finalized", "result": "scalar", "settlement_value_dollars": "0.5"}, {}),
        ({"status": "finalized", "result": "yes"}, {}),
        (
            {"status": "finalized", "result": "yes", "settlement_value_dollars": "0"},
            {},
        ),
        (
            {"status": "finalized"},
            {"home_score": 120, "away_score": 110, "winner": "yes"},
        ),
    ],
)
def test_unsupported_or_incomplete_terminal_data_has_no_normalized_resolution(
    updates: dict[str, object],
    extra: dict[str, object],
) -> None:
    payload = market_payload()
    payload.update(updates)
    payload.update(extra)
    payload.setdefault("settlement_ts", "2026-08-01T12:30:00Z")

    normalized = normalize_kalshi_market(
        KalshiMarketPayload.model_validate(payload),
        event=None,
        retrieved_at=datetime(2026, 8, 1, 13, tzinfo=UTC),
    )

    assert normalized.resolution is None


def test_nested_market_without_title_uses_event_title() -> None:
    payload = event_payload()
    markets = payload["markets"]
    assert isinstance(markets, list)
    market_payload_value = markets[0]
    assert isinstance(market_payload_value, dict)
    market_payload_value.pop("title")
    event = KalshiEventPayload.model_validate(payload)

    normalized = normalize_kalshi_market(
        event.markets[0],
        event=event,
        retrieved_at=datetime(2026, 8, 1, tzinfo=UTC),
    )

    assert normalized.title == "Boston at New York"


def test_list_markets_follows_cursor_pagination() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        cursor = request.url.params.get("cursor")
        if cursor is None:
            return httpx.Response(
                200,
                json={"events": [event_payload()], "cursor": "next-page"},
            )
        return httpx.Response(
            200,
            json={
                "events": [
                    event_payload(
                        ticker="KXNBAGAME-26AUG02LALGSW",
                        market_ticker="KXNBAGAME-26AUG02LALGSW-LAL",
                    )
                ],
                "cursor": "",
            },
        )

    markets = asyncio.run(
        provider_for(httpx.MockTransport(handler)).list_markets(status=MarketStatusFilter.OPEN)
    )

    assert len(markets) == 2
    assert requests[0].url.params["with_nested_markets"] == "true"
    assert requests[0].url.params["status"] == "open"
    assert requests[1].url.params["cursor"] == "next-page"


def test_list_markets_forwards_exact_series_filter() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"events": [], "cursor": ""})

    result = asyncio.run(
        provider_for(httpx.MockTransport(handler)).list_markets(
            status=MarketStatusFilter.OPEN,
            series_ticker="KXMLBGAME",
        )
    )

    assert result == []
    assert requests[0].url.params["series_ticker"] == "KXMLBGAME"


def test_get_market_normalizes_single_market_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/markets/KXNBAGAME-26AUG01BOSNYK-BOS"):
            return httpx.Response(200, json={"market": market_payload()})
        assert request.url.path.endswith("/events/KXNBAGAME-26AUG01BOSNYK")
        return httpx.Response(200, json={"event": event_payload()})

    market = asyncio.run(
        provider_for(httpx.MockTransport(handler)).get_market("KXNBAGAME-26AUG01BOSNYK-BOS")
    )

    assert market.provider_event_id == "KXNBAGAME-26AUG01BOSNYK"
    assert market.series_ticker == "KXNBAGAME"
    assert market.price is not None
    assert market.price.last_price == Decimal("0.5500")


def test_transient_provider_error_is_retried() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, json={"error": "temporarily unavailable"})
        return httpx.Response(200, json={"events": [], "cursor": ""})

    result = asyncio.run(provider_for(httpx.MockTransport(handler), retries=1).list_markets())

    assert result == []
    assert attempts == 2


def test_network_failure_raises_safe_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network unavailable", request=request)

    with pytest.raises(ProviderUnavailableError):
        asyncio.run(provider_for(httpx.MockTransport(handler), retries=1).list_markets())


def test_malformed_provider_response_fails_validation() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"events": [{"event_ticker": "MISSING-TITLE"}]})

    with pytest.raises(ProviderResponseError):
        asyncio.run(provider_for(httpx.MockTransport(handler)).list_markets())


def test_out_of_range_price_fails_normalization_safely() -> None:
    event = event_payload()
    markets = event["markets"]
    assert isinstance(markets, list)
    market = markets[0]
    assert isinstance(market, dict)
    market["yes_bid_dollars"] = "1.5000"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"events": [event], "cursor": ""})

    with pytest.raises(ProviderResponseError, match="failed normalization"):
        asyncio.run(provider_for(httpx.MockTransport(handler)).list_markets())
