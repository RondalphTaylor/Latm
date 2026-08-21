from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import httpx
import pytest

from app.domain.sports import SportsEventStatus, SportsLeague
from app.providers.sports.base import (
    SportsProviderResponseError,
    SportsProviderUnavailableError,
)
from app.providers.sports.mlb import (
    MlbGamePayload,
    MlbStatsSportsDataProvider,
    MlbTeamPayload,
    normalize_mlb_game,
    normalize_mlb_team,
)


def team_payload(
    *,
    team_id: int = 147,
    abbreviation: str = "NYY",
    location: str = "New York",
    team_name: str = "Yankees",
) -> dict[str, object]:
    return {
        "id": team_id,
        "name": f"{location} {team_name}",
        "abbreviation": abbreviation,
        "teamName": team_name,
        "locationName": location,
        "active": True,
        "league": {"id": 103, "name": "American League"},
        "division": {"id": 201, "name": "American League East"},
    }


def game_payload(
    *,
    detailed_state: str = "Final",
    abstract_state: str = "Final",
    status_code: str = "F",
    game_type: str = "R",
    inning: int = 9,
    home_score: int | None = 4,
    away_score: int | None = 5,
) -> dict[str, object]:
    return {
        "gamePk": 824802,
        "gameType": game_type,
        "season": "2026",
        "gameDate": "2026-08-20T22:35:00Z",
        "officialDate": "2026-08-20",
        "status": {
            "abstractGameState": abstract_state,
            "codedGameState": status_code,
            "detailedState": detailed_state,
            "statusCode": status_code,
        },
        "teams": {
            "away": {
                "team": team_payload(),
                "score": away_score,
            },
            "home": {
                "team": team_payload(
                    team_id=110,
                    abbreviation="BAL",
                    location="Baltimore",
                    team_name="Orioles",
                ),
                "score": home_score,
            },
        },
        "linescore": {
            "currentInning": inning,
            "currentInningOrdinal": f"{inning}th",
            "inningState": "Bottom",
        },
        "venue": {"id": 2, "name": "Oriole Park at Camden Yards"},
        "seriesDescription": "Regular Season",
    }


def provider_for(
    transport: httpx.AsyncBaseTransport,
    *,
    retries: int = 0,
) -> MlbStatsSportsDataProvider:
    return MlbStatsSportsDataProvider(
        base_url="https://example.test/api/v1",
        timeout_seconds=1.0,
        max_retries=retries,
        request_interval_seconds=0,
        retry_backoff_seconds=0,
        transport=transport,
    )


def test_normalizes_official_mlb_team_with_league_identity() -> None:
    payload = MlbTeamPayload.model_validate(team_payload())

    team = normalize_mlb_team(
        payload,
        retrieved_at=datetime(2026, 8, 20, tzinfo=UTC),
    )

    assert team.provider_name == "mlb"
    assert team.provider_team_id == "147"
    assert team.league is SportsLeague.MLB
    assert team.abbreviation == "NYY"
    assert team.conference == "American League"
    assert team.division == "American League East"
    assert team.raw_data["teamName"] == "Yankees"


@pytest.mark.parametrize(
    ("detailed", "abstract", "code", "expected"),
    [
        ("Scheduled", "Preview", "S", SportsEventStatus.SCHEDULED),
        ("In Progress", "Live", "I", SportsEventStatus.IN_PROGRESS),
        ("Final", "Final", "F", SportsEventStatus.FINAL),
        ("Postponed", "Preview", "DR", SportsEventStatus.POSTPONED),
        ("Suspended", "Live", "I", SportsEventStatus.POSTPONED),
        ("Cancelled", "Final", "C", SportsEventStatus.CANCELED),
        ("Data pending", "Unknown", "U", SportsEventStatus.UNKNOWN),
    ],
)
def test_normalizes_mlb_game_statuses(
    detailed: str,
    abstract: str,
    code: str,
    expected: SportsEventStatus,
) -> None:
    payload = MlbGamePayload.model_validate(
        game_payload(
            detailed_state=detailed,
            abstract_state=abstract,
            status_code=code,
        )
    )

    event = normalize_mlb_game(
        payload,
        retrieved_at=datetime(2026, 8, 20, 16, tzinfo=UTC),
    )

    assert event.league is SportsLeague.MLB
    assert event.status is expected
    assert event.provider_event_id == "824802"
    assert event.away_team.abbreviation == "NYY"
    assert event.home_team.abbreviation == "BAL"
    assert event.venue == "Oriole Park at Camden Yards"
    if expected in {SportsEventStatus.IN_PROGRESS, SportsEventStatus.FINAL}:
        assert (event.home_score, event.away_score) == (4, 5)
    else:
        assert event.home_score is None
        assert event.away_score is None


def test_postseason_and_live_inning_metadata_are_preserved() -> None:
    payload = MlbGamePayload.model_validate(
        game_payload(
            detailed_state="In Progress",
            abstract_state="Live",
            status_code="I",
            game_type="D",
            inning=7,
        )
    )

    event = normalize_mlb_game(
        payload,
        retrieved_at=datetime(2026, 8, 20, 23, tzinfo=UTC),
    )

    assert event.postseason is True
    assert event.period == 7
    assert event.clock == "Bottom 7th"


def test_get_teams_games_and_single_resources_use_public_official_endpoints() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/teams") or request.url.path.endswith("/teams/147"):
            return httpx.Response(200, json={"teams": [team_payload()]})
        return httpx.Response(
            200,
            json={"dates": [{"date": "2026-08-20", "games": [game_payload()]}]},
        )

    provider = provider_for(httpx.MockTransport(handler))

    teams = asyncio.run(provider.get_teams())
    team = asyncio.run(provider.get_team("147"))
    games = asyncio.run(
        provider.get_games(start_date=date(2026, 8, 20), end_date=date(2026, 8, 21))
    )
    game = asyncio.run(provider.get_game("824802"))

    assert len(teams) == 1
    assert team.full_name == "New York Yankees"
    assert len(games) == 1
    assert game.status is SportsEventStatus.FINAL
    assert "Authorization" not in requests[0].headers
    team_params = requests[0].url.params
    assert team_params["sportId"] == "1"
    assert team_params["activeStatus"] == "Yes"
    schedule_request = next(request for request in requests if "startDate" in request.url.params)
    assert schedule_request.url.params["startDate"] == "2026-08-20"
    assert schedule_request.url.params["endDate"] == "2026-08-21"
    assert schedule_request.url.params["hydrate"] == "team,venue,linescore"
    game_request = next(request for request in requests if "gamePk" in request.url.params)
    assert game_request.url.params["gamePk"] == "824802"


def test_rate_limit_is_retried() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"teams": []})

    teams = asyncio.run(provider_for(httpx.MockTransport(handler), retries=1).get_teams())

    assert teams == []
    assert attempts == 2


def test_network_and_malformed_responses_fail_safely() -> None:
    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with pytest.raises(SportsProviderUnavailableError):
        asyncio.run(provider_for(httpx.MockTransport(offline), retries=1).get_teams())

    malformed = httpx.MockTransport(lambda _: httpx.Response(200, json={"teams": [{"id": 1}]}))
    with pytest.raises(SportsProviderResponseError):
        asyncio.run(provider_for(malformed).get_teams())
