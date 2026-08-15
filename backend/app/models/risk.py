from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.portfolio import PositionSizeProposalRecord


class RiskDecisionRecord(Base):
    """Append-only deterministic risk authorization evidence."""

    __tablename__ = "risk_decisions"
    __table_args__ = (
        UniqueConstraint(
            "position_size_proposal_id",
            "risk_policy_version",
            "input_fingerprint",
            name="uq_risk_decisions_semantic_input",
        ),
        CheckConstraint("execution_mode = 'paper'", name="ck_risk_decisions_paper_only"),
        CheckConstraint("direction IN ('yes', 'no')", name="ck_risk_decisions_direction"),
        CheckConstraint(
            "decision IN ('reject', 'auto_approve', 'require_human_approval')",
            name="ck_risk_decisions_decision",
        ),
        CheckConstraint(
            "escalation_band IN ('hard_rejection', 'automatic', "
            "'medium_confidence_unavailable', 'large_exposure')",
            name="ck_risk_decisions_escalation_band",
        ),
        CheckConstraint(
            "confidence_basis = 'not_available' "
            "AND adjusted_edge_basis = 'not_available' "
            "AND liquidity_basis = 'not_evaluated_phase7' "
            "AND edge_basis = 'raw_edge'",
            name="ck_risk_decisions_evidence_bases",
        ),
        CheckConstraint(
            "proposed_capital > 0 AND proposal_available_bankroll > 0 "
            "AND current_available_bankroll >= 0 "
            "AND current_authorized_capital >= 0",
            name="ck_risk_decisions_capital",
        ),
        CheckConstraint(
            "proposed_exposure_fraction > 0 AND proposed_exposure_fraction <= 1 "
            "AND recomputed_exposure_fraction >= 0 "
            "AND recomputed_exposure_fraction <= 1",
            name="ck_risk_decisions_exposure",
        ),
        CheckConstraint(
            "auto_approve_exposure_max > 0 "
            "AND auto_approve_exposure_max < high_confidence_auto_approve_max "
            "AND high_confidence_auto_approve_max <= 1",
            name="ck_risk_decisions_policy_exposure",
        ),
        CheckConstraint(
            "min_raw_edge >= 0 AND min_raw_edge <= 1 "
            "AND min_match_confidence >= 0 AND min_match_confidence <= 1 "
            "AND max_market_price_age_seconds > 0 "
            "AND max_operational_forecast_age_seconds > 0 "
            "AND authorization_ttl_seconds > 0",
            name="ck_risk_decisions_policy_limits",
        ),
        CheckConstraint(
            "reference_price > 0 AND reference_price < 1 "
            "AND model_probability >= 0 AND model_probability <= 1 "
            "AND raw_edge >= -1 AND raw_edge <= 1",
            name="ck_risk_decisions_probability_values",
        ),
        CheckConstraint(
            "match_confidence >= 0 AND match_confidence <= 1",
            name="ck_risk_decisions_match_confidence",
        ),
        CheckConstraint(
            "hard_failure_count >= 0 "
            "AND hard_failure_count = jsonb_array_length(failed_rules) "
            "AND jsonb_array_length(check_results) > 0",
            name="ck_risk_decisions_check_counts",
        ),
        CheckConstraint(
            "(decision = 'reject' AND all_required_checks_passed = false "
            "AND hard_failure_count > 0 AND authorization_valid_until IS NULL) OR "
            "(decision = 'auto_approve' AND all_required_checks_passed = true "
            "AND hard_failure_count = 0 "
            "AND proposed_exposure_fraction < auto_approve_exposure_max "
            "AND authorization_valid_until IS NOT NULL) OR "
            "(decision = 'require_human_approval' "
            "AND all_required_checks_passed = true AND hard_failure_count = 0 "
            "AND proposed_exposure_fraction >= auto_approve_exposure_max "
            "AND authorization_valid_until IS NOT NULL)",
            name="ck_risk_decisions_outcome_consistency",
        ),
        CheckConstraint(
            "authorization_valid_until IS NULL OR authorization_valid_until >= evaluated_at",
            name="ck_risk_decisions_validity",
        ),
        CheckConstraint(
            "length(risk_policy_fingerprint) = 64 "
            "AND length(proposal_input_fingerprint) = 64 "
            "AND length(opportunity_input_fingerprint) = 64 "
            "AND length(input_fingerprint) = 64",
            name="ck_risk_decisions_fingerprints",
        ),
        Index(
            "ix_risk_decisions_proposal_evaluated",
            "position_size_proposal_id",
            "evaluated_at",
        ),
        Index("ix_risk_decisions_portfolio_evaluated", "portfolio_id", "evaluated_at"),
        Index("ix_risk_decisions_market_evaluated", "market_id", "evaluated_at"),
        Index("ix_risk_decisions_decision_evaluated", "decision", "evaluated_at"),
        Index(
            "ix_risk_decisions_active_intent",
            "portfolio_id",
            "market_id",
            "direction",
            "outcome_team_id",
            "authorization_valid_until",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    position_size_proposal_id: Mapped[UUID] = mapped_column(
        ForeignKey("position_size_proposals.id", ondelete="RESTRICT"), nullable=False
    )
    portfolio_id: Mapped[UUID] = mapped_column(
        ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False
    )
    portfolio_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("portfolio_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    opportunity_id: Mapped[UUID] = mapped_column(
        ForeignKey("opportunities.id", ondelete="RESTRICT"), nullable=False
    )
    market_id: Mapped[UUID] = mapped_column(
        ForeignKey("markets.id", ondelete="RESTRICT"), nullable=False
    )
    outcome_team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    market_event_match_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_event_matches.id", ondelete="RESTRICT"), nullable=False
    )
    market_price_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_prices.id", ondelete="RESTRICT"), nullable=False
    )
    base_forecast_id: Mapped[UUID] = mapped_column(
        ForeignKey("base_forecasts.id", ondelete="RESTRICT"), nullable=False
    )
    execution_mode: Mapped[str] = mapped_column(String(10), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    decision: Mapped[str] = mapped_column(String(40), nullable=False)
    escalation_band: Mapped[str] = mapped_column(String(50), nullable=False)
    primary_reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    all_required_checks_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    hard_failure_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_rules: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    check_results: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    proposed_capital: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    proposal_available_bankroll: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    current_available_bankroll: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    current_authorized_capital: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    remaining_authorizable_bankroll: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    proposed_exposure_fraction: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    recomputed_exposure_fraction: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    reference_price: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    model_probability: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    raw_edge: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    edge_basis: Mapped[str] = mapped_column(String(30), nullable=False)
    adjusted_edge_basis: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence_basis: Mapped[str] = mapped_column(String(30), nullable=False)
    liquidity_basis: Mapped[str] = mapped_column(String(40), nullable=False)
    match_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    market_price_age_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    forecast_age_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_policy_name: Mapped[str] = mapped_column(String(50), nullable=False)
    risk_policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    risk_policy_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    auto_approve_exposure_max: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    high_confidence_auto_approve_max: Mapped[Decimal] = mapped_column(
        Numeric(12, 10), nullable=False
    )
    min_raw_edge: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    min_match_confidence: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    max_market_price_age_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    max_operational_forecast_age_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    authorization_ttl_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    proposal_strategy_name: Mapped[str] = mapped_column(String(50), nullable=False)
    proposal_strategy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    proposal_input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    opportunity_input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    authorization_valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    audit_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)

    proposal: Mapped[PositionSizeProposalRecord] = relationship(lazy="joined")
