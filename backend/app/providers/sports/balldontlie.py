from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, date, datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr, ValidationError

from app.domain.sports import SportsEvent, SportsEventStatus, Team
from app.providers.sports.base import (
    SportsProviderAuthenticationError,
    SportsProviderResponseError,
    SportsProviderUnavailableError,
)


class BallDontLieTeamPayload(BaseModel):
    """Validated BALLDONTLIE team payload."""

    model_config = ConfigDict(extra="allow")

    id: int | str
    conference: str | None = None
    division: str | None = None
    city: str = Field(min_length=1)
    name: str = Field(min_length=1)
    full_name: str = Field(min_length=1)
    abbreviation: str = Field(min_length=2)


class BallDontLieGamePayload(BaseModel):
    """Validated BALLDONTLIE game payload used by Phase 2."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: int | str
    date: date
    season: int
    status: str = Field(min_length=1)
    period: int = Field(ge=0)
    time: str | None = None
    postseason: bool
    postponed: bool = False
    home_team_score: int = Field(ge=0)
    visitor_team_score: int = Field(ge=0)
    scheduled_at: datetime = Field(alias="datetime")
    ist_stage: str | None = None
    home_team: BallDontLieTeamPayload
    visitor_team: BallDontLieTeamPayload


class BallDontLieMeta(BaseModel):
    """Cursor metadata returned by paginated BALLDONTLIE endpoints."""

    model_config = ConfigDict(extra="ignore")

    next_cursor: int | str | None = None
    per_page: int | None = None


class BallDontLieTeamsResponse(BaseModel):
    """BALLDONTLIE all-teams response."""

    model_config = ConfigDict(extra="ignore")

    data: list[BallDontLieTeamPayload]


class BallDontLieTeamResponse(BaseModel):
    """BALLDONTLIE single-team response."""

    model_config = ConfigDict(extra="ignore")

    data: BallDontLieTeamPayload | list[BallDontLieTeamPayload]


class BallDontLieGamesResponse(BaseModel):
    """BALLDONTLIE cursor-paginated games response."""

    model_config = ConfigDict(extra="ignore")

    data: list[BallDontLieGamePayload]
    meta: BallDontLieMeta = Field(default_factory=BallDontLieMeta)


class BallDontLieGameResponse(BaseModel):
    """BALLDONTLIE single-game response."""

    model_config = ConfigDict(extra="ignore")

    data: BallDontLieGamePayload


def _json_dict(model: BaseModel) -> dict[str, JsonValue]:
    value = model.model_dump(mode="json", by_alias=True)
    return {str(key): item for key, item in value.items()}


def normalize_balldontlie_team(
    payload: BallDontLieTeamPayload,
    *,
    retrieved_at: datetime,
) -> Team:
    """Convert one BALLDONTLIE team into the provider-neutral model."""
    return Team(
        provider_name=BallDontLieSportsDataProvider.name,
        provider_team_id=str(payload.id),
        abbreviation=payload.abbreviation.upper(),
        city=payload.city,
        name=payload.name,
        full_name=payload.full_name,
        conference=payload.conference,
        division=payload.division,
        raw_data=_json_dict(payload),
        retrieved_at=retrieved_at,
    )


def normalize_game_status(
    payload: BallDontLieGamePayload,
    *,
    retrieved_at: datetime,
) -> SportsEventStatus:
    """Map BALLDONTLIE's display status into a stable lifecycle state."""
    status = payload.status.strip().casefold()
    if payload.postponed or "postpon" in status:
        return SportsEventStatus.POSTPONED
    if "cancel" in status:
        return SportsEventStatus.CANCELED
    if status.startswith("final"):
        return SportsEventStatus.FINAL
    if payload.period > 0 or status in {
        "1st qtr",
        "2nd qtr",
        "halftime",
        "3rd qtr",
        "4th qtr",
        "overtime",
    }:
        return SportsEventStatus.IN_PROGRESS
    if ":" in status or status in {"scheduled", "tbd"}:
        return SportsEventStatus.SCHEDULED
    if payload.scheduled_at > retrieved_at:
        return SportsEventStatus.SCHEDULED
    return SportsEventStatus.UNKNOWN


def normalize_balldontlie_game(
    payload: BallDontLieGamePayload,
    *,
    retrieved_at: datetime,
) -> SportsEvent:
    """Convert one BALLDONTLIE game into the provider-neutral model."""
    normalized_status = normalize_game_status(payload, retrieved_at=retrieved_at)
    has_score = normalized_status in {SportsEventStatus.IN_PROGRESS, SportsEventStatus.FINAL}
    return SportsEvent(
        provider_name=BallDontLieSportsDataProvider.name,
        provider_event_id=str(payload.id),
        season=payload.season,
        event_date=payload.date,
        scheduled_start_time=payload.scheduled_at,
        status=normalized_status,
        status_detail=payload.status,
        period=payload.period,
        clock=payload.time.strip() if payload.time and payload.time.strip() else None,
        postseason=payload.postseason,
        postponed=payload.postponed,
        tournament_stage=payload.ist_stage,
        home_team=normalize_balldontlie_team(payload.home_team, retrieved_at=retrieved_at),
        away_team=normalize_balldontlie_team(payload.visitor_team, retrieved_at=retrieved_at),
        home_score=payload.home_team_score if has_score else None,
        away_score=payload.visitor_team_score if has_score else None,
        raw_data=_json_dict(payload),
        retrieved_at=retrieved_at,
    )


