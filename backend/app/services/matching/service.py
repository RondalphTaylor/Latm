from __future__ import annotations

import math
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.matching import (
    MarketEventMatchStatus,
    MarketMatchInput,
    MatchingPolicy,
    SportsEventMatchInput,
    TeamMatchInput,
)
from app.models.markets import PredictionMarketRecord
from app.models.sports import SportsEventRecord, TeamRecord
from app.services.matching.matcher import MarketEventMatcher
from app.services.matching.repository import MatchingRepository

_MAX_MATCHING_RANGE_DAYS = 31


class MatchingRunResult(BaseModel):
    """Audit summary for one bounded local matching run."""

    model_config = ConfigDict(frozen=True)

    matcher_version: str
    start_date: date
    end_date: date
    examined: int = Field(ge=0)
    persisted: int = Field(ge=0)
    matched: int = Field(ge=0)
    ambiguous: int = Field(ge=0)
    unmatched: int = Field(ge=0)


class MarketEventMatchingService:
    """Coordinate bounded matching using only locally persisted snapshots."""

    def __init__(
        self,
        *,
        repository: MatchingRepository,
        matcher: MarketEventMatcher,
        policy: MatchingPolicy,
        sports_provider_name: str,
    ) -> None:
        self._repository = repository
        self._matcher = matcher
        self._policy = policy
        self._sports_provider_name = sports_provider_name

    async def run(
        self,
        *,
        start_date: date,
        end_date: date,
        market_id: UUID | None,
        limit: int,
        offset: int,
    ) -> MatchingRunResult:
        """Evaluate and append a bounded batch of semantic match decisions."""
        self._validate_date_range(start_date, end_date)
        padding = timedelta(hours=self._policy.time_window_hours)
        reference_start = datetime.combine(start_date, time.min, tzinfo=UTC) - padding
        reference_end = (
            datetime.combine(
                end_date + timedelta(days=1),
                time.min,
                tzinfo=UTC,
            )
            + padding
        )
        event_padding_days = math.ceil(self._policy.time_window_hours / 24)

        markets = await self._repository.list_markets_for_matching(
            reference_start=reference_start,
            reference_end=reference_end,
            market_id=market_id,
            limit=limit,
            offset=offset,
        )
        teams = await self._repository.list_teams_for_matching(
            provider_name=self._sports_provider_name
        )
        events = await self._repository.list_events_for_matching(
            provider_name=self._sports_provider_name,
            start_date=start_date - timedelta(days=event_padding_days),
            end_date=end_date + timedelta(days=event_padding_days),
        )

        team_inputs = tuple(self._team_input(team) for team in teams)
        event_inputs = tuple(self._event_input(event) for event in events)
        evaluated_at = datetime.now(UTC)
        decisions = [
            self._matcher.match(
                self._market_input(market),
                teams=team_inputs,
                events=event_inputs,
                evaluated_at=evaluated_at,
            )
            for market in markets
        ]
        persisted = await self._repository.insert_decisions(decisions)
        status_counts = {
            status: sum(decision.status is status for decision in decisions)
            for status in MarketEventMatchStatus
        }
        return MatchingRunResult(
            matcher_version=self._policy.matcher_version,
            start_date=start_date,
            end_date=end_date,
            examined=len(decisions),
            persisted=persisted,
            matched=status_counts[MarketEventMatchStatus.MATCHED],
            ambiguous=status_counts[MarketEventMatchStatus.AMBIGUOUS],
            unmatched=status_counts[MarketEventMatchStatus.UNMATCHED],
        )

    @staticmethod
    def _validate_date_range(start_date: date, end_date: date) -> None:
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        inclusive_days = (end_date - start_date).days + 1
        if inclusive_days > _MAX_MATCHING_RANGE_DAYS:
            raise ValueError(
                f"matching date range cannot exceed {_MAX_MATCHING_RANGE_DAYS} inclusive days"
            )

    @staticmethod
    def _team_input(record: TeamRecord) -> TeamMatchInput:
        return TeamMatchInput(
            id=record.id,
            abbreviation=record.abbreviation,
            city=record.city,
            name=record.name,
            full_name=record.full_name,
        )

    @staticmethod
    def _event_input(record: SportsEventRecord) -> SportsEventMatchInput:
        return SportsEventMatchInput(
            id=record.id,
            event_date=record.event_date,
            scheduled_start_time=record.scheduled_start_time,
            home_team_id=record.home_team_id,
            away_team_id=record.away_team_id,
            last_seen_at=record.last_seen_at,
        )

    @staticmethod
    def _market_input(record: PredictionMarketRecord) -> MarketMatchInput:
        return MarketMatchInput(
            id=record.id,
            title=record.title,
            subtitle=record.subtitle,
            rules_primary=record.rules_primary,
            rules_secondary=record.rules_secondary,
            category=record.category,
            market_type=record.market_type,
            outcome_labels=tuple(outcome.label for outcome in record.outcomes),
            occurrence_time=record.occurrence_time,
            close_time=record.close_time,
            last_seen_at=record.last_seen_at,
        )
