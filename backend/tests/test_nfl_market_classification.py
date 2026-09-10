from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from app.domain.markets import MarketOutcome, MarketStatusFilter, OutcomeSide, PredictionMarket
from app.domain.sports import SportsLeague
from app.schemas.markets import MarketIngestionResponse
from app.services.markets.filtering import (
    NFL_CLASSIFICATION_VERSION,
    classify_sports_market,
    is_likely_nba_market,
    supported_series_ticker,
)
from app.services.markets.ingestion import IngestionResult, MarketIngestionService
from app.services.markets.repository import MarketRepository


def nfl_market(**updates: object) -> PredictionMarket:
    event_id = "KXNFLGAME-26SEP10SFLAR"
    market = PredictionMarket(
        provider_name="kalshi",
        provider_market_id=f"{event_id}-LAR",
        provider_event_id=event_id,
        series_ticker="KXNFLGAME",
        category="Sports",
        market_type="binary",
        title="San Francisco vs Los Angeles R Pro Football game: Los Angeles R wins?",
        subtitle="Los Angeles R",
        status="open",
        outcomes=(
            MarketOutcome(provider_outcome_id="yes", side=OutcomeSide.YES, label="Los Angeles R"),
            MarketOutcome(provider_outcome_id="no", side=OutcomeSide.NO, label="Los Angeles R"),
        ),
        raw_data={
            "event": {
                "event_ticker": event_id,
                "series_ticker": "KXNFLGAME",
                "product_metadata": {"competition": "Pro Football", "competition_scope": "Game"},
            },
            "market": {"ticker": f"{event_id}-LAR", "event_ticker": event_id},
        },
        retrieved_at=datetime(2026, 9, 10, tzinfo=UTC),
    )
    return market.model_copy(update=updates)


def test_nfl_classification_is_versioned_shape_not_trading_approval() -> None:
    market = nfl_market()
    result = classify_sports_market(market)
    assert result is not None
    assert result.league is SportsLeague.NFL
    assert result.version == NFL_CLASSIFICATION_VERSION
    assert result.sports_market_type.value == "single_game_winner"
    assert result == classify_sports_market(market)
    assert market.rules_primary is None  # Classification does not claim rule eligibility.
    assert supported_series_ticker(SportsLeague.NFL) == "KXNFLGAME"


def test_official_nfl_series_cannot_enter_nba_heuristic_filter() -> None:
    assert not is_likely_nba_market(nfl_market(title="DAL vs PHI: Dallas wins?"))


@pytest.mark.parametrize(
    "title",
    [
        "Los Angeles R wins by 3.5 points?",
        "Los Angeles R first half winner?",
        "Los Angeles R 1Q winner?",
        "Los Angeles R Q4 winner?",
        "Los Angeles R winning both halves?",
        "Los Angeles R regulation winner?",
        "Los Angeles R touchdown total?",
        "Los Angeles R passing yards?",
        "Los Angeles R over 20 points?",
        "Los Angeles R season winner?",
        "Los Angeles R Super Bowl winner?",
        "Los Angeles R division winner?",
        "Los Angeles R first period winner?",
        "Will the weather be warm?",
    ],
)
def test_incompatible_shape_rejected_despite_official_series(title: str) -> None:
    assert classify_sports_market(nfl_market(title=title)) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"series_ticker": "KXNFLSPREAD"},
        {"series_ticker": "KXNFLTOTAL"},
        {"series_ticker": "KXNFLGAMEEXTRA"},
        {"provider_event_id": "KXNBAGAME-26SEP10SFLAR"},
        {"provider_market_id": "KXNFLGAME-26SEP11SFLAR-LAR"},
        {"provider_market_id": "KXNFLGAME-26SEP10SFLAR-LAR-SPREAD"},
        {"market_type": "scalar"},
        {"provider_name": "other"},
        {"category": "Politics"},
        {"subtitle": "First quarter"},
    ],
)
def test_mixed_and_unsupported_identifiers_rejected(changes: dict[str, object]) -> None:
    assert classify_sports_market(nfl_market(**changes)) is None


