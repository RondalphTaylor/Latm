from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import httpx
import pytest
from pydantic import SecretStr

from app.domain.sports import SportsEventStatus, SportsLeague
from app.providers.sports.base import (
    SportsProviderAuthenticationError,
    SportsProviderResponseError,
    SportsProviderUnavailableError,
)
from app.providers.sports.nfl import (
    BallDontLieNflSportsDataProvider,
    NflGamePayload,
    normalize_nfl_game,
)


def team_payload(team_id: int = 1) -> dict[str, object]:
    return {
        "id": team_id,
        "location": "New England" if team_id == 1 else "Seattle",
        "name": "Patriots" if team_id == 1 else "Seahawks",
        "full_name": "New England Patriots" if team_id == 1 else "Seattle Seahawks",
        "abbreviation": "NE" if team_id == 1 else "SEA",
        "conference": "AFC",
        "division": "EAST",
    }


def game_payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": 7001,
        "date": "2026-09-10T00:20:00Z",
        "season": 2026,
        "week": 1,
        "postseason": False,
        "status": "Final/OT",
        "status_state": "final",
        "home_team_score": 20,
        "visitor_team_score": 20,
        "home_team": team_payload(),
        "visitor_team": team_payload(2),
        "venue": "Example stadium",
    }
    payload.update(changes)
    return payload


def provider_for(
    transport: httpx.AsyncBaseTransport, *, max_pages: int = 5, retries: int = 0
) -> BallDontLieNflSportsDataProvider:
    return BallDontLieNflSportsDataProvider(
        api_key=SecretStr("test-nfl-key"),
        base_url="https://example.test/nfl/v1",
        timeout_seconds=1,
        max_retries=retries,
        max_pages=max_pages,
        request_interval_seconds=0,
        retry_backoff_seconds=0,
        transport=transport,
    )


def test_nfl_tie_and_raw_week_are_preserved() -> None:
    event = normalize_nfl_game(
        NflGamePayload.model_validate(game_payload()), retrieved_at=datetime.now(UTC)
    )
    assert event.league is SportsLeague.NFL
    assert event.provider_name == event.home_team.provider_name == "balldontlie_nfl"
    assert event.home_team.city == "New England"
    assert event.home_team.league is SportsLeague.NFL
    assert event.home_score == event.away_score == 20
    assert event.event_date == date(2026, 9, 9)
    assert event.period == 0
    assert event.raw_data["week"] == 1
    assert event.venue == "Example stadium"


@pytest.mark.parametrize(
    ("state", "expected"),
    [(state.value, state) for state in SportsEventStatus]
    + [
        (state, SportsEventStatus.UNKNOWN) for state in ("delayed", "suspended", "abandoned", "new")
    ],
)
def test_explicit_status_wins_over_display_text(state: str, expected: SportsEventStatus) -> None:
    event = normalize_nfl_game(
        NflGamePayload.model_validate(game_payload(status="Final", status_state=state)),
        retrieved_at=datetime.now(UTC),
    )
    assert event.status is expected
    assert event.postponed is (expected is SportsEventStatus.POSTPONED)
    if expected not in {SportsEventStatus.FINAL, SportsEventStatus.IN_PROGRESS}:
        assert event.home_score is None
        assert event.away_score is None


def test_games_auth_pagination_dedup_and_eastern_boundaries() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.params.get("cursor") is None:
            return httpx.Response(
                200,
                json={
                    "data": [
                        game_payload(),
                        game_payload(id=2, date="2026-09-09T03:59:59Z"),
                        game_payload(id=3, date="2026-09-09T04:00:00Z"),
                    ],
                    "meta": {"next_cursor": 25},
                },
            )
        return httpx.Response(
            200,
            json={
                "data": [
                    game_payload(),
                    game_payload(id=4, date="2026-09-10T03:59:59Z"),
                    game_payload(id=5, date="2026-09-10T04:00:00Z"),
                ]
            },
        )

    events = asyncio.run(
        provider_for(httpx.MockTransport(handler)).get_games(
            start_date=date(2026, 9, 9), end_date=date(2026, 9, 9)
        )
    )
    assert {event.provider_event_id for event in events} == {"7001", "3", "4"}
    assert requests[0].url.path == "/nfl/v1/games"
    assert requests[0].headers["Authorization"] == "test-nfl-key"
    assert requests[0].url.params.get_list("dates[]") == ["2026-09-08", "2026-09-09", "2026-09-10"]
    assert requests[1].url.params["cursor"] == "25"


