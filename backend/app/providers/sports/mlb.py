from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, date, datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from app.domain.sports import SportsEvent, SportsEventStatus, SportsLeague, Team
from app.providers.sports.base import (
    SportsProviderResponseError,
    SportsProviderUnavailableError,
)

_MLB_SPORT_ID = 1
_MLB_TEAM_HYDRATION = "league,division"
_MLB_GAME_HYDRATION = "team,venue,linescore"
_POSTSEASON_GAME_TYPES = frozenset({"F", "D", "L", "W"})


class MlbNamedReferencePayload(BaseModel):
    """Validated named reference embedded by the official MLB Stats API."""

    model_config = ConfigDict(extra="allow")

    id: int
    name: str = Field(min_length=1)


class MlbTeamPayload(BaseModel):
    """Validated MLB team payload used by team and schedule responses."""

    model_config = ConfigDict(extra="allow")

    id: int
    name: str = Field(min_length=1)
    abbreviation: str = Field(min_length=2)
    team_name: str = Field(alias="teamName", min_length=1)
    location_name: str = Field(alias="locationName", min_length=1)
    active: bool = True
    league: MlbNamedReferencePayload | None = None
    division: MlbNamedReferencePayload | None = None


class MlbTeamsResponse(BaseModel):
    """Official MLB team-list response."""

    model_config = ConfigDict(extra="ignore")

    teams: list[MlbTeamPayload]


class MlbGameStatusPayload(BaseModel):
    """Provider lifecycle fields for one MLB game."""

    model_config = ConfigDict(extra="allow")

    abstract_game_state: str = Field(alias="abstractGameState", min_length=1)
    detailed_state: str = Field(alias="detailedState", min_length=1)
    coded_game_state: str | None = Field(default=None, alias="codedGameState")
    status_code: str | None = Field(default=None, alias="statusCode")


class MlbGameTeamPayload(BaseModel):
    """One home or away team within an MLB schedule game."""

    model_config = ConfigDict(extra="allow")

    team: MlbTeamPayload
    score: int | None = Field(default=None, ge=0)


class MlbGameTeamsPayload(BaseModel):
    """Home and away sides for one MLB game."""

    model_config = ConfigDict(extra="ignore")

    home: MlbGameTeamPayload
    away: MlbGameTeamPayload


class MlbLineScorePayload(BaseModel):
    """Small linescore subset used for inning state."""

    model_config = ConfigDict(extra="allow")

    current_inning: int = Field(default=0, alias="currentInning", ge=0)
    current_inning_ordinal: str | None = Field(default=None, alias="currentInningOrdinal")
    inning_state: str | None = Field(default=None, alias="inningState")


class MlbGamePayload(BaseModel):
    """Validated official MLB schedule game."""

    model_config = ConfigDict(extra="allow")

    game_pk: int = Field(alias="gamePk")
    game_type: str = Field(alias="gameType", min_length=1)
    season: int
    game_date: datetime = Field(alias="gameDate")
    official_date: date = Field(alias="officialDate")
    status: MlbGameStatusPayload
    teams: MlbGameTeamsPayload
    linescore: MlbLineScorePayload | None = None
    venue: MlbNamedReferencePayload | None = None
    series_description: str | None = Field(default=None, alias="seriesDescription")


class MlbScheduleDatePayload(BaseModel):
    """One calendar-date group returned by the MLB schedule endpoint."""

    model_config = ConfigDict(extra="ignore")

    games: list[MlbGamePayload] = Field(default_factory=list)


class MlbScheduleResponse(BaseModel):
    """Official MLB schedule response."""

    model_config = ConfigDict(extra="ignore")

    dates: list[MlbScheduleDatePayload] = Field(default_factory=list)


def _json_dict(model: BaseModel) -> dict[str, JsonValue]:
    value = model.model_dump(mode="json", by_alias=True)
    return {str(key): item for key, item in value.items()}


