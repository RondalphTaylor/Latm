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
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NflPilotScenarioRecord(Base):
    """Frozen NFL paper experiment settings for one isolated portfolio."""

    __tablename__ = "nfl_pilot_scenarios"
    __table_args__ = (
        UniqueConstraint("portfolio_id", name="uq_nfl_pilot_scenarios_portfolio"),
        UniqueConstraint("scenario_key", name="uq_nfl_pilot_scenarios_key"),
        CheckConstraint(
            "execution_mode = 'paper' AND NOT live_trading_enabled",
            name="ck_nfl_pilot_scenarios_paper",
        ),
        CheckConstraint(
            "profile IN ('conservative', 'baseline', 'assertive')",
            name="ck_nfl_pilot_scenarios_profile",
        ),
        CheckConstraint(
            "per_entry_exposure > 0 AND per_entry_exposure < aggregate_exposure AND aggregate_exposure <= 1",
            name="ck_nfl_pilot_scenarios_exposure",
        ),
        CheckConstraint(
            "length(policy_fingerprint) = 64 AND jsonb_typeof(audit) = 'object'",
            name="ck_nfl_pilot_scenarios_audit",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    scenario_key: Mapped[str] = mapped_column(String(100), nullable=False)
    portfolio_id: Mapped[UUID] = mapped_column(
        ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False
    )
    profile: Mapped[str] = mapped_column(String(20), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(10), nullable=False)
    starting_bankroll: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    per_entry_exposure: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    aggregate_exposure: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    minimum_adjusted_edge: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    live_trading_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    audit: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)


class NflPilotEntryRecord(Base):
    """An NFL-only simulated entry; it is never a provider order or live position."""

    __tablename__ = "nfl_pilot_entries"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_nfl_pilot_entries_idempotency"),
        UniqueConstraint(
            "scenario_id", "preflight_id", name="uq_nfl_pilot_entries_scenario_preflight"
        ),
        CheckConstraint(
            "execution_mode = 'paper' AND NOT live_trading_enabled AND status = 'filled'",
            name="ck_nfl_pilot_entries_paper_only",
        ),
        CheckConstraint(
            "direction IN ('yes', 'no') AND quantity > 0", name="ck_nfl_pilot_entries_side"
        ),
        CheckConstraint(
            "total_cost > 0 AND gross_cost > 0 AND estimated_fee >= 0 AND total_cost = gross_cost + estimated_fee",
            name="ck_nfl_pilot_entries_costs",
        ),
        CheckConstraint(
            "entry_cap > 0 AND aggregate_cap > 0 AND total_cost <= entry_cap AND total_cost <= aggregate_cap",
            name="ck_nfl_pilot_entries_caps",
        ),
        CheckConstraint(
            "adjusted_edge >= minimum_adjusted_edge AND length(policy_fingerprint) = 64 AND jsonb_typeof(audit) = 'object'",
            name="ck_nfl_pilot_entries_policy",
        ),
        Index("ix_nfl_pilot_entries_scenario_entered", "scenario_id", "entered_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    scenario_id: Mapped[UUID] = mapped_column(
        ForeignKey("nfl_pilot_scenarios.id", ondelete="RESTRICT"), nullable=False
    )
    portfolio_id: Mapped[UUID] = mapped_column(
        ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False
    )
    preflight_id: Mapped[UUID] = mapped_column(
        ForeignKey("nfl_paper_preflights.id", ondelete="RESTRICT"), nullable=False
    )
    opportunity_id: Mapped[UUID] = mapped_column(
        ForeignKey("nfl_paper_opportunities.id", ondelete="RESTRICT"), nullable=False
    )
    market_id: Mapped[UUID] = mapped_column(
        ForeignKey("markets.id", ondelete="RESTRICT"), nullable=False
    )
    direction: Mapped[str] = mapped_column(String(3), nullable=False)
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[int] = mapped_column(nullable=False)
    gross_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    estimated_fee: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    adjusted_edge: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    minimum_adjusted_edge: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    entry_cap: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    aggregate_cap: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(10), nullable=False)
    live_trading_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    audit: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
