from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from app.domain.sports import SportsEvent, SportsEventStatus, SportsLeague, Team
from app.providers.sports.balldontlie import (
    BallDontLieMeta,
    BallDontLieSportsDataProvider,
    _json_dict,
)
from app.providers.sports.base import SportsProviderResponseError

_EASTERN = ZoneInfo("America/New_York")


class NflTeamPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int | str
    location: str = Field(min_length=1)
    name: str = Field(min_length=1)
    full_name: str = Field(min_length=1)
    abbreviation: str = Field(min_length=2)
    conference: str | None = None
    division: str | None = None


class NflGamePayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int | str
    date: AwareDatetime
    season: int
    week: int = Field(ge=0)
    postseason: bool
    status: str = Field(min_length=1)
    status_state: str = Field(min_length=1)
    period: int | None = Field(default=None, ge=0)
    home_team_score: int | None = Field(default=None, ge=0)
    visitor_team_score: int | None = Field(default=None, ge=0)
    home_team: NflTeamPayload
    visitor_team: NflTeamPayload
    venue: str | None = None


class NflTeamsResponse(BaseModel):
    data: list[NflTeamPayload]


class NflTeamResponse(BaseModel):
    data: NflTeamPayload | list[NflTeamPayload]


class NflGamesResponse(BaseModel):
    data: list[NflGamePayload]
    meta: BallDontLieMeta = Field(default_factory=BallDontLieMeta)


class NflGameResponse(BaseModel):
    data: NflGamePayload


def normalize_nfl_team(payload: NflTeamPayload, *, retrieved_at: datetime) -> Team:
    return Team(
        provider_name=BallDontLieNflSportsDataProvider.name,
        provider_team_id=str(payload.id),
        league=SportsLeague.NFL,
        abbreviation=payload.abbreviation.upper(),
        city=payload.location,
        name=payload.name,
        full_name=payload.full_name,
        conference=payload.conference,
        division=payload.division,
        raw_data=_json_dict(payload),
        retrieved_at=retrieved_at,
    )


def normalize_nfl_game(payload: NflGamePayload, *, retrieved_at: datetime) -> SportsEvent:
    """Preserve explicit lifecycle and tie scores; never infer results from time."""
    state = payload.status_state.strip().casefold()
    status = {
        "scheduled": SportsEventStatus.SCHEDULED,
        "in_progress": SportsEventStatus.IN_PROGRESS,
        "final": SportsEventStatus.FINAL,
        "postponed": SportsEventStatus.POSTPONED,
        "canceled": SportsEventStatus.CANCELED,
    }.get(state, SportsEventStatus.UNKNOWN)
    has_score = status in {SportsEventStatus.IN_PROGRESS, SportsEventStatus.FINAL}
    return SportsEvent(
        provider_name=BallDontLieNflSportsDataProvider.name,
        provider_event_id=str(payload.id),
        league=SportsLeague.NFL,
        season=payload.season,
        event_date=payload.date.astimezone(_EASTERN).date(),
        scheduled_start_time=payload.date,
        status=status,
        status_detail=payload.status,
        # The common schema uses zero for unavailable period; never derive it from week.
        period=payload.period if payload.period is not None else 0,
        postseason=payload.postseason,
        postponed=status is SportsEventStatus.POSTPONED,
        home_team=normalize_nfl_team(payload.home_team, retrieved_at=retrieved_at),
        away_team=normalize_nfl_team(payload.visitor_team, retrieved_at=retrieved_at),
        home_score=payload.home_team_score if has_score else None,
        away_score=payload.visitor_team_score if has_score else None,
        venue=payload.venue,
        raw_data=_json_dict(payload),
        retrieved_at=retrieved_at,
    )


