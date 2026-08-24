from __future__ import annotations

import asyncio
import csv
import io
from collections.abc import AsyncIterator
from datetime import date

import httpx
import pytest

from app.domain.mlb_statcast import MlbStatcastPlayerRole
from app.providers.sports.base import (
    SportsProviderResponseError,
    SportsProviderUnavailableError,
)
from app.providers.sports.savant import BaseballSavantStatcastProvider

CSV_COLUMNS = [
    "game_date",
    "release_speed",
    "player_name",
    "batter",
    "pitcher",
    "events",
    "description",
    "game_type",
    "type",
    "launch_speed",
    "launch_angle",
    "release_spin_rate",
    "game_pk",
    "estimated_woba_using_speedangle",
    "woba_value",
    "woba_denom",
    "launch_speed_angle",
    "at_bat_number",
    "pitch_number",
]


def csv_row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "game_date": "2026-08-10",
        "release_speed": "95.4",
        "player_name": "Pitcher, Test",
        "batter": "1001",
        "pitcher": "677960",
        "events": "single",
        "description": "hit_into_play",
        "game_type": "R",
        "type": "X",
        "launch_speed": "100.0",
        "launch_angle": "25",
        "release_spin_rate": "2400",
        "game_pk": "823000",
        "estimated_woba_using_speedangle": "0.700",
        "woba_value": "0.900",
        "woba_denom": "1",
        "launch_speed_angle": "6",
        "at_bat_number": "1",
        "pitch_number": "1",
    }
    row.update(updates)
    return row


def csv_payload(rows: list[dict[str, object]], *, columns: list[str] | None = None) -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=columns or CSV_COLUMNS,
        lineterminator="\n",
        extrasaction="ignore",
    )
    writer.writeheader()
    writer.writerows(rows)
    return ("\ufeff" + output.getvalue()).encode()


def provider_for(
    transport: httpx.AsyncBaseTransport,
    *,
    retries: int = 0,
    max_response_bytes: int = 1_000_000,
    max_rows: int = 100,
) -> BaseballSavantStatcastProvider:
    return BaseballSavantStatcastProvider(
        base_url="https://example.test",
        timeout_seconds=1,
        max_retries=retries,
        request_interval_seconds=0,
        max_response_bytes=max_response_bytes,
        max_rows=max_rows,
        retry_backoff_seconds=0,
        transport=transport,
    )


def test_multi_player_query_is_bounded_and_normalized() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=csv_payload([csv_row()]))

    batch = asyncio.run(
        provider_for(httpx.MockTransport(handler)).get_player_rows(
            role=MlbStatcastPlayerRole.PITCHER,
            player_ids=("677960", "656302"),
            window_start_date=date(2026, 8, 1),
            window_end_date=date(2026, 8, 21),
        )
    )

    assert len(batch.rows) == 1
    assert batch.rows[0].pitcher_id == "677960"
    assert batch.rows[0].release_speed_mph is not None
    assert str(batch.rows[0].release_speed_mph) == "95.4"
    assert batch.rows[0].launch_speed_angle == 6
    assert len(batch.response_sha256) == 64
    request = requests[0]
    assert request.url.path == "/statcast_search/csv"
    assert request.url.params["game_date_gt"] == "2026-08-01"
    assert request.url.params["game_date_lt"] == "2026-08-21"
    assert request.url.params["hfGT"] == "R|PO|"
    assert request.url.params.get_list("pitchers_lookup[]") == ["656302", "677960"]
    assert "Authorization" not in request.headers


def test_empty_official_result_preserves_requested_player_set() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=csv_payload([])))
    batch = asyncio.run(
        provider_for(transport).get_player_rows(
            role=MlbStatcastPlayerRole.BATTER,
            player_ids=("1001", "1002"),
            window_start_date=date(2026, 8, 1),
            window_end_date=date(2026, 8, 21),
        )
    )

    assert batch.rows == ()
    assert batch.requested_player_ids == ("1001", "1002")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (csv_payload([csv_row(pitcher="999")]), "unrequested player"),
        (csv_payload([csv_row(game_date="2026-08-22")]), "outside the requested"),
        (csv_payload([csv_row(game_type="S")]), "non-regular/postseason"),
        (csv_payload([csv_row()], columns=CSV_COLUMNS[:-1]), "missing required columns"),
    ],
)
def test_malformed_or_semantically_broad_source_fails_closed(
    payload: bytes,
    message: str,
) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=payload))

    with pytest.raises(SportsProviderResponseError, match=message):
        asyncio.run(
            provider_for(transport).get_player_rows(
                role=MlbStatcastPlayerRole.PITCHER,
                player_ids=("677960",),
                window_start_date=date(2026, 8, 1),
                window_end_date=date(2026, 8, 21),
            )
        )


def test_incomplete_official_woba_fields_are_preserved_as_missing() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            content=csv_payload([csv_row(woba_value="0", woba_denom="")]),
        )
    )

    batch = asyncio.run(
        provider_for(transport).get_player_rows(
            role=MlbStatcastPlayerRole.BATTER,
            player_ids=("1001",),
            window_start_date=date(2026, 8, 1),
            window_end_date=date(2026, 8, 21),
        )
    )

    assert batch.rows[0].woba_value == 0
    assert batch.rows[0].woba_denom is None


def test_response_byte_and_row_caps_fail_closed() -> None:
    payload = csv_payload([csv_row(), csv_row(pitch_number="2")])
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=payload))

    with pytest.raises(SportsProviderResponseError, match="byte limit"):
        asyncio.run(
            provider_for(transport, max_response_bytes=10).get_player_rows(
                role=MlbStatcastPlayerRole.PITCHER,
                player_ids=("677960",),
                window_start_date=date(2026, 8, 1),
                window_end_date=date(2026, 8, 21),
            )
        )
    with pytest.raises(SportsProviderResponseError, match="row limit"):
        asyncio.run(
            provider_for(transport, max_rows=1).get_player_rows(
                role=MlbStatcastPlayerRole.PITCHER,
                player_ids=("677960",),
                window_start_date=date(2026, 8, 1),
                window_end_date=date(2026, 8, 21),
            )
        )


def test_rate_limit_retries_and_network_failure_is_safe() -> None:
    attempts = 0

    def rate_limited(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, content=csv_payload([]))

    asyncio.run(
        provider_for(httpx.MockTransport(rate_limited), retries=1).get_player_rows(
            role=MlbStatcastPlayerRole.BATTER,
            player_ids=("1001",),
            window_start_date=date(2026, 8, 1),
            window_end_date=date(2026, 8, 21),
        )
    )
    assert attempts == 2

    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with pytest.raises(SportsProviderUnavailableError):
        asyncio.run(
            provider_for(httpx.MockTransport(offline), retries=1).get_player_rows(
                role=MlbStatcastPlayerRole.BATTER,
                player_ids=("1001",),
                window_start_date=date(2026, 8, 1),
                window_end_date=date(2026, 8, 21),
            )
        )


class TruncatedResponseStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"partial"
        raise httpx.RemoteProtocolError("response body ended early")


def test_truncated_response_body_retries_as_provider_unavailable() -> None:
    attempts = 0

    def truncated(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(200, stream=TruncatedResponseStream())

    with pytest.raises(SportsProviderUnavailableError, match="bounded retries"):
        asyncio.run(
            provider_for(httpx.MockTransport(truncated), retries=1).get_player_rows(
                role=MlbStatcastPlayerRole.BATTER,
                player_ids=("1001",),
                window_start_date=date(2026, 8, 1),
                window_end_date=date(2026, 8, 21),
            )
        )

    assert attempts == 2
