from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.domain.forecasts import EloConfiguration
from app.domain.opportunities import (
    OpportunityDecision,
    OpportunityDirection,
    OpportunityEvaluationInput,
    OpportunityOutcomeInput,
    OpportunityPolicy,
    OpportunityPriceSource,
    OpportunityTeamInput,
)
from app.models.forecasts import BaseForecastRecord
from app.models.markets import MarketPriceRecord, PredictionMarketRecord
from app.models.matching import MarketEventMatchRecord
from app.models.sports import SportsEventRecord, TeamRecord
from app.services.forecasting.elo import effective_model_version, source_event_fingerprint
from app.services.opportunities.engine import RawEdgeOpportunityEngine
from app.services.opportunities.orientation import resolve_outcome_orientation
from app.services.opportunities.repository import (
    OpportunityRepository,
    OpportunitySourceBundle,
)

_MAX_RUN_RANGE_DAYS = 31
_BOOK_TOLERANCE = Decimal("0.0001")


class OpportunityRunResult(BaseModel):
    """Auditable counts from one bounded local opportunity run."""

    model_config = ConfigDict(frozen=True)

    strategy_name: str
    strategy_version: str
    forecast_model_name: str
    forecast_model_version: str
    start_date: date
    end_date: date
    examined: int = Field(ge=0)
    generated: int = Field(ge=0)
    persisted: int = Field(ge=0)
    yes_generated: int = Field(ge=0)
    no_generated: int = Field(ge=0)
    status_counts: dict[str, int]
    skip_counts: dict[str, int]