class BallDontLieSportsDataProvider:
    """Read-only adapter for BALLDONTLIE NBA teams and games."""

    name = "balldontlie"

    def __init__(
        self,
        *,
        api_key: SecretStr,
        base_url: str,
        timeout_seconds: float,
        max_retries: int,
        max_pages: int,
        request_interval_seconds: float = 12.1,
        retry_backoff_seconds: float = 0.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key.get_secret_value().strip():
            raise ValueError("BALLDONTLIE API key cannot be empty")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds)
        self._max_retries = max_retries
        self._max_pages = max_pages
        self._request_interval_seconds = request_interval_seconds
        self._retry_backoff_seconds = retry_backoff_seconds
        self._transport = transport
        self._last_request_started: float | None = None
        self._pacing_lock = asyncio.Lock()

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": self._api_key.get_secret_value()},
            timeout=self._timeout,
            transport=self._transport,
        )

    async def _pace_request(self) -> None:
        """Serialize calls so one adapter respects the configured request rate."""
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
                if response.status_code in {401, 403}:
                    raise SportsProviderAuthenticationError(
                        "BALLDONTLIE rejected the configured credentials"
                    )
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                if response.is_error:
                    raise SportsProviderResponseError(
                        f"BALLDONTLIE returned HTTP {response.status_code} for {path}"
                    )
                payload = response.json()
                if not isinstance(payload, dict):
                    raise SportsProviderResponseError(
                        "BALLDONTLIE returned a non-object JSON response"
                    )
                return payload
            except SportsProviderAuthenticationError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                if attempt >= self._max_retries:
                    raise SportsProviderUnavailableError(
                        f"BALLDONTLIE remained unavailable after {attempt + 1} attempt(s)"
                    ) from exc
                retry_delay = self._retry_backoff_seconds * (2**attempt)
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                    retry_after = exc.response.headers.get("Retry-After")
                    if retry_after is not None:
                        with suppress(ValueError):
                            retry_delay = max(retry_delay, min(float(retry_after), 60.0))
                await asyncio.sleep(retry_delay)
            except ValueError as exc:
                raise SportsProviderResponseError("BALLDONTLIE returned invalid JSON") from exc
        raise AssertionError("provider retry loop exited unexpectedly")

    async def get_teams(self) -> list[Team]:
        """Retrieve and normalize all NBA teams."""
        retrieved_at = datetime.now(UTC)
        async with self._client() as client:
            raw_payload = await self._get_json(client, "/teams")
        try:
            payload = BallDontLieTeamsResponse.model_validate(raw_payload)
            return [
                normalize_balldontlie_team(team, retrieved_at=retrieved_at) for team in payload.data
            ]
        except ValidationError as exc:
            raise SportsProviderResponseError(
                "BALLDONTLIE teams response failed validation"
            ) from exc

    async def get_team(self, provider_team_id: str) -> Team:
        """Retrieve and normalize one NBA team."""
        retrieved_at = datetime.now(UTC)
        async with self._client() as client:
            raw_payload = await self._get_json(client, f"/teams/{provider_team_id}")
        try:
            payload = BallDontLieTeamResponse.model_validate(raw_payload)
            team = payload.data[0] if isinstance(payload.data, list) else payload.data
            return normalize_balldontlie_team(team, retrieved_at=retrieved_at)
        except (IndexError, ValidationError) as exc:
            raise SportsProviderResponseError(
                "BALLDONTLIE team response failed validation"
            ) from exc

    async def get_games(self, *, start_date: date, end_date: date) -> list[SportsEvent]:
        """Retrieve and normalize all games in an inclusive bounded date range."""
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        retrieved_at = datetime.now(UTC)
        cursor: int | str | None = None
        seen_cursors: set[str] = set()
        games: dict[str, SportsEvent] = {}

        async with self._client() as client:
            for _ in range(self._max_pages):
                params: dict[str, str | int] = {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "per_page": 100,
                }
                if cursor is not None:
                    params["cursor"] = cursor
                raw_payload = await self._get_json(client, "/games", params=params)
                try:
                    payload = BallDontLieGamesResponse.model_validate(raw_payload)
                    for game in payload.data:
                        normalized = normalize_balldontlie_game(
                            game,
                            retrieved_at=retrieved_at,
                        )
                        games[normalized.provider_event_id] = normalized
                except ValidationError as exc:
                    raise SportsProviderResponseError(
                        "BALLDONTLIE games response failed validation"
                    ) from exc

                next_cursor = payload.meta.next_cursor
                if next_cursor is None:
                    return list(games.values())
                cursor_key = str(next_cursor)
                if cursor_key in seen_cursors:
                    raise SportsProviderResponseError(
                        "BALLDONTLIE returned a repeated pagination cursor"
                    )
                seen_cursors.add(cursor_key)
                cursor = next_cursor

        raise SportsProviderResponseError(
            f"BALLDONTLIE pagination exceeded the configured {self._max_pages}-page limit"
        )

    async def get_game(self, provider_event_id: str) -> SportsEvent:
        """Retrieve and normalize one NBA game."""
        retrieved_at = datetime.now(UTC)
        async with self._client() as client:
            raw_payload = await self._get_json(client, f"/games/{provider_event_id}")
        try:
            payload = BallDontLieGameResponse.model_validate(raw_payload)
            return normalize_balldontlie_game(payload.data, retrieved_at=retrieved_at)
        except ValidationError as exc:
            raise SportsProviderResponseError(
                "BALLDONTLIE game response failed validation"
            ) from exc