@pytest.mark.parametrize("as_list", [True, False])
def test_all_public_resources_use_nfl_payloads(as_list: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/teams"):
            return httpx.Response(200, json={"data": [team_payload()]})
        if request.url.path.endswith("/teams/1"):
            return httpx.Response(
                200, json={"data": [team_payload()] if as_list else team_payload()}
            )
        return httpx.Response(200, json={"data": game_payload()})

    provider = provider_for(httpx.MockTransport(handler))
    assert asyncio.run(provider.get_teams())[0].league is SportsLeague.NFL
    assert asyncio.run(provider.get_team("1")).provider_team_id == "1"
    assert asyncio.run(provider.get_game("7001")).status is SportsEventStatus.FINAL


@pytest.mark.parametrize(
    "changes",
    [
        {"date": "2026-09-10T00:20:00"},
        {"home_team_score": None},
        {"home_team_score": None, "visitor_team_score": None},
        {"home_team_score": -1},
        {"status_state": None},
        {"home_team": team_payload(2)},
    ],
)
def test_bad_games_fail_without_fabrication(changes: dict[str, object]) -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"data": game_payload(**changes)})
    )
    with pytest.raises(SportsProviderResponseError, match="validation"):
        asyncio.run(provider_for(transport).get_game("7001"))


@pytest.mark.parametrize("status", [401, 403])
def test_auth_errors_are_secret_safe(status: int) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(status))
    with pytest.raises(SportsProviderAuthenticationError) as exc:
        asyncio.run(provider_for(transport).get_teams())
    assert "test-nfl-key" not in str(exc.value)


def test_unavailable_and_retry() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503)

    with pytest.raises(SportsProviderUnavailableError):
        asyncio.run(provider_for(httpx.MockTransport(handler), retries=1).get_teams())
    assert attempts == 2


@pytest.mark.parametrize("max_pages, message", [(1, "page limit"), (3, "repeated pagination")])
def test_pagination_fails_closed(max_pages: int, message: str) -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"data": [game_payload()], "meta": {"next_cursor": 25}})
    )
    with pytest.raises(SportsProviderResponseError, match=message):
        asyncio.run(
            provider_for(transport, max_pages=max_pages).get_games(
                start_date=date(2026, 9, 9), end_date=date(2026, 9, 10)
            )
        )


def test_reversed_range_never_calls_provider() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("must not call provider")

    with pytest.raises(ValueError):
        asyncio.run(
            provider_for(httpx.MockTransport(handler)).get_games(
                start_date=date(2026, 9, 10), end_date=date(2026, 9, 9)
            )
        )


def test_winter_date_boundary_and_explicit_period() -> None:
    event = normalize_nfl_game(
        NflGamePayload.model_validate(
            game_payload(date="2026-01-05T04:30:00Z", season=2025, week=18, period=5)
        ),
        retrieved_at=datetime.now(UTC),
    )
    assert event.event_date == date(2026, 1, 4)
    assert event.season == 2025
    assert event.period == 5


def test_long_date_windows_are_chunked_and_globally_capped() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": []})

    with pytest.raises(SportsProviderResponseError, match="page limit"):
        asyncio.run(
            provider_for(httpx.MockTransport(handler), max_pages=1).get_games(
                start_date=date(2026, 1, 1), end_date=date(2026, 3, 1)
            )
        )
    assert len(requests) == 1
    assert len(requests[0].url.params.get_list("dates[]")) == 31


@pytest.mark.parametrize(
    "payload",
    [{"data": []}, {"data": [team_payload(), team_payload(2)]}, {"data": team_payload(2)}],
)
def test_single_team_ambiguous_or_wrong_identity_rejected(payload: dict[str, object]) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    with pytest.raises(SportsProviderResponseError):
        asyncio.run(provider_for(transport).get_team("1"))