def normalize_mlb_team(payload: MlbTeamPayload, *, retrieved_at: datetime) -> Team:
    """Convert an official MLB team into the provider-neutral model."""
    return Team(
        provider_name=MlbStatsSportsDataProvider.name,
        provider_team_id=str(payload.id),
        league=SportsLeague.MLB,
        abbreviation=payload.abbreviation.upper(),
        city=payload.location_name,
        name=payload.team_name,
        full_name=payload.name,
        conference=payload.league.name if payload.league is not None else None,
        division=payload.division.name if payload.division is not None else None,
        raw_data=_json_dict(payload),
        retrieved_at=retrieved_at,
    )


def normalize_mlb_game_status(payload: MlbGamePayload) -> SportsEventStatus:
    """Map official MLB lifecycle values to the normalized event states."""
    detailed_state = payload.status.detailed_state.casefold()
    abstract_state = payload.status.abstract_game_state.casefold()
    status_code = (payload.status.status_code or "").casefold()

    if "postpon" in detailed_state or "suspend" in detailed_state:
        return SportsEventStatus.POSTPONED
    if "cancel" in detailed_state:
        return SportsEventStatus.CANCELED
    if abstract_state == "final" or status_code in {"f", "o"}:
        return SportsEventStatus.FINAL
    if abstract_state == "live" or status_code in {"i", "m"}:
        return SportsEventStatus.IN_PROGRESS
    if abstract_state == "preview" or status_code in {"p", "s"}:
        return SportsEventStatus.SCHEDULED
    return SportsEventStatus.UNKNOWN


def _inning_clock(linescore: MlbLineScorePayload | None) -> str | None:
    if linescore is None or linescore.current_inning <= 0:
        return None
    components = [linescore.inning_state, linescore.current_inning_ordinal]
    value = " ".join(component.strip() for component in components if component)
    return value or None


def normalize_mlb_game(payload: MlbGamePayload, *, retrieved_at: datetime) -> SportsEvent:
    """Convert one official MLB schedule game into the normalized event model."""
    normalized_status = normalize_mlb_game_status(payload)
    has_score = normalized_status in {SportsEventStatus.IN_PROGRESS, SportsEventStatus.FINAL}
    linescore = payload.linescore
    return SportsEvent(
        provider_name=MlbStatsSportsDataProvider.name,
        provider_event_id=str(payload.game_pk),
        league=SportsLeague.MLB,
        season=payload.season,
        event_date=payload.official_date,
        scheduled_start_time=payload.game_date,
        status=normalized_status,
        status_detail=payload.status.detailed_state,
        period=linescore.current_inning if linescore is not None else 0,
        clock=_inning_clock(linescore),
        postseason=payload.game_type.upper() in _POSTSEASON_GAME_TYPES,
        postponed=normalized_status is SportsEventStatus.POSTPONED,
        tournament_stage=payload.series_description,
        home_team=normalize_mlb_team(payload.teams.home.team, retrieved_at=retrieved_at),
        away_team=normalize_mlb_team(payload.teams.away.team, retrieved_at=retrieved_at),
        home_score=payload.teams.home.score if has_score else None,
        away_score=payload.teams.away.score if has_score else None,
        venue=payload.venue.name if payload.venue is not None else None,
        raw_data=_json_dict(payload),
        retrieved_at=retrieved_at,
    )