class BallDontLieNflSportsDataProvider(BallDontLieSportsDataProvider):
    """Read-only NFL adapter sharing only authenticated transport with NBA.

    NFL does not document start_date/end_date filters. Query dates[] in bounded
    chunks with one-day timezone padding, then filter kickoff dates in Eastern
    time. Provider defaults exclude preseason. Pagination failure returns no
    partial dataset. All NFL identities are distinct from NBA identities.
    """

    name = "balldontlie_nfl"

    async def get_teams(self) -> list[Team]:
        retrieved_at = datetime.now(UTC)
        async with self._client() as client:
            raw = await self._get_json(client, "/teams")
        try:
            response = NflTeamsResponse.model_validate(raw)
            return [normalize_nfl_team(team, retrieved_at=retrieved_at) for team in response.data]
        except ValidationError as exc:
            raise SportsProviderResponseError("NFL teams response failed validation") from exc

    async def get_team(self, provider_team_id: str) -> Team:
        retrieved_at = datetime.now(UTC)
        async with self._client() as client:
            raw = await self._get_json(client, f"/teams/{provider_team_id}")
        try:
            response = NflTeamResponse.model_validate(raw)
            if isinstance(response.data, list):
                if len(response.data) != 1:
                    raise SportsProviderResponseError("NFL team response must contain one team")
                team = response.data[0]
            else:
                team = response.data
            if str(team.id) != provider_team_id:
                raise SportsProviderResponseError("NFL team response identity mismatch")
            return normalize_nfl_team(team, retrieved_at=retrieved_at)
        except ValidationError as exc:
            raise SportsProviderResponseError("NFL team response failed validation") from exc

    async def get_game(self, provider_event_id: str) -> SportsEvent:
        retrieved_at = datetime.now(UTC)
        async with self._client() as client:
            raw = await self._get_json(client, f"/games/{provider_event_id}")
        try:
            response = NflGameResponse.model_validate(raw)
            if str(response.data.id) != provider_event_id:
                raise SportsProviderResponseError("NFL game response identity mismatch")
            return normalize_nfl_game(response.data, retrieved_at=retrieved_at)
        except ValidationError as exc:
            raise SportsProviderResponseError("NFL game response failed validation") from exc

    async def get_games(self, *, start_date: date, end_date: date) -> list[SportsEvent]:
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        retrieved_at = datetime.now(UTC)
        games: dict[str, SportsEvent] = {}
        pages = 0
        query_date = start_date - timedelta(days=1)
        padded_end = end_date + timedelta(days=1)
        async with self._client() as client:
            while query_date <= padded_end:
                dates: list[tuple[str, str]] = []
                for _ in range(31):
                    if query_date > padded_end:
                        break
                    dates.append(("dates[]", query_date.isoformat()))
                    query_date += timedelta(days=1)
                cursor: int | str | None = None
                seen: set[str] = set()
                while True:
                    if pages >= self._max_pages:
                        raise SportsProviderResponseError(
                            f"NFL pagination exceeded the configured {self._max_pages}-page limit"
                        )
                    params = [*dates, ("per_page", "100")]
                    if cursor is not None:
                        params.append(("cursor", str(cursor)))
                    raw = await self._get_json(client, f"/games?{httpx.QueryParams(tuple(params))}")
                    pages += 1
                    try:
                        response = NflGamesResponse.model_validate(raw)
                        for game in response.data:
                            if start_date <= game.date.astimezone(_EASTERN).date() <= end_date:
                                event = normalize_nfl_game(game, retrieved_at=retrieved_at)
                                games[event.provider_event_id] = event
                    except ValidationError as exc:
                        raise SportsProviderResponseError(
                            "NFL games response failed validation"
                        ) from exc
                    cursor = response.meta.next_cursor
                    if cursor is None:
                        break
                    if str(cursor) in seen:
                        raise SportsProviderResponseError(
                            "NFL returned a repeated pagination cursor"
                        )
                    seen.add(str(cursor))
        return sorted(
            games.values(), key=lambda game: (game.scheduled_start_time, game.provider_event_id)
        )
