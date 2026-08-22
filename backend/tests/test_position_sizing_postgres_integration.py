from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.domain.forecasts import EloConfiguration
from app.domain.portfolio import PositionSizingPolicy
from app.domain.risk import RiskDecisionType, RiskPolicy
from app.models.forecasts import BaseForecastRecord, ModelVersionRecord
from app.models.markets import (
    MarketOutcomeRecord,
    MarketPriceRecord,
    PredictionMarketRecord,
    Provider,
)
from app.models.matching import MarketEventMatchRecord
from app.models.sports import SportsEventRecord, TeamRecord
from app.services.forecasting.elo import (
    ELO_FORMULA,
    configuration_fingerprint,
    effective_model_version,
    source_event_fingerprint,
)
from app.services.forecasting.repository import model_version_record_id
from app.services.opportunities.repository import OpportunityRepository
from app.services.opportunities.service import OpportunityDetectionService
from app.services.position_sizing.engine import RulesPositionSizer
from app.services.position_sizing.repository import PositionSizingRepository
from app.services.position_sizing.service import PaperPortfolioService, PositionSizingService
from app.services.risk.repository import RiskRepository
from app.services.risk.service import RiskService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION_TESTS") != "1",
    reason="set RUN_DATABASE_INTEGRATION_TESTS=1 against a migrated test database",
)

NOW = datetime(2026, 8, 11, 16, tzinfo=UTC)
PORTFOLIO_IDEMPOTENCY_KEY = "phase6-integration-portfolio"
MARKET_ID = UUID("a0000000-0000-0000-0000-000000000001")
PRICE_ID = UUID("a0000000-0000-0000-0000-000000000002")
NEW_PRICE_ID = UUID("a0000000-0000-0000-0000-000000000003")
MATCH_ID = UUID("a0000000-0000-0000-0000-000000000004")
EVENT_ID = UUID("a0000000-0000-0000-0000-000000000005")
FORECAST_ID = UUID("a0000000-0000-0000-0000-000000000006")
HOME_ID = UUID("a0000000-0000-0000-0000-000000000007")
AWAY_ID = UUID("a0000000-0000-0000-0000-000000000008")


def _team(team_id: UUID, provider_id: str, abbreviation: str, city: str, name: str) -> TeamRecord:
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
        first_seen_at=NOW - timedelta(days=1),
        last_seen_at=NOW - timedelta(minutes=20),
    )


def _price(price_id: UUID, retrieved_at: datetime, yes_ask: str) -> MarketPriceRecord:
    ask = Decimal(yes_ask)
    return MarketPriceRecord(
        id=price_id,
        market_id=MARKET_ID,
        yes_bid=ask - Decimal("0.02"),
        yes_ask=ask,
        no_bid=Decimal("1") - ask,
        no_ask=Decimal("1.02") - ask,
        last_price=ask - Decimal("0.01"),
        volume=Decimal("100"),
        volume_24h=Decimal("25"),
        open_interest=Decimal("50"),
        liquidity=None,
        retrieved_at=retrieved_at,
    )