class MlbStatsSportsDataProvider:
    """Read-only adapter for official MLB team, schedule, and result data."""

    name = "mlb"

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        max_retries: int,
        request_interval_seconds: float = 0.25,
        retry_backoff_seconds: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds)
        self._max_retries = max_retries
        self._request_interval_seconds = request_interval_seconds
        self._retry_backoff_seconds = retry_backoff_seconds
        self._transport = transport
        self._last_request_started: float | None = None
        self._pacing_lock = asyncio.Lock()

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
            transport=self._transport,
        )

    async def _pace_request(self) -> None:
        async with self._pacing_lock:
            if self._last_request_started is not None:
                loop = asyncio.get_running_loop()
                elapsed = loop.time() - self._last_request_started
                remaining = self._request_interval_seconds - elapsed
                if remaining > 0:
                    await asyncio.sleep(remaining)
            self._last_request_started = asyncio.get_running_loop().time()

    async def _get_json(
        self,
        client: httpx.AsyncClient,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
    ) -> dict[str, Any]:
        for attempt in range(self._max_retries + 1):
            try:
                await self._pace_request()
                response = await client.get(path, params=params)
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                if response.is_error:
                    raise SportsProviderResponseError(
                        f"MLB Stats API returned HTTP {response.status_code} for {path}"
                    )
                payload = response.json()
                if not isinstance(payload, dict):
                    raise SportsProviderResponseError(
                        "MLB Stats API returned a non-object JSON response"
                    )
                return payload
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                if attempt >= self._max_retries:
                    raise SportsProviderUnavailableError(
                        f"MLB Stats API remained unavailable after {attempt + 1} attempt(s)"
                    ) from exc
                retry_delay = self._retry_backoff_seconds * (2**attempt)
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                    retry_after = exc.response.headers.get("Retry-After")
                    if retry_after is not None:
                        with suppress(ValueError):
                            retry_delay = max(retry_delay, min(float(retry_after), 60.0))
                await asyncio.sleep(retry_delay)
            except ValueError as exc:
                raise SportsProviderResponseError("MLB Stats API returned invalid JSON") from exc
        raise AssertionError("provider retry loop exited unexpectedly")

    async def get_teams(self) -> list[Team]:
        """Retrieve and normalize all active Major League Baseball teams."""
        retrieved_at = datetime.now(UTC)
        async with self._client() as client:
            raw_payload = await self._get_json(
                client,
                "/teams",
                params={
                    "sportId": _MLB_SPORT_ID,
                    "activeStatus": "Yes",
                    "hydrate": _MLB_TEAM_HYDRATION,
                },
            )
        try:
            payload = MlbTeamsResponse.model_validate(raw_payload)
            return [
                normalize_mlb_team(team, retrieved_at=retrieved_at)
                for team in payload.teams
                if team.active
            ]
        except ValidationError as exc:
            raise SportsProviderResponseError("MLB teams response failed validation") from exc

    async def get_team(self, provider_team_id: str) -> Team:
        """Retrieve and normalize one Major League Baseball team."""
        retrieved_at = datetime.now(UTC)
        async with self._client() as client:
            raw_payload = await self._get_json(
                client,
                f"/teams/{provider_team_id}",
                params={
                    "sportId": _MLB_SPORT_ID,
                    "hydrate": _MLB_TEAM_HYDRATION,
                },
            )
        try:
            payload = MlbTeamsResponse.model_validate(raw_payload)
            team = payload.teams[0]
            return normalize_mlb_team(team, retrieved_at=retrieved_at)
        except (IndexError, ValidationError) as exc:
            raise SportsProviderResponseError("MLB team response failed validation") from exc

    async def get_games(self, *, start_date: date, end_date: date) -> list[SportsEvent]:
        """Retrieve and normalize MLB games in an inclusive date range."""
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        retrieved_at = datetime.now(UTC)
        async with self._client() as client:
            raw_payload = await self._get_json(
                client,
                "/schedule",
                params={
                    "sportId": _MLB_SPORT_ID,
                    "startDate": start_date.isoformat(),
                    "endDate": end_date.isoformat(),
                    "hydrate": _MLB_GAME_HYDRATION,
                },
            )
        try:
            payload = MlbScheduleResponse.model_validate(raw_payload)
            games = {
                str(game.game_pk): normalize_mlb_game(game, retrieved_at=retrieved_at)
                for date_group in payload.dates
                for game in date_group.games
            }
            return list(games.values())
        except ValidationError as exc:
            raise SportsProviderResponseError("MLB schedule response failed validation") from exc

    async def get_game(self, provider_event_id: str) -> SportsEvent:
        """Retrieve and normalize one MLB game by official gamePk."""
        retrieved_at = datetime.now(UTC)
        async with self._client() as client:
            raw_payload = await self._get_json(
                client,
                "/schedule",
                params={
                    "sportId": _MLB_SPORT_ID,
                    "gamePk": provider_event_id,
                    "hydrate": _MLB_GAME_HYDRATION,
                },
            )
        try:
            payload = MlbScheduleResponse.model_validate(raw_payload)
            game = next(game for date_group in payload.dates for game in date_group.games)
            return normalize_mlb_game(game, retrieved_at=retrieved_at)
        except (StopIteration, ValidationError) as exc:
            raise SportsProviderResponseError("MLB game response failed validation") from exc
