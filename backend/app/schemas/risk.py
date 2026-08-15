from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter

from app.domain.risk import (
    RiskCheckResult,
    RiskDecisionType,
    RiskEscalationBand,
)
from app.models.risk import RiskDecisionRecord

_CHECKS_ADAPTER = TypeAdapter(list[RiskCheckResult])
_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JsonValue])


class RiskRunResponse(BaseModel):
    """Counts returned by one bounded deterministic risk run."""

    model_config = ConfigDict(frozen=True)

    risk_policy_name: str
    risk_policy_version: str
    examined: int
    generated: int
    persisted: int
    decision_counts: dict[str, int]


class RiskDecisionResponse(BaseModel):
    """Historical risk authorization evidence, never an execution instruction."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    position_size_proposal_id: UUID
    portfolio_id: UUID
    portfolio_snapshot_id: UUID
    opportunity_id: UUID
    market_id: UUID
    outcome_team_id: UUID
    market_event_match_id: UUID
    market_price_id: UUID
    base_forecast_id: UUID
    execution_mode: str
    direction: str
    decision: RiskDecisionType
    escalation_band: RiskEscalationBand
    primary_reason_code: str
    reason: str
    all_required_checks_passed: bool
    hard_failure_count: int
    failed_rules: list[str]
    check_results: list[RiskCheckResult]
    proposed_capital: Decimal
    proposal_available_bankroll: Decimal
    current_available_bankroll: Decimal
    current_authorized_capital: Decimal
    remaining_authorizable_bankroll: Decimal
    proposed_exposure_fraction: Decimal
    recomputed_exposure_fraction: Decimal
    reference_price: Decimal
    model_probability: Decimal
    raw_edge: Decimal
    edge_basis: str
    adjusted_edge_basis: str
    confidence_basis: str
    liquidity_basis: str
    match_confidence: Decimal
    market_price_age_seconds: int
    forecast_age_seconds: int
    risk_policy_name: str
    risk_policy_version: str
    risk_policy_fingerprint: str
    auto_approve_exposure_max: Decimal
    high_confidence_auto_approve_max: Decimal
    min_raw_edge: Decimal
    min_match_confidence: Decimal
    max_market_price_age_seconds: int
    max_operational_forecast_age_seconds: int
    authorization_ttl_seconds: int
    proposal_strategy_name: str
    proposal_strategy_version: str
    proposal_input_fingerprint: str
    opportunity_input_fingerprint: str
    input_fingerprint: str
    evaluated_at: datetime
    authorization_valid_until: datetime | None
    audit_snapshot: dict[str, JsonValue]

    @classmethod
    def from_record(cls, record: RiskDecisionRecord) -> RiskDecisionResponse:
        return cls(
            id=record.id,
            position_size_proposal_id=record.position_size_proposal_id,
            portfolio_id=record.portfolio_id,
            portfolio_snapshot_id=record.portfolio_snapshot_id,
            opportunity_id=record.opportunity_id,
            market_id=record.market_id,
            outcome_team_id=record.outcome_team_id,
            market_event_match_id=record.market_event_match_id,
            market_price_id=record.market_price_id,
            base_forecast_id=record.base_forecast_id,
            execution_mode=record.execution_mode,
            direction=record.direction,
            decision=RiskDecisionType(record.decision),
            escalation_band=RiskEscalationBand(record.escalation_band),
            primary_reason_code=record.primary_reason_code,
            reason=record.reason,
            all_required_checks_passed=record.all_required_checks_passed,
            hard_failure_count=record.hard_failure_count,
            failed_rules=record.failed_rules,
            check_results=_CHECKS_ADAPTER.validate_python(record.check_results),
            proposed_capital=record.proposed_capital,
            proposal_available_bankroll=record.proposal_available_bankroll,
            current_available_bankroll=record.current_available_bankroll,
            current_authorized_capital=record.current_authorized_capital,
            remaining_authorizable_bankroll=record.remaining_authorizable_bankroll,
            proposed_exposure_fraction=record.proposed_exposure_fraction,
            recomputed_exposure_fraction=record.recomputed_exposure_fraction,
            reference_price=record.reference_price,
            model_probability=record.model_probability,
            raw_edge=record.raw_edge,
            edge_basis=record.edge_basis,
            adjusted_edge_basis=record.adjusted_edge_basis,
            confidence_basis=record.confidence_basis,
            liquidity_basis=record.liquidity_basis,
            match_confidence=record.match_confidence,
            market_price_age_seconds=record.market_price_age_seconds,
            forecast_age_seconds=record.forecast_age_seconds,
            risk_policy_name=record.risk_policy_name,
            risk_policy_version=record.risk_policy_version,
            risk_policy_fingerprint=record.risk_policy_fingerprint,
            auto_approve_exposure_max=record.auto_approve_exposure_max,
            high_confidence_auto_approve_max=(record.high_confidence_auto_approve_max),
            min_raw_edge=record.min_raw_edge,
            min_match_confidence=record.min_match_confidence,
            max_market_price_age_seconds=record.max_market_price_age_seconds,
            max_operational_forecast_age_seconds=(record.max_operational_forecast_age_seconds),
            authorization_ttl_seconds=record.authorization_ttl_seconds,
            proposal_strategy_name=record.proposal_strategy_name,
            proposal_strategy_version=record.proposal_strategy_version,
            proposal_input_fingerprint=record.proposal_input_fingerprint,
            opportunity_input_fingerprint=record.opportunity_input_fingerprint,
            input_fingerprint=record.input_fingerprint,
            evaluated_at=record.evaluated_at,
            authorization_valid_until=record.authorization_valid_until,
            audit_snapshot=_JSON_OBJECT_ADAPTER.validate_python(record.audit_snapshot),
        )
