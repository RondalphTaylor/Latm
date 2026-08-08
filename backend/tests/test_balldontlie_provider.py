from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import httpx
import pytest
from pydantic import SecretStr

from app.domain.sports import SportsEventStatus
from app.providers.sports.balldontlie import (
    BallDontLieGamePayload,
    BallDontLieSportsDataProvider,
    BallDontLieTeamPayload,
    normalize_balldontlie_game,
    normalize_balldontlie_team,
)
from app.providers.sports.base import (
    SportsProviderAuthenticationError,
    SportsProviderResponseError,
    SportsProviderUnavailableError,
)


def team_payload(
    *,
    team_id: int = 2,
    abbreviation: str = "BOS",
    city: str = "Boston",
    name: str = "Celtics",
) -> dict[str, object]:
    return {
        "id": team_id,
        "conference": "East",
        "division": "Atlantic",
        "city": city,
        "name": name,
        "full_name": f"{city} {name}",
        "abbreviation": abbreviation,
    }


def game_payload(
    *,
    game_id: int = 15907925,
    game_status: str = "Final",
    period: int = 4,
    postponed: bool = False,
    scheduled_at: str = "2026-08-01T23:00:00Z",
    home_score: int = 115,
    away_score: int = 105,
) -> dict[str, object]:
    return {
        "id": game_id,
        "date": "2026-08-01",
        "season": 2025,
        "status": game_status,
        "period": period,
        "time": "Final" if game_status.casefold().startswith("final") else "3:44",
        "postseason": False,
        "postponed": postponed,
        "home_team_score": home_score,
        "visitor_team_score": away_score,
        "datetime": scheduled_at,
        "ist_stage": None,
        "home_team": team_payload(),
        "visitor_team": team_payload(
            team_id=20,
            abbreviation="NYK",
            city="New York",
            name="Knicks",
        ),
    }


def provider_for(
    transport: httpx.AsyncBaseTransport,
    *,
    retries: int = 0,
    max_pages: int = 5,
) -> BallDontLieSportsDataProvider:
    return BallDontLieSportsDataProvider(
        api_key=SecretStr("test-api-key"),
        base_url="https://example.test/v1",
        timeout_seconds=1.0,
        max_retries=retries,
        max_pages=max_pages,
        request_interval_seconds=0,
        retry_backoff_seconds=0,
        transport=transport,
    )


def test_normalizes_team_and_preserves_raw_payload() -> None:
    payload = BallDontLieTeamPayload.model_validate(team_payload())

    team = normalize_balldontlie_team(
        payload,
        retrieved_at=datetime(2026, 8, 1, tzinfo=UTC),
    )

    assert team.provider_name == "balldontlie"
    assert team.provider_team_id == "2"
    assert team.abbreviation == "BOS"
    assert team.full_name == "Boston Celtics"
    assert team.raw_data["id"] == 2


@pytest.mark.parametrize(
    ("game_status", "period", "postponed", "scheduled_at", "expected"),
    [
        ("7:00 pm ET", 0, False, "2026-08-02T23:00:00Z", SportsEventStatus.SCHEDULED),
        ("Halftime", 2, False, "2026-08-01T20:00:00Z", SportsEventStatus.IN_PROGRESS),
        ("Final", 4, False, "2026-08-01T20:00:00Z", SportsEventStatus.FINAL),
        ("7:00 pm ET", 0, True, "2026-08-02T23:00:00Z", SportsEventStatus.POSTPONED),
        ("Canceled", 0, False, "2026-08-01T20:00:00Z", SportsEventStatus.CANCELED),
        ("Data pending", 0, False, "2026-07-01T20:00:00Z", SportsEventStatus.UNKNOWN),
    ],
)
def test_normalizes_game_statuses(
    game_status: str,
    period: int,
    postponed: bool,
    scheduled_at: str,
    expected: SportsEventStatus,
) -> None:
    payload = BallDontLieGamePayload.model_validate(
        game_payload(
            game_status=game_status,
            period=period,
            postponed=postponed,
            scheduled_at=scheduled_at,
        )
    )

    event = normalize_balldontlie_game(
        payload,
        retrieved_at=datetime(2026, 8, 1, 12, tzinfo=UTC),
    )

    assert event.status is expected
    assert event.away_team.abbreviation == "NYK"
    if expected in {SportsEventStatus.FINAL, SportsEventStatus.IN_PROGRESS}:
        assert (event.home_score, event.away_score) == (115, 105)
    else:
        assert event.home_score is None
        assert event.away_score is None


def test_get_games_sends_auth_and_follows_cursor_pagination() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.params.get("cursor") is None:
            return httpx.Response(
                200,
                json={
                    "data": [game_payload()],
                    "meta": {"next_cursor": 25, "per_page": 100},
                },
            )
        return httpx.Response(
            200,
            json={
                "data": [game_payload(game_id=15907926)],
                "meta": {"per_page": 100},
            },
        )

    games = asyncio.run(
        provider_for(httpx.MockTransport(handler)).get_games(
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
        )
    )

    assert len(games) == 2
    assert requests[0].headers["Authorization"] == "test-api-key"
    assert requests[0].url.params["start_date"] == "2026-08-01"
    assert requests[0].url.params["end_date"] == "2026-08-02"
    assert requests[0].url.params["per_page"] == "100"
    assert requests[1].url.params["cursor"] == "25"


def test_get_teams_and_single_resources() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/teams"):
            return httpx.Response(200, json={"data": [team_payload()]})
        if request.url.path.endswith("/teams/2"):
            return httpx.Response(200, json={"data": [team_payload()]})
        return httpx.Response(200, json={"data": game_payload()})

    provider = provider_for(httpx.MockTransport(handler))

    teams = asyncio.run(provider.get_teams())
    team = asyncio.run(provider.get_team("2"))
    game = asyncio.run(provider.get_game("15907925"))

    assert len(teams) == 1
    assert team.full_name == "Boston Celtics"
    assert game.status is SportsEventStatus.FINAL


def test_rate_limit_is_retried() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"data": []})

    teams = asyncio.run(provider_for(httpx.MockTransport(handler), retries=1).get_teams())

    assert teams == []
    assert attempts == 2


def test_rejected_credentials_fail_without_leaking_key() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    with pytest.raises(SportsProviderAuthenticationError) as error:
        asyncio.run(provider_for(httpx.MockTransport(handler)).get_teams())

    assert "test-api-key" not in str(error.value)


def test_network_failure_raises_safe_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with pytest.raises(SportsProviderUnavailableError):
        asyncio.run(provider_for(httpx.MockTransport(handler), retries=1).get_teams())


def test_malformed_response_fails_validation() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": 2}]})

    with pytest.raises(SportsProviderResponseError):
        asyncio.run(provider_for(httpx.MockTransport(handler)).get_teams())


def test_repeated_cursor_fails_safely() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [], "meta": {"next_cursor": 25, "per_page": 100}},
        )

    with pytest.raises(SportsProviderResponseError, match="repeated pagination cursor"):
        asyncio.run(
            provider_for(httpx.MockTransport(handler)).get_games(
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 2),
            )
        )
