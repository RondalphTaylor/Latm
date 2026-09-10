from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.services.nfl_research.collection import collect_history


def _payload(request: httpx.Request) -> dict[str, object]:
    return {
        "provider": "balldontlie_nfl",
        "start_date": request.url.params["start_date"],
        "end_date": request.url.params["end_date"],
        "fetched": 1,
        "teams_persisted": 2,
        "events_persisted": 1,
        "scheduled": 0,
        "in_progress": 0,
        "final": 1,
        "postponed": 0,
        "canceled": 0,
        "unknown": 0,
    }


def test_chunking_and_completion_only_use_local_allowed_endpoints() -> None:
    requests: list[httpx.Request] = []
    records: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.host == "localhost" and request.url.port == 8000
        if request.url.path == "/health":
            assert request.method == "GET"
            return httpx.Response(200, json={"status": "ok", "trading_mode": "paper"})
        assert request.url.path == "/events/ingest" and request.method == "POST"
        assert request.url.params["provider"] == "balldontlie_nfl"
        return httpx.Response(200, json=_payload(request))

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = collect_history(
            client,
            start_date=date(2020, 1, 31),
            end_date=date(2020, 3, 2),
            max_windows=2,
            emit=records.append,
        )
    assert result["completed"] is True and result["next_start"] is None
    assert len(requests) == 4
    assert records[0]["end_date"] == "2020-03-01"
    assert records[1]["start_date"] == records[1]["end_date"] == "2020-03-02"
    assert records[-1] == result


def test_default_limit_returns_manual_resume_date() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=(
                {"status": "ok", "trading_mode": "paper"}
                if request.url.path == "/health"
                else _payload(request)
            ),
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = collect_history(client, start_date=date(2018, 8, 1), end_date=date(2026, 2, 28))
    assert result["windows_completed"] == 1
    assert result["completed"] is False
    assert result["next_start"] == "2018-09-01"


@pytest.mark.parametrize(
    "health",
    [
        {"status": "ok", "trading_mode": "live"},
        {"status": "error", "trading_mode": "paper"},
        {},
        [],
    ],
)
def test_paper_gate_prevents_ingestion(health: object) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(200, json=health)

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = collect_history(client, start_date=date(2018, 8, 1), end_date=date(2018, 8, 1))
    assert result["failure"] == "paper_health_gate_failed"
    assert result["next_start"] == "2018-08-01"


def test_failure_does_not_advance_failed_window_or_expose_body() -> None:
    posts = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "trading_mode": "paper"})
        posts += 1
        return (
            httpx.Response(200, json=_payload(request))
            if posts == 1
            else httpx.Response(502, text="SECRET provider body")
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = collect_history(
            client, start_date=date(2018, 8, 1), end_date=date(2018, 12, 31), max_windows=5
        )
    assert posts == 2 and result["windows_completed"] == 1
    assert result["next_start"] == "2018-09-01"
    assert result["http_status"] == 502 and result["failure"] == "ingestion_http_error"
    assert "SECRET" not in str(result)


@pytest.mark.parametrize(
    "changes",
    [
        {"fetched": True},
        {"final": -1},
        {"final": "1"},
        {"final": 0},
        {"events_persisted": 2},
        {"events_persisted": 0},
        {"provider": "mlb"},
        {"start_date": "2018-08-02"},
    ],
)
def test_malformed_counts_and_identity_do_not_advance(changes: dict[str, object]) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "trading_mode": "paper"})
        return httpx.Response(200, json={**_payload(request), **changes})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        result = collect_history(client, start_date=date(2018, 8, 1), end_date=date(2018, 8, 1))
    assert result["failure"] == "malformed_ingestion_response"
    assert result["windows_completed"] == 0 and result["next_start"] == "2018-08-01"


@pytest.mark.parametrize(
    ("start", "end", "limit"),
    [
        (date(2018, 7, 31), date(2018, 8, 1), 1),
        (date(2026, 2, 28), date(2026, 3, 1), 1),
        (date(2020, 2, 2), date(2020, 2, 1), 1),
        (date(2020, 2, 1), date(2020, 2, 1), 0),
        (date(2020, 2, 1), date(2020, 2, 1), 49),
    ],
)
def test_invalid_bounds_never_send_request(start: date, end: date, limit: int) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        pytest.fail("invalid arguments must not reach the network")

    with httpx.Client(transport=httpx.MockTransport(handle)) as client, pytest.raises(ValueError):
        collect_history(client, start_date=start, end_date=end, max_windows=limit)


@pytest.mark.parametrize("failure_kind", ["timeout", "invalid_json", "redirect"])
def test_uncertain_or_redirected_request_stops_without_retry(failure_kind: str) -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "trading_mode": "paper"})
        if failure_kind == "timeout":
            raise httpx.ReadTimeout("SECRET", request=request)
        if failure_kind == "redirect":
            return httpx.Response(302, headers={"Location": "https://example.org"})
        return httpx.Response(200, text="SECRET invalid JSON")

    with httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        result = collect_history(client, start_date=date(2026, 2, 28), end_date=date(2026, 2, 28))
    assert calls == 2
    assert result["next_start"] == "2026-02-28" and result["completed"] is False
    assert result["failure"] is not None and "SECRET" not in str(result)
