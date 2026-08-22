from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import httpx
import pytest

from app.domain.mlb_lineups import MlbLineupState, MlbObservationPhase
from app.domain.sports import SportsEventStatus, SportsLeague
from app.providers.sports.base import (
    SportsProviderResponseError,
    SportsProviderUnavailableError,
)
from app.providers.sports.mlb import (
    MlbGamePayload,
    MlbLiveFeedPayload,
    MlbStatsSportsDataProvider,
    MlbTeamPayload,
    normalize_mlb_game,
    normalize_mlb_lineup_snapshot,
    normalize_mlb_team,
)


def lineup_feed_payload(
    *,
    timestamp: str = "20260822_120000",
    abstract_state: str = "Preview",
    home_order_size: int = 9,
    away_order_size: int = 9,
) -> dict[str, object]:
    home_ids = list(range(1001, 1010))
    away_ids = list(range(2001, 2010))
    all_ids = [677960, 656302, *home_ids, *away_ids]
    game_players = {
        f"ID{player_id}": {
            "id": player_id,
            "fullName": f"Player {player_id}",
            "primaryPosition": {"abbreviation": "P" if player_id < 1_000_000 else "CF"},
            "batSide": {"code": "R"},
            "pitchHand": {"code": "L" if player_id == 677960 else "R"},
        }
        for player_id in all_ids
    }

    def boxscore_side(player_ids: list[int], size: int) -> dict[str, object]:
        return {
            "battingOrder": player_ids[:size],
            "players": {
                f"ID{player_id}": {
                    "person": {"id": player_id, "fullName": f"Player {player_id}"},
                    "position": {"abbreviation": "CF"},
                }
                for player_id in player_ids
            },
        }

    return {
        "gamePk": 823509,
        "metaData": {"timeStamp": timestamp},
        "gameData": {
            "datetime": {"dateTime": "2026-08-22T17:35:00Z"},
            "status": {
                "abstractGameState": abstract_state,
                "detailedState": "Scheduled" if abstract_state == "Preview" else abstract_state,
            },
            "teams": {"home": {"id": 147}, "away": {"id": 141}},
            "probablePitchers": {
                "home": {"id": 677960, "fullName": "Ryan Weathers"},
                "away": {"id": 656302, "fullName": "Dylan Cease"},
            },
            "players": game_players,
        },
        "liveData": {
            "boxscore": {
                "teams": {
                    "home": boxscore_side(home_ids, home_order_size),
                    "away": boxscore_side(away_ids, away_order_size),
                }
            }
        },
    }


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


def test_normalizes_posted_pregame_lineups_and_probable_pitchers() -> None:
    payload = MlbLiveFeedPayload.model_validate(lineup_feed_payload())

    snapshot = normalize_mlb_lineup_snapshot(
        payload,
        retrieved_at=datetime(2026, 8, 22, 12, 1, tzinfo=UTC),
    )

    assert snapshot.provider_event_id == "823509"
    assert snapshot.observation_phase is MlbObservationPhase.PREGAME
    assert snapshot.home_lineup_state is MlbLineupState.POSTED
    assert snapshot.away_lineup_state is MlbLineupState.POSTED
    assert snapshot.complete_for_pregame_model is True
    assert len(snapshot.home_lineup) == 9
    assert snapshot.home_lineup[0].batting_order == 1
    assert snapshot.home_lineup[0].provider_player_id == "1001"
    assert snapshot.home_probable_pitcher is not None
    assert snapshot.home_probable_pitcher.full_name == "Ryan Weathers"
    assert snapshot.home_probable_pitcher.pitch_hand == "L"
    assert snapshot.source_snapshot["gamePk"] == 823509
    assert len(snapshot.input_fingerprint) == 64