@pytest.mark.parametrize(
    "event",
    [
        {"product_metadata": {"competition": "College Football", "competition_scope": "Game"}},
        {"product_metadata": {"competition": "Pro Football", "competition_scope": "Season"}},
        {"product_metadata": {"competition": "Pro Football"}},
        {
            "event_ticker": "KXNBAGAME-123",
            "product_metadata": {"competition": "Pro Football", "competition_scope": "Game"},
        },
        {
            "series_ticker": "KXNFLSPREAD",
            "product_metadata": {"competition": "Pro Football", "competition_scope": "Game"},
        },
    ],
)
def test_raw_metadata_conflicts_rejected(event: dict[str, object]) -> None:
    assert classify_sports_market(nfl_market(raw_data={"event": event})) is None


def test_raw_partial_game_title_cannot_hide_behind_normalized_title() -> None:
    market = nfl_market()
    raw = dict(market.raw_data)
    raw["market"] = {"title": "First half winner"}
    assert classify_sports_market(market.model_copy(update={"raw_data": raw})) is None


@pytest.mark.parametrize(
    "league,series,competition",
    [
        (SportsLeague.NBA, "KXNBAGAME", None),
        (SportsLeague.MLB, "KXMLBGAME", "Pro Baseball"),
    ],
)
def test_existing_classification_fingerprints_unchanged(
    league: SportsLeague, series: str, competition: str | None
) -> None:
    market = nfl_market(
        series_ticker=series,
        provider_event_id=f"{series}-1",
        raw_data={
            "event": {"product_metadata": {"competition": competition, "competition_scope": "Game"}}
        },
    )
    result = classify_sports_market(market)
    assert result is not None
    payload = {
        "provider_name": "kalshi",
        "provider_market_id": market.provider_market_id,
        "provider_event_id": market.provider_event_id,
        "series_ticker": series,
        "category": "Sports",
        "market_type": "binary",
        "competition": competition,
        "competition_scope": "Game",
        "sports_market_type": "single_game_winner",
        "method": "official_series_metadata",
        "version": "kalshi-official-series-v1",
    }
    assert result.league is league
    assert (
        result.fingerprint
        == hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


class NflProvider:
    name = "kalshi"

    def __init__(self) -> None:
        self.series: str | None = None

    async def list_markets(
        self, *, status: MarketStatusFilter | None = None, series_ticker: str | None = None
    ) -> list[PredictionMarket]:
        self.series = series_ticker
        return [nfl_market(), nfl_market(title="First half winner?")]

    async def get_market(self, provider_market_id: str) -> PredictionMarket:
        return nfl_market()


class CapturingRepository(MarketRepository):
    def __init__(self) -> None:
        self.markets: list[PredictionMarket] = []

    async def upsert_markets(self, markets: Sequence[PredictionMarket]) -> int:
        self.markets = list(markets)
        return len(self.markets)


def test_nfl_ingestion_requests_series_and_persists_only_classified_candidates() -> None:
    provider = NflProvider()
    repository = CapturingRepository()
    result = asyncio.run(
        MarketIngestionService(provider=provider, repository=repository).ingest(
            league=SportsLeague.NFL
        )
    )
    assert provider.series == "KXNFLGAME"
    assert result.fetched == 2
    assert result.nfl_markets == result.persisted == 1
    assert result.nba_markets == result.mlb_markets == 0
    assert len(repository.markets) == 1
    assert MarketIngestionResponse.model_validate(result.model_dump()).nfl_markets == 1


def test_nfl_count_defaults_to_zero_for_legacy_callers() -> None:
    values = {
        "provider": "kalshi",
        "fetched": 0,
        "nba_markets": 0,
        "mlb_markets": 0,
        "selected_league": None,
        "persisted": 0,
    }
    assert IngestionResult.model_validate(values).nfl_markets == 0
    assert MarketIngestionResponse.model_validate(values).nfl_markets == 0
