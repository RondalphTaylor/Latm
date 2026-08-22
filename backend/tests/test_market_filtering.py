from __future__ import annotations

from datetime import UTC, datetime

from app.domain.markets import MarketOutcome, OutcomeSide, PredictionMarket
from app.domain.sports import SportsLeague
from app.services.markets.filtering import classify_sports_market, is_likely_nba_market


def prediction_market(
    *,
    title: str,
    category: str | None = "Sports",
    series_ticker: str | None = None,
    event_ticker: str | None = None,
    product_metadata: dict[str, str] | None = None,
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
        raw_data={"event": {"product_metadata": product_metadata or {}}},
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


def test_exact_official_mlb_game_series_is_classified_reproducibly() -> None:
    market = prediction_market(
        title="Milwaukee wins",
        series_ticker="KXMLBGAME",
        event_ticker="KXMLBGAME-26AUG23ATLMIL",
        product_metadata={"competition": "Pro Baseball", "competition_scope": "Game"},
    )

    classification = classify_sports_market(market)

    assert classification is not None
    assert classification.league is SportsLeague.MLB
    assert classification.sports_market_type.value == "single_game_winner"
    assert len(classification.fingerprint) == 64
    assert classification == classify_sports_market(market)


def test_mlb_props_and_incomplete_metadata_fail_closed() -> None:
    prop = prediction_market(
        title="Milwaukee wins by over 1.5 runs",
        series_ticker="KXMLBSPREAD",
        event_ticker="KXMLBSPREAD-1",
        product_metadata={"competition": "Pro Baseball", "competition_scope": "Game"},
    )
    missing_scope = prediction_market(
        title="Milwaukee wins",
        series_ticker="KXMLBGAME",
        event_ticker="KXMLBGAME-1",
        product_metadata={"competition": "Pro Baseball"},
    )

    assert classify_sports_market(prop) is None
    assert classify_sports_market(missing_scope) is None
