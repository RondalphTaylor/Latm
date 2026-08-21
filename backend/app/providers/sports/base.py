from __future__ import annotations

from datetime import date
from typing import Protocol

from app.domain.sports import SportsEvent, Team


class SportsDataProviderError(RuntimeError):
    """Base error raised when a sports provider cannot return valid data."""


class SportsProviderUnavailableError(SportsDataProviderError):
    """The sports provider remained temporarily unavailable."""


class SportsProviderResponseError(SportsDataProviderError):
    """The sports provider returned an unsuccessful or invalid response."""


class SportsProviderAuthenticationError(SportsDataProviderError):
    """The configured sports-provider credentials were rejected."""


class SportsDataProvider(Protocol):
    """Read-only provider boundary used by sports-ingestion business logic."""

    name: str

    async def get_teams(self) -> list[Team]: ...

    async def get_team(self, provider_team_id: str) -> Team: ...

    async def get_games(self, *, start_date: date, end_date: date) -> list[SportsEvent]: ...

    async def get_game(self, provider_event_id: str) -> SportsEvent: ...
