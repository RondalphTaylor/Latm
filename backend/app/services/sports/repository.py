from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from itertools import batched
from uuid import UUID, uuid5

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.domain.sports import SportsEvent, Team
from app.models.markets import Provider
from app.models.sports import SportsEventRecord, TeamRecord

_LATM_SPORTS_NAMESPACE = UUID("9b989f97-beb8-4aab-9a67-0355d2cfa897")
_UPSERT_BATCH_SIZE = 500


def team_record_id(provider_name: str, provider_team_id: str) -> UUID:
    """Return a stable internal team ID for a provider identity."""
    return uuid5(_LATM_SPORTS_NAMESPACE, f"team:{provider_name}:{provider_team_id}")


def sports_event_record_id(provider_name: str, provider_event_id: str) -> UUID:
    """Return a stable internal sports-event ID for a provider identity."""
    return uuid5(_LATM_SPORTS_NAMESPACE, f"event:{provider_name}:{provider_event_id}")


@dataclass(frozen=True)
class SportsUpsertResult:
    """Counts written during one sports-event transaction."""

    teams: int
    events: int


class SportsRepository:
    """Persist and query normalized sports teams and events."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _provider_values(provider_names: set[str]) -> list[dict[str, object]]:
        display_names = {
            "balldontlie": "BALLDONTLIE",
            "mlb": "MLB Stats API",
        }
        return [
            {
                "name": name,
                "display_name": display_names.get(name, name.title()),
                "is_read_only": True,
            }
            for name in sorted(provider_names)
        ]

    @staticmethod
    def _deduplicate_teams(teams: Sequence[Team]) -> list[Team]:
        identities = {(team.provider_name, team.provider_team_id): team for team in teams}
        return list(identities.values())

    async def _upsert_providers(self, values: list[dict[str, object]]) -> None:
        provider_insert = insert(Provider).values(values)
        await self._session.execute(
            provider_insert.on_conflict_do_update(
                index_elements=[Provider.name],
                set_={
                    "display_name": provider_insert.excluded.display_name,
                    "is_read_only": True,
                },
            )
        )

    async def _upsert_team_values(self, values: list[dict[str, object]]) -> None:
        for batch in batched(values, _UPSERT_BATCH_SIZE, strict=False):
            team_insert = insert(TeamRecord).values(list(batch))
            await self._session.execute(
                team_insert.on_conflict_do_update(
                    constraint="uq_teams_provider_team_id",
                    set_={
                        column: getattr(team_insert.excluded, column)
                        for column in (
                            "league",
                            "abbreviation",
                            "city",
                            "name",
                            "full_name",
                            "conference",
                            "division",
                            "raw_data",
                            "last_seen_at",
                        )
                    },
                )
            )

    async def _upsert_event_values(self, values: list[dict[str, object]]) -> None:
        for batch in batched(values, _UPSERT_BATCH_SIZE, strict=False):
            event_insert = insert(SportsEventRecord).values(list(batch))
            await self._session.execute(
                event_insert.on_conflict_do_update(
                    constraint="uq_sports_events_provider_event_id",
                    set_={
                        column: getattr(event_insert.excluded, column)
                        for column in (
                            "league",
                            "season",
                            "event_date",
                            "scheduled_start_time",
                            "status",
                            "status_detail",
                            "period",
                            "clock",
                            "postseason",
                            "postponed",
                            "tournament_stage",
                            "home_team_id",
                            "away_team_id",
                            "home_score",
                            "away_score",
                            "venue",
                            "raw_data",
                            "last_seen_at",
                        )
                    },
                )
            )

    @staticmethod
    def _team_values(teams: Sequence[Team]) -> list[dict[str, object]]:
        return [
            {
                "id": team_record_id(team.provider_name, team.provider_team_id),
                "provider_name": team.provider_name,
                "provider_team_id": team.provider_team_id,
                "league": team.league.value,
                "abbreviation": team.abbreviation,
                "city": team.city,
                "name": team.name,
                "full_name": team.full_name,
                "conference": team.conference,
                "division": team.division,
                "raw_data": team.raw_data,
                "first_seen_at": team.retrieved_at,
                "last_seen_at": team.retrieved_at,
            }
            for team in teams
        ]

    @staticmethod
    def _event_values(events: Sequence[SportsEvent]) -> list[dict[str, object]]:
        return [
            {
                "id": sports_event_record_id(event.provider_name, event.provider_event_id),
                "provider_name": event.provider_name,
                "provider_event_id": event.provider_event_id,
                "league": event.league.value,
                "season": event.season,
                "event_date": event.event_date,
                "scheduled_start_time": event.scheduled_start_time,
                "status": event.status.value,
                "status_detail": event.status_detail,
                "period": event.period,
                "clock": event.clock,
                "postseason": event.postseason,
                "postponed": event.postponed,
                "tournament_stage": event.tournament_stage,
                "home_team_id": team_record_id(
                    event.home_team.provider_name,
                    event.home_team.provider_team_id,
                ),
                "away_team_id": team_record_id(
                    event.away_team.provider_name,
                    event.away_team.provider_team_id,
                ),
                "home_score": event.home_score,
                "away_score": event.away_score,
                "venue": event.venue,
                "raw_data": event.raw_data,
                "first_seen_at": event.retrieved_at,
                "last_seen_at": event.retrieved_at,
            }
            for event in events
        ]

    async def upsert_teams(self, teams: Sequence[Team]) -> int:
        """Upsert team identities without duplicating repeated provider records."""
        unique_teams = self._deduplicate_teams(teams)
        if not unique_teams:
            return 0
        try:
            await self._upsert_providers(
                self._provider_values({team.provider_name for team in unique_teams})
            )
            await self._upsert_team_values(self._team_values(unique_teams))
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        return len(unique_teams)

    async def upsert_events(self, events: Sequence[SportsEvent]) -> SportsUpsertResult:
        """Atomically upsert embedded teams followed by event identities."""
        unique_events = list(
            {(event.provider_name, event.provider_event_id): event for event in events}.values()
        )
        if not unique_events:
            return SportsUpsertResult(teams=0, events=0)
        unique_teams = self._deduplicate_teams(
            [team for event in unique_events for team in (event.home_team, event.away_team)]
        )
        provider_names = {team.provider_name for team in unique_teams} | {
            event.provider_name for event in unique_events
        }
        try:
            await self._upsert_providers(self._provider_values(provider_names))
            await self._upsert_team_values(self._team_values(unique_teams))
            await self._upsert_event_values(self._event_values(unique_events))
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise
        return SportsUpsertResult(teams=len(unique_teams), events=len(unique_events))

    async def list_teams(
        self,
        *,
        league: str | None,
        provider_name: str | None,
        limit: int,
        offset: int,
    ) -> list[TeamRecord]:
        """Return persisted teams using provider-neutral filters."""
        statement = select(TeamRecord).order_by(TeamRecord.full_name).limit(limit).offset(offset)
        if league is not None:
            statement = statement.where(TeamRecord.league == league)
        if provider_name is not None:
            statement = statement.where(TeamRecord.provider_name == provider_name)
        result = await self._session.scalars(statement)
        return list(result.all())

    async def get_team(self, team_id: UUID) -> TeamRecord | None:
        """Return one persisted team by stable internal ID."""
        result = await self._session.scalars(select(TeamRecord).where(TeamRecord.id == team_id))
        return result.one_or_none()

    async def list_events(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
        league: str | None,
        event_status: str | None,
        team_id: UUID | None,
        provider_name: str | None,
        limit: int,
        offset: int,
    ) -> list[SportsEventRecord]:
        """Return persisted sports events using provider-neutral filters."""
        statement = (
            select(SportsEventRecord)
            .options(
                joinedload(SportsEventRecord.home_team),
                joinedload(SportsEventRecord.away_team),
            )
            .order_by(SportsEventRecord.scheduled_start_time)
            .limit(limit)
            .offset(offset)
        )
        if start_date is not None:
            statement = statement.where(SportsEventRecord.event_date >= start_date)
        if end_date is not None:
            statement = statement.where(SportsEventRecord.event_date <= end_date)
        if league is not None:
            statement = statement.where(SportsEventRecord.league == league)
        if event_status is not None:
            statement = statement.where(SportsEventRecord.status == event_status)
        if team_id is not None:
            statement = statement.where(
                or_(
                    SportsEventRecord.home_team_id == team_id,
                    SportsEventRecord.away_team_id == team_id,
                )
            )
        if provider_name is not None:
            statement = statement.where(SportsEventRecord.provider_name == provider_name)
        result = await self._session.scalars(statement)
        return list(result.unique().all())

    async def get_event(self, event_id: UUID) -> SportsEventRecord | None:
        """Return one persisted NBA event by stable internal ID."""
        statement = (
            select(SportsEventRecord)
            .where(SportsEventRecord.id == event_id)
            .options(
                joinedload(SportsEventRecord.home_team),
                joinedload(SportsEventRecord.away_team),
            )
        )
        result = await self._session.scalars(statement)
        return result.unique().one_or_none()
