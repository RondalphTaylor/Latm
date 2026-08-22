from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

from app.domain.opportunities import OpportunityDecision, OpportunityPolicy
from app.models.forecasts import BaseForecastRecord
from app.models.markets import (
    MarketOutcomeRecord,
    MarketPriceRecord,
    PredictionMarketRecord,
)
from app.models.matching import MarketEventMatchRecord
from app.models.sports import SportsEventRecord, TeamRecord
from app.services.forecasting.elo import source_event_fingerprint
from app.services.opportunities.repository import (
    OpportunityRepository,
    OpportunitySourceBundle,
)
from app.services.opportunities.service import (
    OpportunityDetectionService,
    OpportunityRunResult,
)

RUN_AT = datetime(2026, 8, 8, 16, tzinfo=UTC)
MARKET_ID = UUID("10000000-0000-0000-0000-000000000001")
PRICE_ID = UUID("10000000-0000-0000-0000-000000000002")
MATCH_ID = UUID("10000000-0000-0000-0000-000000000003")
EVENT_ID = UUID("10000000-0000-0000-0000-000000000004")
FORECAST_ID = UUID("10000000-0000-0000-0000-000000000005")
MODEL_ID = UUID("10000000-0000-0000-0000-000000000006")
HOME_ID = UUID("10000000-0000-0000-0000-000000000007")
AWAY_ID = UUID("10000000-0000-0000-0000-000000000008")


class FakeOpportunityRepository:
    def __init__(self, bundles: list[OpportunitySourceBundle]) -> None:
        self.bundles = bundles
        self.decisions: list[OpportunityDecision] = []
        self.arguments: dict[str, object] | None = None

    async def list_source_bundles(self, **kwargs: object) -> list[OpportunitySourceBundle]:
        self.arguments = kwargs
        return self.bundles

    async def persist_opportunities(self, decisions: list[OpportunityDecision]) -> int:
        self.decisions = list(decisions)
        return len(decisions)


def _team(team_id: UUID, abbreviation: str, city: str, name: str) -> TeamRecord:
    return TeamRecord(
        id=team_id,
        provider_name="balldontlie",
        provider_team_id=abbreviation,
        league="nba",
        abbreviation=abbreviation,
        city=city,
        name=name,
        full_name=f"{city} {name}",
        conference=None,
        division=None,
        raw_data={},
        first_seen_at=RUN_AT - timedelta(days=1),
        last_seen_at=RUN_AT - timedelta(minutes=20),
    )


def source_bundle() -> OpportunitySourceBundle:
    home = _team(HOME_ID, "BOS", "Boston", "Celtics")
    away = _team(AWAY_ID, "NYK", "New York", "Knicks")
    market = PredictionMarketRecord(
        id=MARKET_ID,
        provider_name="kalshi",
        provider_market_id="fixture",
        provider_event_id=None,
        series_ticker=None,
        category="Sports",
        market_type="binary",
        title="Will the Boston Celtics win?",
        subtitle=None,
        rules_primary=None,
        rules_secondary=None,
        status="active",
        is_nba=True,
        open_time=RUN_AT - timedelta(days=1),
        close_time=RUN_AT + timedelta(hours=2),
        occurrence_time=RUN_AT + timedelta(hours=2),
        provider_created_at=None,
        provider_updated_at=None,
        raw_data={},
        first_seen_at=RUN_AT - timedelta(days=1),
        last_seen_at=RUN_AT - timedelta(minutes=1),
    )
    market.outcomes = [
        MarketOutcomeRecord(
            id=UUID("10000000-0000-0000-0000-000000000009"),
            market_id=MARKET_ID,
            provider_outcome_id="yes",
            side="yes",
            label="Boston Celtics",
        ),
        MarketOutcomeRecord(
            id=UUID("10000000-0000-0000-0000-000000000010"),
            market_id=MARKET_ID,
            provider_outcome_id="no",
            side="no",
            label="New York Knicks",
        ),
    ]
    event = SportsEventRecord(
        id=EVENT_ID,
        provider_name="balldontlie",
        provider_event_id="game",
        league="nba",
        season=2026,
        event_date=date(2026, 8, 8),
        scheduled_start_time=RUN_AT + timedelta(hours=2),
        status="scheduled",
        status_detail="Scheduled",
        period=0,
        clock=None,
        postseason=False,
        postponed=False,
        tournament_stage=None,
        home_team_id=HOME_ID,
        away_team_id=AWAY_ID,
        home_score=None,
        away_score=None,
        venue=None,
        raw_data={},
        first_seen_at=RUN_AT - timedelta(days=1),
        last_seen_at=RUN_AT - timedelta(minutes=20),
    )
    event.home_team = home
    event.away_team = away
    match = MarketEventMatchRecord(
        id=MATCH_ID,
        market_id=MARKET_ID,
        league="nba",
        sports_event_id=EVENT_ID,
        status="matched",
        confidence=Decimal("0.99"),
        method="fixture",
        reason="fixture",
        matcher_version="1.0.0",
        min_confidence=Decimal("0.90"),
        ambiguity_margin=Decimal("0.10"),
        time_window_hours=36,
        automatic_trading_eligible=True,
        input_fingerprint="a" * 64,
        team_signals=[],
        candidate_scores=[],
        evidence={},
        evaluated_at=RUN_AT - timedelta(minutes=20),
    )
    price = MarketPriceRecord(
        id=PRICE_ID,
        market_id=MARKET_ID,
        yes_bid=Decimal("0.53"),
        yes_ask=Decimal("0.55"),
        no_bid=Decimal("0.45"),
        no_ask=Decimal("0.47"),
        last_price=Decimal("0.54"),
        volume=None,
        volume_24h=None,
        open_interest=None,
        liquidity=None,
        retrieved_at=RUN_AT - timedelta(minutes=2),
    )
    forecast = BaseForecastRecord(
        id=FORECAST_ID,
        sports_event_id=EVENT_ID,
        model_version_id=MODEL_ID,
        purpose="operational",
        home_team_id=HOME_ID,
        away_team_id=AWAY_ID,
        home_win_probability=Decimal("0.640000"),
        away_win_probability=Decimal("0.360000"),
        home_team_rating=Decimal("1510"),
        away_team_rating=Decimal("1490"),
        adjusted_rating_difference=Decimal("120"),
        training_data_fingerprint="b" * 64,
        input_fingerprint="c" * 64,
        input_features={
            "source_event_fingerprint": source_event_fingerprint(
                event_id=event.id,
                scheduled_start_time=event.scheduled_start_time,
                home_team_id=event.home_team_id,
                away_team_id=event.away_team_id,
                event_status=event.status,
            )
        },
        training_games_seen=10,
        training_games_processed=10,
        skipped_tied_games=0,
        skipped_incomplete_games=0,
        home_prior_games=5,
        away_prior_games=5,
        latest_training_event_time=RUN_AT - timedelta(days=1),
        forecast_as_of=RUN_AT - timedelta(minutes=10),
        source_event_last_seen_at=event.last_seen_at,
        generated_at=RUN_AT - timedelta(minutes=10),
    )
    return OpportunitySourceBundle(
        market=market,
        match=match,
        price=price,
        event=event,
        forecast=forecast,
    )


