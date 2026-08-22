from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from app.domain.matching import MarketEventMatchDecision, MatchingPolicy
from app.domain.sports import SportsLeague
from app.models.markets import MarketOutcomeRecord, PredictionMarketRecord
from app.models.sports import SportsEventRecord, TeamRecord
from app.services.matching.matcher import MATCHER_VERSION, MarketEventMatcher
from app.services.matching.service import MarketEventMatchingService

BOS_ID = UUID("a7129d9c-0d4c-44d6-8a2d-dda4dc34cf82")
NYK_ID = UUID("92d9bccf-dd34-4f1f-8886-9d2e884940d1")
MARKET_ID = UUID("3da220e1-b6d0-45e9-b507-7e75dc95a353")
EVENT_ID = UUID("8701782a-4d22-4147-9d60-edbf2e243adc")
TIP_TIME = datetime(2026, 8, 1, 23, tzinfo=UTC)


def team_record(
    *,
    team_id: UUID,
    provider_id: str,
    abbreviation: str,
    city: str,
    name: str,
) -> TeamRecord:
    return TeamRecord(
        id=team_id,
        provider_name="balldontlie",
        provider_team_id=provider_id,
        league="nba",
        abbreviation=abbreviation,
        city=city,
        name=name,
        full_name=f"{city} {name}",
        conference="East",
        division="Atlantic",
        raw_data={},
        first_seen_at=TIP_TIME,
        last_seen_at=TIP_TIME,
    )


def market_record() -> PredictionMarketRecord:
    record = PredictionMarketRecord(
        id=MARKET_ID,
        provider_name="kalshi",
        provider_market_id="BOS-NYK-BOS",
        provider_event_id="BOS-NYK",
        series_ticker="NBA-GAME",
        category="Sports",
        market_type="binary",
        title="Will Boston win the Pro Basketball game?",
        subtitle="BOS vs NYK",
        rules_primary=None,
        rules_secondary=None,
        status="open",
        is_nba=True,
        sports_league="nba",
        sports_market_type="single_game_winner",
        sports_classification_method="official_series_metadata",
        sports_classification_version="kalshi-official-series-v1",
        sports_classification_fingerprint="b" * 64,
        open_time=None,
        close_time=TIP_TIME + timedelta(hours=2),
        occurrence_time=TIP_TIME,
        provider_created_at=None,
        provider_updated_at=None,
        raw_data={},
        first_seen_at=TIP_TIME,
        last_seen_at=TIP_TIME,
    )
    record.outcomes = [
        MarketOutcomeRecord(
            id=UUID("8925e3e6-d86e-47e8-a4a4-99d091b29030"),
            market_id=MARKET_ID,
            provider_outcome_id="yes",
            side="yes",
            label="Boston",
        )
    ]
    return record


def event_record() -> SportsEventRecord:
    return SportsEventRecord(
        id=EVENT_ID,
        provider_name="balldontlie",
        provider_event_id="15907925",
        league="nba",
        season=2025,
        event_date=TIP_TIME.date(),
        scheduled_start_time=TIP_TIME,
        status="scheduled",
        status_detail="7:00 pm ET",
        period=0,
        clock=None,
        postseason=False,
        postponed=False,
        tournament_stage=None,
        home_team_id=BOS_ID,
        away_team_id=NYK_ID,
        home_score=None,
        away_score=None,
        venue=None,
        raw_data={},
        first_seen_at=TIP_TIME,
        last_seen_at=TIP_TIME,
    )


class FakeMatchingRepository:
    def __init__(self, *, include_records: bool = True) -> None:
        self.include_records = include_records
        self.calls: dict[str, object] = {}
        self.decisions: list[MarketEventMatchDecision] = []

    async def list_markets_for_matching(self, **kwargs: object) -> list[PredictionMarketRecord]:
        self.calls["markets"] = kwargs
        return [market_record()] if self.include_records else []

    async def list_teams_for_matching(self, **kwargs: object) -> list[TeamRecord]:
        self.calls["teams"] = kwargs
        if not self.include_records:
            return []
        return [
            team_record(
                team_id=BOS_ID,
                provider_id="2",
                abbreviation="BOS",
                city="Boston",
                name="Celtics",
            ),
            team_record(
                team_id=NYK_ID,
                provider_id="20",
                abbreviation="NYK",
                city="New York",
                name="Knicks",
            ),
        ]

    async def list_events_for_matching(self, **kwargs: object) -> list[SportsEventRecord]:
        self.calls["events"] = kwargs
        return [event_record()] if self.include_records else []

    async def insert_decisions(self, decisions: list[MarketEventMatchDecision]) -> int:
        self.decisions = list(decisions)
        return len(self.decisions)


def service(repository: FakeMatchingRepository) -> MarketEventMatchingService:
    matching_policy = MatchingPolicy(
        matcher_version=MATCHER_VERSION,
        min_confidence=Decimal("0.90"),
        ambiguity_margin=Decimal("0.10"),
        time_window_hours=36,
    )
    return MarketEventMatchingService(
        repository=repository,  # type: ignore[arg-type]
        matcher=MarketEventMatcher(matching_policy),
        policy=matching_policy,
    )


def test_matching_run_persists_and_summarizes_decisions() -> None:
    repository = FakeMatchingRepository()

    result = asyncio.run(
        service(repository).run(
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1),
            market_id=None,
            limit=250,
            offset=0,
        )
    )

    assert result.examined == 1
    assert result.league is SportsLeague.NBA
    assert result.persisted == 1
    assert result.matched == 1
    assert result.ambiguous == 0
    assert result.unmatched == 0
    assert repository.decisions[0].sports_event_id == EVENT_ID
    assert repository.calls["markets"] == {
        "reference_start": datetime(2026, 7, 30, 12, tzinfo=UTC),
        "reference_end": datetime(2026, 8, 3, 12, tzinfo=UTC),
        "market_id": None,
        "limit": 250,
        "offset": 0,
        "league": SportsLeague.NBA,
    }
    assert repository.calls["teams"] == {
        "provider_name": "balldontlie",
        "league": SportsLeague.NBA,
    }
    assert repository.calls["events"] == {
        "provider_name": "balldontlie",
        "start_date": date(2026, 7, 30),
        "end_date": date(2026, 8, 3),
        "league": SportsLeague.NBA,
    }


def test_empty_local_snapshots_return_zero_summary() -> None:
    repository = FakeMatchingRepository(include_records=False)

    result = asyncio.run(
        service(repository).run(
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 1),
            market_id=None,
            limit=250,
            offset=0,
        )
    )

    assert result.examined == 0
    assert result.persisted == 0


@pytest.mark.parametrize(
    ("start_date", "end_date", "message"),
    [
        (date(2026, 8, 2), date(2026, 8, 1), "must not be after"),
        (date(2026, 8, 1), date(2026, 9, 1), "cannot exceed 31"),
    ],
)
def test_invalid_range_fails_before_repository_calls(
    start_date: date,
    end_date: date,
    message: str,
) -> None:
    repository = FakeMatchingRepository()

    with pytest.raises(ValueError, match=message):
        asyncio.run(
            service(repository).run(
                start_date=start_date,
                end_date=end_date,
                market_id=None,
                limit=250,
                offset=0,
            )
        )

    assert repository.calls == {}