class OpportunityDetectionService:
    """Generate research-only raw-edge classifications from local snapshots."""

    def __init__(
        self,
        *,
        repository: OpportunityRepository,
        policy: OpportunityPolicy | None = None,
        forecast_configuration: EloConfiguration | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._policy = policy or OpportunityPolicy()
        self._forecast_configuration = forecast_configuration or EloConfiguration()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._engine = RawEdgeOpportunityEngine(self._policy)

    async def run(
        self,
        *,
        start_date: date,
        end_date: date,
        market_id: UUID | None,
        limit: int,
        offset: int,
    ) -> OpportunityRunResult:
        """Compare newest eligible local evidence without provider or trading calls."""
        self._validate_date_range(start_date, end_date)
        run_at = self._clock()
        if run_at.tzinfo is None or run_at.utcoffset() is None:
            raise ValueError("opportunity clock must return a timezone-aware datetime")
        forecast_version = effective_model_version(self._forecast_configuration)
        bundles = await self._repository.list_source_bundles(
            start_date=start_date,
            end_date=end_date,
            market_id=market_id,
            model_name=self._policy.forecast_model_name,
            model_version=forecast_version,
            limit=limit,
            offset=offset,
        )
        skips: Counter[str] = Counter()
        decisions: list[OpportunityDecision] = []
        for bundle in bundles:
            inputs = self._evaluation_inputs(bundle, run_at=run_at, skips=skips)
            decisions.extend(self._engine.evaluate(source) for source in inputs)
        persisted = await self._repository.persist_opportunities(decisions)
        statuses = Counter(decision.status.value for decision in decisions)
        directions = Counter(decision.direction.value for decision in decisions)
        return OpportunityRunResult(
            strategy_name=self._policy.strategy_name,
            strategy_version=self._engine.strategy_version,
            forecast_model_name=self._policy.forecast_model_name,
            forecast_model_version=forecast_version,
            start_date=start_date,
            end_date=end_date,
            examined=len(bundles),
            generated=len(decisions),
            persisted=persisted,
            yes_generated=directions[OpportunityDirection.YES.value],
            no_generated=directions[OpportunityDirection.NO.value],
            status_counts=dict(sorted(statuses.items())),
            skip_counts=dict(sorted(skips.items())),
        )

    def _evaluation_inputs(
        self,
        bundle: OpportunitySourceBundle,
        *,
        run_at: datetime,
        skips: Counter[str],
    ) -> tuple[OpportunityEvaluationInput, ...]:
        market, match, price, event, forecast = (
            bundle.market,
            bundle.match,
            bundle.price,
            bundle.event,
            bundle.forecast,
        )
        skip = self._bundle_skip_reason(bundle, run_at=run_at)
        if skip is not None:
            skips[skip] += 1
            return ()
        assert (
            match is not None and price is not None and event is not None and forecast is not None
        )

        orientation = resolve_outcome_orientation(
            home_team=self._team_input(event.home_team),
            away_team=self._team_input(event.away_team),
            outcomes=tuple(
                OpportunityOutcomeInput(id=outcome.id, side=outcome.side, label=outcome.label)
                for outcome in market.outcomes
            ),
            market_title=market.title,
            market_type=market.market_type,
        )
        if orientation is None:
            skips["unresolved_outcome_orientation"] += 1
            return ()

        valid_until = min(
            price.retrieved_at + timedelta(seconds=self._policy.max_market_price_age_seconds),
            forecast.generated_at
            + timedelta(seconds=self._policy.max_operational_forecast_age_seconds),
            event.scheduled_start_time,
            market.close_time or event.scheduled_start_time,
        )
        if valid_until < run_at:
            skips["expired_inputs"] += 1
            return ()
        snapshot = self._source_snapshot(
            market=market,
            match=match,
            price=price,
            event=event,
            forecast=forecast,
            orientation=orientation.model_dump(mode="json"),
        )
        probabilities = {
            event.home_team_id: forecast.home_win_probability,
            event.away_team_id: forecast.away_win_probability,
        }
        sides = (
            (
                OpportunityDirection.YES,
                OpportunityPriceSource.DIRECT_YES_ASK,
                price.yes_ask,
                orientation.yes_team_id,
            ),
            (
                OpportunityDirection.NO,
                OpportunityPriceSource.DIRECT_NO_ASK,
                price.no_ask,
                orientation.no_team_id,
            ),
        )
        inputs: list[OpportunityEvaluationInput] = []
        for direction, price_source, ask, team_id in sides:
            if ask is None:
                skips[f"missing_{direction.value}_ask"] += 1
                continue
            if ask <= 0 or ask >= 1:
                skips[f"non_actionable_{direction.value}_ask"] += 1
                continue
            inputs.append(
                OpportunityEvaluationInput(
                    market_id=market.id,
                    market_price_id=price.id,
                    market_event_match_id=match.id,
                    sports_event_id=event.id,
                    base_forecast_id=forecast.id,
                    model_version_id=forecast.model_version_id,
                    outcome_team_id=team_id,
                    yes_team_id=orientation.yes_team_id,
                    no_team_id=orientation.no_team_id,
                    direction=direction,
                    price_source=price_source,
                    mapping_method=orientation.mapping_method,
                    orientation_fingerprint=orientation.input_fingerprint,
                    match_input_fingerprint=match.input_fingerprint,
                    forecast_input_fingerprint=forecast.input_fingerprint,
                    market_probability=ask,
                    model_probability=probabilities[team_id],
                    price_retrieved_at=price.retrieved_at,
                    forecast_generated_at=forecast.generated_at,
                    valid_until=valid_until,
                    evaluated_at=run_at,
                    source_snapshot=snapshot,
                )
            )
        return tuple(inputs)

    def _bundle_skip_reason(
        self, bundle: OpportunitySourceBundle, *, run_at: datetime
    ) -> str | None:
        market, match, price, event, forecast = (
            bundle.market,
            bundle.match,
            bundle.price,
            bundle.event,
            bundle.forecast,
        )
        if market.status.lower() not in {"active", "open"}:
            return "market_not_active"
        if market.close_time is not None and market.close_time <= run_at:
            return "market_closed"
        if match is None:
            return "missing_event_match"
        if (
            match.status != "matched"
            or not match.automatic_trading_eligible
            or match.sports_event_id is None
        ):
            return "latest_match_not_eligible"
        if event is None:
            return "missing_sports_event"
        if event.status != "scheduled" or event.postponed or event.scheduled_start_time <= run_at:
            return "event_not_upcoming"
        if price is None:
            return "missing_market_price"
        if price.retrieved_at > run_at:
            return "future_market_price"
        if (
            run_at - price.retrieved_at
        ).total_seconds() > self._policy.max_market_price_age_seconds:
            return "stale_market_price"
        if not self._valid_book(price):
            return "invalid_market_book"
        if forecast is None:
            return "missing_current_operational_forecast"
        if forecast.generated_at > run_at:
            return "future_operational_forecast"
        if (
            run_at - forecast.generated_at
        ).total_seconds() > self._policy.max_operational_forecast_age_seconds:
            return "stale_operational_forecast"
        if forecast.sports_event_id != event.id or {
            forecast.home_team_id,
            forecast.away_team_id,
        } != {event.home_team_id, event.away_team_id}:
            return "forecast_event_mismatch"
        persisted_event_fingerprint = forecast.input_features.get("source_event_fingerprint")
        current_event_fingerprint = source_event_fingerprint(
            event_id=event.id,
            scheduled_start_time=event.scheduled_start_time,
            home_team_id=event.home_team_id,
            away_team_id=event.away_team_id,
            event_status=event.status,
        )
        if persisted_event_fingerprint != current_event_fingerprint:
            return "event_changed_since_forecast"
        return None

    @staticmethod
    def _valid_book(price: MarketPriceRecord) -> bool:
        quoted = (price.yes_bid, price.yes_ask, price.no_bid, price.no_ask, price.last_price)
        if any(value is not None and (value < 0 or value > 1) for value in quoted):
            return False
        if (
            price.yes_bid is not None
            and price.yes_ask is not None
            and price.yes_bid > price.yes_ask
        ):
            return False
        if price.no_bid is not None and price.no_ask is not None and price.no_bid > price.no_ask:
            return False
        if (
            price.yes_bid is not None
            and price.no_ask is not None
            and abs(price.yes_bid + price.no_ask - Decimal("1")) > _BOOK_TOLERANCE
        ):
            return False
        return not (
            price.yes_ask is not None
            and price.no_bid is not None
            and abs(price.yes_ask + price.no_bid - Decimal("1")) > _BOOK_TOLERANCE
        )

    @staticmethod
    def _team_input(record: TeamRecord) -> OpportunityTeamInput:
        return OpportunityTeamInput(
            id=record.id,
            abbreviation=record.abbreviation,
            city=record.city,
            name=record.name,
            full_name=record.full_name,
        )

    @staticmethod
    def _source_snapshot(
        *,
        market: PredictionMarketRecord,
        match: MarketEventMatchRecord,
        price: MarketPriceRecord,
        event: SportsEventRecord,
        forecast: BaseForecastRecord,
        orientation: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        return {
            "market": {
                "id": str(market.id),
                "title": market.title,
                "market_type": market.market_type,
                "status": market.status,
                "outcomes": [
                    {"id": str(item.id), "side": item.side, "label": item.label}
                    for item in sorted(market.outcomes, key=lambda item: (item.side, str(item.id)))
                ],
            },
            "match": {"id": str(match.id), "input_fingerprint": match.input_fingerprint},
            "event": {
                "id": str(event.id),
                "status": event.status,
                "scheduled_start_time": event.scheduled_start_time.isoformat(),
                "home_team_id": str(event.home_team_id),
                "away_team_id": str(event.away_team_id),
                "last_seen_at": event.last_seen_at.isoformat(),
            },
            "price": {
                "id": str(price.id),
                "yes_bid": str(price.yes_bid) if price.yes_bid is not None else None,
                "yes_ask": str(price.yes_ask) if price.yes_ask is not None else None,
                "no_bid": str(price.no_bid) if price.no_bid is not None else None,
                "no_ask": str(price.no_ask) if price.no_ask is not None else None,
                "last_price": str(price.last_price) if price.last_price is not None else None,
                "retrieved_at": price.retrieved_at.isoformat(),
            },
            "forecast": {
                "id": str(forecast.id),
                "model_version_id": str(forecast.model_version_id),
                "home_win_probability": str(forecast.home_win_probability),
                "away_win_probability": str(forecast.away_win_probability),
                "input_fingerprint": forecast.input_fingerprint,
                "generated_at": forecast.generated_at.isoformat(),
            },
            "orientation": orientation,
        }

    @staticmethod
    def _validate_date_range(start_date: date, end_date: date) -> None:
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        if (end_date - start_date).days + 1 > _MAX_RUN_RANGE_DAYS:
            raise ValueError(f"opportunity date range cannot exceed {_MAX_RUN_RANGE_DAYS} days")
