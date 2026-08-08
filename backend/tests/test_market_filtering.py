from __future__ import annotations

from datetime import UTC, datetime

from app.domain.markets import MarketOutcome, OutcomeSide, PredictionMarket
from app.services.markets.filtering import is_likely_nba_market


def prediction_market(
    *,
    title: str,
    category: str | None = "Sports",
    series_ticker: str | None = None,
    event_ticker: str | None = None,
) -> PredictionMarket:
    retrieved_at = datetime(2026, 8, 1, tzinfo=UTC)
    return PredictionMarket(
        provider_name="kalshi",
        provider_market_id="TEST-MARKET",
        provider_event_id=event_ticker,
        series_ticker=series_ticker,
        category=category,
        market_type="binary",
        title=title,
        status="open",
        outcomes=(
            MarketOutcome(provider_outcome_id="yes", side=OutcomeSide.YES, label="Yes"),
            MarketOutcome(provider_outcome_id="no", side=OutcomeSide.NO, label="No"),
        ),
        raw_data={},
        retrieved_at=retrieved_at,
    )


def test_structured_nba_series_is_preferred() -> None:
    market = prediction_market(title="Game winner", series_ticker="KXNBAGAME")

    assert is_likely_nba_market(market)


def test_two_team_names_identify_nba_market() -> None:
    market = prediction_market(title="Boston Celtics at New York Knicks winner")

    assert is_likely_nba_market(market)


def test_non_sports_category_rejects_ambiguous_team_word() -> None:
    market = prediction_market(title="Will the Heat index exceed 100?", category="Climate")

    assert not is_likely_nba_market(market)


def test_unrelated_sports_market_is_not_nba() -> None:
    market = prediction_market(title="Will the Yankees defeat the Red Sox?")

    assert not is_likely_nba_market(market)