async def _seed_sources(session: AsyncSession) -> None:
    await session.execute(
        insert(Provider)
        .values(
            [
                {"name": "kalshi", "display_name": "Kalshi", "is_read_only": True},
                {
                    "name": "balldontlie",
                    "display_name": "BALLDONTLIE",
                    "is_read_only": True,
                },
            ]
        )
        .on_conflict_do_nothing(index_elements=[Provider.name])
    )
    configuration = EloConfiguration()
    model_version = effective_model_version(configuration)
    model_id = model_version_record_id("nba_elo", model_version)
    event_last_seen = NOW - timedelta(minutes=20)
    market = PredictionMarketRecord(
        id=MARKET_ID,
        provider_name="kalshi",
        provider_market_id="phase6-market",
        provider_event_id="phase6-event",
        series_ticker="NBA-GAME",
        category="Sports",
        market_type="binary",
        title="Will the Boston Celtics win?",
        subtitle="BOS vs NYK",
        rules_primary=None,
        rules_secondary=None,
        status="active",
        is_nba=True,
        open_time=NOW - timedelta(days=1),
        close_time=NOW + timedelta(hours=2),
        occurrence_time=NOW + timedelta(hours=2),
        provider_created_at=None,
        provider_updated_at=None,
        raw_data={},
        first_seen_at=NOW - timedelta(days=1),
        last_seen_at=NOW,
    )
    market.outcomes = [
        MarketOutcomeRecord(
            id=UUID("a0000000-0000-0000-0000-000000000009"),
            market_id=MARKET_ID,
            provider_outcome_id="yes",
            side="yes",
            label="Boston Celtics",
        ),
        MarketOutcomeRecord(
            id=UUID("a0000000-0000-0000-0000-000000000010"),
            market_id=MARKET_ID,
            provider_outcome_id="no",
            side="no",
            label="New York Knicks",
        ),
    ]
    session.add_all(
        [
            _team(HOME_ID, "phase6-bos", "BOS", "Boston", "Celtics"),
            _team(AWAY_ID, "phase6-nyk", "NYK", "New York", "Knicks"),
            SportsEventRecord(
                id=EVENT_ID,
                provider_name="balldontlie",
                provider_event_id="phase6-game",
                league="nba",
                season=2026,
                event_date=NOW.date(),
                scheduled_start_time=NOW + timedelta(hours=2),
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
                first_seen_at=NOW - timedelta(days=1),
                last_seen_at=event_last_seen,
            ),
            market,
            ModelVersionRecord(
                id=model_id,
                model_name="nba_elo",
                model_version=model_version,
                algorithm="elo",
                configuration=configuration.model_dump(mode="json"),
                configuration_fingerprint=configuration_fingerprint(configuration),
                formula=ELO_FORMULA,
                description="fixture",
                created_at=NOW - timedelta(minutes=10),
            ),
        ]
    )
    await session.flush()
    session.add_all(
        [
            MarketEventMatchRecord(
                id=MATCH_ID,
                market_id=MARKET_ID,
                league="nba",
                sports_event_id=EVENT_ID,
                status="matched",
                confidence=Decimal("0.9900"),
                method="fixture",
                reason="fixture",
                matcher_version="deterministic-team-time-v1",
                min_confidence=Decimal("0.9000"),
                ambiguity_margin=Decimal("0.1000"),
                time_window_hours=36,
                automatic_trading_eligible=True,
                input_fingerprint="a" * 64,
                team_signals=[],
                candidate_scores=[],
                evidence={},
                evaluated_at=NOW - timedelta(minutes=20),
            ),
            _price(PRICE_ID, NOW - timedelta(minutes=2), "0.55"),
            BaseForecastRecord(
                id=FORECAST_ID,
                sports_event_id=EVENT_ID,
                model_version_id=model_id,
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
                        event_id=EVENT_ID,
                        scheduled_start_time=NOW + timedelta(hours=2),
                        home_team_id=HOME_ID,
                        away_team_id=AWAY_ID,
                        event_status="scheduled",
                    )
                },
                training_games_seen=10,
                training_games_processed=10,
                skipped_tied_games=0,
                skipped_incomplete_games=0,
                home_prior_games=5,
                away_prior_games=5,
                latest_training_event_time=NOW - timedelta(days=1),
                forecast_as_of=NOW - timedelta(minutes=10),
                source_event_last_seen_at=event_last_seen,
                generated_at=NOW - timedelta(minutes=10),
            ),
        ]
    )
    await session.commit()