def _run(repository: FakeOpportunityRepository) -> OpportunityRunResult:
    service = OpportunityDetectionService(
        repository=cast(OpportunityRepository, repository),
        policy=OpportunityPolicy(),
        clock=lambda: RUN_AT,
    )
    return asyncio.run(
        service.run(
            start_date=RUN_AT.date(),
            end_date=RUN_AT.date(),
            market_id=None,
            limit=100,
            offset=0,
        )
    )


def test_run_generates_separate_yes_and_no_from_direct_asks() -> None:
    repository = FakeOpportunityRepository([source_bundle()])

    result = _run(repository)

    assert result.examined == 1
    assert result.generated == 2
    assert result.persisted == 2
    assert result.status_counts == {"ignore": 1, "trade_candidate": 1}
    yes, no = repository.decisions
    assert (yes.direction.value, yes.market_probability, yes.raw_edge) == (
        "yes",
        Decimal("0.55"),
        Decimal("0.090000"),
    )
    assert (no.direction.value, no.market_probability, no.raw_edge) == (
        "no",
        Decimal("0.47"),
        Decimal("-0.110000"),
    )
    price_snapshot = cast(dict[str, object], yes.source_snapshot["price"])
    assert price_snapshot["yes_bid"] == "0.53"


def test_stale_newest_price_skips_instead_of_falling_back() -> None:
    bundle = source_bundle()
    assert bundle.price is not None
    bundle.price.retrieved_at = RUN_AT - timedelta(minutes=16)
    repository = FakeOpportunityRepository([bundle])

    result = _run(repository)

    assert result.generated == 0
    assert result.skip_counts == {"stale_market_price": 1}
    assert repository.decisions == []


def test_invalid_complement_book_and_ineligible_latest_match_are_audited() -> None:
    invalid_book = source_bundle()
    assert invalid_book.price is not None
    invalid_book.price.no_ask = Decimal("0.40")
    ineligible = source_bundle()
    assert ineligible.match is not None
    ineligible.match.automatic_trading_eligible = False
    ineligible.market.id = UUID("20000000-0000-0000-0000-000000000001")
    repository = FakeOpportunityRepository([invalid_book, ineligible])

    result = _run(repository)

    assert result.generated == 0
    assert result.skip_counts == {
        "invalid_market_book": 1,
        "latest_match_not_eligible": 1,
    }


def test_boundary_or_missing_asks_skip_only_affected_direction() -> None:
    bundle = source_bundle()
    assert bundle.price is not None
    bundle.price.yes_ask = Decimal("1")
    bundle.price.no_bid = Decimal("0")
    repository = FakeOpportunityRepository([bundle])

    result = _run(repository)

    assert result.generated == 1
    assert result.yes_generated == 0
    assert result.no_generated == 1
    assert result.skip_counts == {"non_actionable_yes_ask": 1}


def test_unchanged_event_refresh_does_not_invalidate_forecast() -> None:
    bundle = source_bundle()
    assert bundle.event is not None and bundle.forecast is not None
    bundle.event.last_seen_at = bundle.forecast.source_event_last_seen_at + timedelta(seconds=1)
    repository = FakeOpportunityRepository([bundle])

    result = _run(repository)

    assert result.generated == 2
    assert result.skip_counts == {}


def test_semantically_changed_event_requires_forecast_regeneration() -> None:
    bundle = source_bundle()
    assert bundle.event is not None
    bundle.event.scheduled_start_time += timedelta(minutes=1)
    repository = FakeOpportunityRepository([bundle])

    result = _run(repository)

    assert result.skip_counts == {"event_changed_since_forecast": 1}
