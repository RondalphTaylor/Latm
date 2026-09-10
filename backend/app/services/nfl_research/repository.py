from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sports import SportsEventRecord
from app.providers.sports.nfl import NflGamePayload
from app.services.nfl_research.baseline import NflResearchGame

MAX_SOURCE_ROWS = 10_000
_EASTERN = ZoneInfo("America/New_York")
_RAW_SOURCE = TypeAdapter(dict[str, JsonValue])
IgnoredReason = Literal[
    "out_of_scope_season", "postseason", "nonfinal", "missing_source_week", "invalid_metadata"
]


class NflResearchSourceSnapshot(BaseModel):
    """Exact local source evidence; latest result observations are retrospective."""

    model_config = ConfigDict(frozen=True)

    event_id: UUID
    provider_event_id: str
    season: int
    status: str
    postseason: bool
    scheduled_start: datetime
    home_team_id: UUID
    away_team_id: UUID
    home_score: int | None
    away_score: int | None
    source_last_seen: datetime
    raw_data: dict[str, JsonValue]


class NflIgnoredResearchEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: UUID
    reason: IgnoredReason


class NflResearchSelection(BaseModel):
    model_config = ConfigDict(frozen=True)

    games: tuple[NflResearchGame, ...]
    sources: tuple[NflResearchSourceSnapshot, ...]
    ignored: tuple[NflIgnoredResearchEvent, ...]
    ignored_reason_counts: dict[str, int]
    blockers: tuple[str, ...]
    source_fingerprint: str


def _select_records(records: list[SportsEventRecord], *, truncated: bool) -> NflResearchSelection:
    games: list[NflResearchGame] = []
    sources: list[NflResearchSourceSnapshot] = []
    ignored: list[NflIgnoredResearchEvent] = []
    for record in records:
        snapshot = NflResearchSourceSnapshot(
            event_id=record.id,
            provider_event_id=record.provider_event_id,
            season=record.season,
            status=record.status,
            postseason=record.postseason,
            scheduled_start=record.scheduled_start_time,
            home_team_id=record.home_team_id,
            away_team_id=record.away_team_id,
            home_score=record.home_score,
            away_score=record.away_score,
            source_last_seen=record.last_seen_at,
            raw_data=_RAW_SOURCE.validate_python(record.raw_data),
        )
        sources.append(snapshot)
        reason: IgnoredReason | None = None
        if not 2018 <= record.season <= 2025:
            reason = "out_of_scope_season"
        elif record.postseason:
            reason = "postseason"
        elif record.status != "final":
            reason = "nonfinal"
        elif "week" not in record.raw_data:
            reason = "missing_source_week"
        else:
            try:
                payload = NflGamePayload.model_validate(record.raw_data)
                home_score, away_score = record.home_score, record.away_score
                kickoff_date = record.scheduled_start_time.astimezone(_EASTERN).date()
                season_type = record.raw_data.get("season_type")
                if (
                    str(payload.id) != record.provider_event_id
                    or payload.season != record.season
                    or payload.postseason != record.postseason
                    or payload.status_state.strip().casefold() != "final"
                    or payload.date != record.scheduled_start_time
                    or payload.home_team_score != record.home_score
                    or payload.visitor_team_score != record.away_score
                    or str(payload.home_team.id) != record.home_team.provider_team_id
                    or str(payload.visitor_team.id) != record.away_team.provider_team_id
                    or record.home_team.provider_name != "balldontlie_nfl"
                    or record.away_team.provider_name != "balldontlie_nfl"
                    or record.home_team.league != "nfl"
                    or record.away_team.league != "nfl"
                    or type(record.raw_data["week"]) is not int
                    or home_score is None
                    or away_score is None
                    or record.raw_data.get("preseason", False) is not False
                    or (
                        season_type is not None
                        and season_type
                        not in (2, "2", "regular", "regular_season", "regular season", "REG")
                    )
                    or not (
                        (kickoff_date.year == record.season and kickoff_date.month >= 9)
                        or (kickoff_date.year == record.season + 1 and kickoff_date.month == 1)
                    )
                    or payload.week > (17 if record.season <= 2020 else 18)
                ):
                    raise ValueError("source metadata conflicts with normalized result")
                games.append(
                    NflResearchGame(
                        event_id=record.id,
                        provider_event_id=record.provider_event_id,
                        season=record.season,
                        week=payload.week,
                        scheduled_start=record.scheduled_start_time,
                        home_team_id=record.home_team_id,
                        away_team_id=record.away_team_id,
                        home_score=home_score,
                        away_score=away_score,
                        source_last_seen=record.last_seen_at,
                    )
                )
            except (ValidationError, ValueError):
                reason = "invalid_metadata"
        if reason is not None:
            ignored.append(NflIgnoredResearchEvent(event_id=record.id, reason=reason))
    counts: dict[str, int] = {
        str(reason): count
        for reason, count in sorted(Counter(item.reason for item in ignored).items())
    }
    blockers: list[str] = []
    if truncated:
        blockers.append("source_row_limit_exceeded")
    if counts.get("missing_source_week", 0) or counts.get("invalid_metadata", 0):
        blockers.append("invalid_final_source_records")
    if not games:
        blockers.append("no_eligible_historical_games")
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "sources": [source.model_dump(mode="json") for source in sources],
                "truncated": truncated,
                "selection_version": "nfl-local-results-v1",
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return NflResearchSelection(
        games=tuple(games),
        sources=tuple(sources),
        ignored=tuple(ignored),
        ignored_reason_counts=counts,
        blockers=tuple(blockers),
        source_fingerprint=fingerprint,
    )


class NflResearchRepository:
    """Bounded SELECT-only access to NFL results; no provider calls or writes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def select_games(self) -> NflResearchSelection:
        statement = (
            select(SportsEventRecord)
            .where(
                SportsEventRecord.provider_name == "balldontlie_nfl",
                SportsEventRecord.league == "nfl",
            )
            .order_by(SportsEventRecord.scheduled_start_time, SportsEventRecord.id)
            .limit(MAX_SOURCE_ROWS + 1)
        )
        result = await self._session.scalars(statement)
        records = list(result.unique().all())
        return _select_records(records[:MAX_SOURCE_ROWS], truncated=len(records) > MAX_SOURCE_ROWS)