@pytest.mark.parametrize(
    ("home_size", "away_size", "home_state", "away_state"),
    [
        (0, 0, MlbLineupState.UNAVAILABLE, MlbLineupState.UNAVAILABLE),
        (4, 9, MlbLineupState.PARTIAL, MlbLineupState.POSTED),
    ],
)
def test_partial_or_unavailable_lineups_are_preserved_but_not_complete(
    home_size: int,
    away_size: int,
    home_state: MlbLineupState,
    away_state: MlbLineupState,
) -> None:
    snapshot = normalize_mlb_lineup_snapshot(
        MlbLiveFeedPayload.model_validate(
            lineup_feed_payload(home_order_size=home_size, away_order_size=away_size)
        ),
        retrieved_at=datetime(2026, 8, 22, 12, 1, tzinfo=UTC),
    )

    assert snapshot.home_lineup_state is home_state
    assert snapshot.away_lineup_state is away_state
    assert snapshot.complete_for_pregame_model is False


@pytest.mark.parametrize(
    ("abstract_state", "retrieved_at", "expected_phase"),
    [
        ("Live", datetime(2026, 8, 22, 17, tzinfo=UTC), MlbObservationPhase.LIVE),
        ("Final", datetime(2026, 8, 23, tzinfo=UTC), MlbObservationPhase.POSTGAME),
        (
            "Preview",
            datetime(2026, 8, 22, 17, 36, tzinfo=UTC),
            MlbObservationPhase.LIVE,
        ),
    ],
)
def test_non_pregame_observations_never_become_model_complete(
    abstract_state: str,
    retrieved_at: datetime,
    expected_phase: MlbObservationPhase,
) -> None:
    snapshot = normalize_mlb_lineup_snapshot(
        MlbLiveFeedPayload.model_validate(lineup_feed_payload(abstract_state=abstract_state)),
        retrieved_at=retrieved_at,
    )

    assert snapshot.observation_phase is expected_phase
    assert snapshot.complete_for_pregame_model is False


def test_lineup_fingerprint_replays_exact_source_and_changes_with_update() -> None:
    retrieved_at = datetime(2026, 8, 22, 12, 1, tzinfo=UTC)
    first = normalize_mlb_lineup_snapshot(
        MlbLiveFeedPayload.model_validate(lineup_feed_payload()),
        retrieved_at=retrieved_at,
    )
    replay = normalize_mlb_lineup_snapshot(
        MlbLiveFeedPayload.model_validate(lineup_feed_payload()),
        retrieved_at=retrieved_at.replace(minute=2),
    )
    changed = normalize_mlb_lineup_snapshot(
        MlbLiveFeedPayload.model_validate(lineup_feed_payload(timestamp="20260822_120100")),
        retrieved_at=retrieved_at.replace(minute=2),
    )

    assert replay.input_fingerprint == first.input_fingerprint
    assert changed.input_fingerprint != first.input_fingerprint


def test_get_lineup_snapshot_uses_official_versioned_live_feed() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=lineup_feed_payload())

    snapshot = asyncio.run(provider_for(httpx.MockTransport(handler)).get_lineup_snapshot("823509"))

    assert snapshot.provider_event_id == "823509"
    assert requests[0].url.path == "/api/v1.1/game/823509/feed/live"
    assert "Authorization" not in requests[0].headers


def test_lineup_feed_wrong_game_and_missing_player_fail_safely() -> None:
    wrong_game = lineup_feed_payload()
    wrong_game["gamePk"] = 1
    provider = provider_for(httpx.MockTransport(lambda _: httpx.Response(200, json=wrong_game)))
    with pytest.raises(SportsProviderResponseError, match="wrong game identity"):
        asyncio.run(provider.get_lineup_snapshot("823509"))

    missing_player = lineup_feed_payload()
    boxscore = missing_player["liveData"]
    assert isinstance(boxscore, dict)
    teams = boxscore["boxscore"]
    assert isinstance(teams, dict)
    side_container = teams["teams"]
    assert isinstance(side_container, dict)
    home = side_container["home"]
    assert isinstance(home, dict)
    players = home["players"]
    assert isinstance(players, dict)
    players.pop("ID1001")
    malformed_provider = provider_for(
        httpx.MockTransport(lambda _: httpx.Response(200, json=missing_player))
    )
    with pytest.raises(SportsProviderResponseError, match="invalid lineup"):
        asyncio.run(malformed_provider.get_lineup_snapshot("823509"))


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
