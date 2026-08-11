from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter

from app.domain.opportunities import (
    OpportunityDirection,
    OpportunityPriceSource,
    OpportunityStatus,
)
from app.models.opportunities import OpportunityRecord
from app.schemas.forecasts import ModelVersionResponse

_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JsonValue])


class OpportunityResponse(BaseModel):
    """One immutable directional market-versus-model comparison."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    market_id: UUID
    market_price_id: UUID
    market_event_match_id: UUID
    sports_event_id: UUID
    base_forecast_id: UUID
    outcome_team_id: UUID
    yes_team_id: UUID
    no_team_id: UUID
    direction: OpportunityDirection
    price_source: OpportunityPriceSource
    mapping_method: str
    orientation_fingerprint: str
    market_probability: Decimal
    model_probability: Decimal
    raw_edge: Decimal
    status: OpportunityStatus
    status_reason: str
    strategy_name: str
    strategy_version: str
    watch_min_raw_edge: Decimal
    trade_candidate_min_raw_edge: Decimal
    max_market_price_age_seconds: int
    max_operational_forecast_age_seconds: int
    policy_fingerprint: str
    input_fingerprint: str
    source_snapshot: dict[str, JsonValue]
    price_retrieved_at: datetime
    forecast_generated_at: datetime
    price_age_seconds: int
    forecast_age_seconds: int
    valid_until: datetime
    evaluated_at: datetime
    model: ModelVersionResponse

    @classmethod
    def from_record(cls, record: OpportunityRecord) -> OpportunityResponse:
        return cls(
            id=record.id,
            market_id=record.market_id,
            market_price_id=record.market_price_id,
            market_event_match_id=record.market_event_match_id,
            sports_event_id=record.sports_event_id,
            base_forecast_id=record.base_forecast_id,
            outcome_team_id=record.outcome_team_id,
            yes_team_id=record.yes_team_id,
            no_team_id=record.no_team_id,
            direction=OpportunityDirection(record.direction),
            price_source=OpportunityPriceSource(record.price_source),
            mapping_method=record.mapping_method,
            orientation_fingerprint=record.orientation_fingerprint,
            market_probability=record.market_probability,
            model_probability=record.model_probability,
            raw_edge=record.raw_edge,
            status=OpportunityStatus(record.status),
            status_reason=record.status_reason,
            strategy_name=record.strategy_name,
            strategy_version=record.strategy_version,
            watch_min_raw_edge=record.watch_min_raw_edge,
            trade_candidate_min_raw_edge=record.trade_candidate_min_raw_edge,
            max_market_price_age_seconds=record.max_market_price_age_seconds,
            max_operational_forecast_age_seconds=(record.max_operational_forecast_age_seconds),
            policy_fingerprint=record.policy_fingerprint,
            input_fingerprint=record.input_fingerprint,
            source_snapshot=_JSON_OBJECT_ADAPTER.validate_python(record.source_snapshot),
            price_retrieved_at=record.price_retrieved_at,
            forecast_generated_at=record.forecast_generated_at,
            price_age_seconds=record.price_age_seconds,
            forecast_age_seconds=record.forecast_age_seconds,
            valid_until=record.valid_until,
            evaluated_at=record.evaluated_at,
            model=ModelVersionResponse.from_record(record.model_version),
        )


class OpportunityRunResponse(BaseModel):
    """Counts and skip reasons from a bounded opportunity run."""

    model_config = ConfigDict(frozen=True)

    strategy_name: str
    strategy_version: str
    forecast_model_name: str
    forecast_model_version: str
    start_date: date
    end_date: date
    examined: int
    generated: int
    persisted: int
    yes_generated: int
    no_generated: int
    status_counts: dict[str, int]
    skip_counts: dict[str, int]