async def _run_integration() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.connect() as connection:
        outer_transaction = await connection.begin()
        try:
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as session:
                await _seed_sources(session)
                opportunity_repository = OpportunityRepository(session)
                opportunity_run = await OpportunityDetectionService(
                    repository=opportunity_repository,
                    clock=lambda: NOW,
                ).run(
                    start_date=NOW.date(),
                    end_date=NOW.date(),
                    market_id=MARKET_ID,
                    limit=10,
                    offset=0,
                )
                candidates = await opportunity_repository.list_opportunities(
                    latest_only=True,
                    current_only=True,
                    current_at=NOW,
                    status=None,
                    direction=None,
                    market_id=MARKET_ID,
                    sports_event_id=None,
                    model_name=None,
                    model_version=None,
                    opportunity_id=None,
                    limit=10,
                    offset=0,
                )
                candidate = next(item for item in candidates if item.status == "trade_candidate")

                repository = PositionSizingRepository(session)
                portfolio_service = PaperPortfolioService(
                    repository=repository,
                    default_starting_bankroll=Decimal("1000.00"),
                    clock=lambda: NOW,
                )
                portfolio, created = await portfolio_service.create(
                    idempotency_key=PORTFOLIO_IDEMPOTENCY_KEY,
                    name="Phase 6 Integration Portfolio",
                    starting_bankroll=None,
                )
                _, identical_portfolio = await portfolio_service.create(
                    idempotency_key=PORTFOLIO_IDEMPOTENCY_KEY,
                    name="Phase 6 Integration Portfolio",
                    starting_bankroll=None,
                )
                sizing_service = PositionSizingService(
                    repository=repository,
                    clock=lambda: NOW,
                )
                first = await sizing_service.run(
                    portfolio_id=portfolio.portfolio.id,
                    opportunity_id=candidate.id,
                    limit=10,
                    offset=0,
                )
                identical = await sizing_service.run(
                    portfolio_id=portfolio.portfolio.id,
                    opportunity_id=candidate.id,
                    limit=10,
                    offset=0,
                )
                proposals_before_policy_change = await repository.list_proposals(
                    portfolio_id=portfolio.portfolio.id,
                    opportunity_id=candidate.id,
                    market_id=None,
                    direction=None,
                    strategy_version=None,
                    limit=10,
                    offset=0,
                )
                first_proposal = proposals_before_policy_change[0]
                risk_repository = RiskRepository(session)
                risk_service = RiskService(
                    repository=risk_repository,
                    policy=RiskPolicy(),
                    runtime_trading_mode="paper",
                    active_sizing_strategy_version=(
                        RulesPositionSizer(PositionSizingPolicy()).strategy_version
                    ),
                    clock=lambda: NOW,
                )
                first_risk = await risk_service.run(
                    proposal_id=first_proposal.id,
                    portfolio_id=None,
                    limit=10,
                    offset=0,
                )
                identical_risk = await risk_service.run(
                    proposal_id=first_proposal.id,
                    portfolio_id=None,
                    limit=10,
                    offset=0,
                )
                changed_policy = await PositionSizingService(
                    repository=repository,
                    policy=PositionSizingPolicy(candidate_exposure_fraction=Decimal("0.030000")),
                    clock=lambda: NOW + timedelta(seconds=1),
                ).run(
                    portfolio_id=portfolio.portfolio.id,
                    opportunity_id=candidate.id,
                    limit=10,
                    offset=0,
                )
                proposals_after_policy_change = await repository.list_proposals(
                    portfolio_id=portfolio.portfolio.id,
                    opportunity_id=candidate.id,
                    market_id=None,
                    direction=None,
                    strategy_version=None,
                    limit=10,
                    offset=0,
                )
                changed_proposal = next(
                    item for item in proposals_after_policy_change if item.id != first_proposal.id
                )
                duplicate_risk = await risk_service.run(
                    proposal_id=changed_proposal.id,
                    portfolio_id=None,
                    limit=10,
                    offset=0,
                )
                session.add(_price(NEW_PRICE_ID, NOW + timedelta(minutes=1), "0.54"))
                await session.commit()
                stale_risk = await RiskService(
                    repository=risk_repository,
                    policy=RiskPolicy(),
                    runtime_trading_mode="paper",
                    active_sizing_strategy_version=(
                        RulesPositionSizer(PositionSizingPolicy()).strategy_version
                    ),
                    clock=lambda: NOW + timedelta(minutes=2),
                ).run(
                    proposal_id=first_proposal.id,
                    portfolio_id=None,
                    limit=10,
                    offset=0,
                )
                invalidated = await PositionSizingService(
                    repository=repository,
                    clock=lambda: NOW + timedelta(minutes=2),
                ).run(
                    portfolio_id=portfolio.portfolio.id,
                    opportunity_id=candidate.id,
                    limit=10,
                    offset=0,
                )
                proposals = await repository.list_proposals(
                    portfolio_id=portfolio.portfolio.id,
                    opportunity_id=None,
                    market_id=None,
                    direction=None,
                    strategy_version=None,
                    limit=10,
                    offset=0,
                )
                snapshots = await repository.list_portfolio_snapshots(
                    portfolio_id=portfolio.portfolio.id,
                    limit=10,
                    offset=0,
                )
                current_portfolio = await repository.get_portfolio(portfolio.portfolio.id)
                risk_history = await risk_repository.list_decisions(
                    latest_only=False,
                    unexpired_only=False,
                    current_at=NOW + timedelta(minutes=2),
                    proposal_id=None,
                    portfolio_id=portfolio.portfolio.id,
                    market_id=None,
                    decision=None,
                    risk_policy_version=None,
                    limit=10,
                    offset=0,
                )

                assert opportunity_run.persisted == 2
                assert created.created is True
                assert identical_portfolio.created is False
                assert first.persisted == 1
                assert identical.persisted == 0
                assert first_risk.decision_counts == {"auto_approve": 1}
                assert first_risk.persisted == 1
                assert identical_risk.persisted == 0
                assert changed_policy.persisted == 1
                assert duplicate_risk.decision_counts == {"reject": 1}
                assert stale_risk.decision_counts == {"reject": 1}
                assert invalidated.generated == 0
                assert invalidated.skip_counts == {"opportunity_not_current_trade_candidate": 1}
                assert len(proposals) == 2
                assert {item.proposed_capital for item in proposals} == {
                    Decimal("20.00"),
                    Decimal("30.00"),
                }
                assert {item.state for item in proposals} == {"awaiting_risk"}
                assert len(snapshots) == 1
                assert len(risk_history) == 3
                assert {item.decision for item in risk_history} == {
                    RiskDecisionType.AUTO_APPROVE.value,
                    RiskDecisionType.REJECT.value,
                }
                stale_decision = risk_history[0]
                assert "current_trade_candidate" in stale_decision.failed_rules
                assert "current_market_price" in stale_decision.failed_rules
                assert current_portfolio is not None
                assert current_portfolio.snapshot.available_bankroll == Decimal("1000.00")
                assert current_portfolio.snapshot.reserved_capital == Decimal("0.00")
                assert current_portfolio.snapshot.committed_capital == Decimal("0.00")
        finally:
            await outer_transaction.rollback()
    await engine.dispose()


def test_postgres_portfolio_sizing_idempotence_history_and_currentness() -> None:
    asyncio.run(_run_integration())
