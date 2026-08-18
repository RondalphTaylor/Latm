from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.opportunities import OpportunityRecord


class PortfolioRecord(Base):
    """Paper-only portfolio with immutable starting capital."""

    __tablename__ = "portfolios"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_portfolios_idempotency_key"),
        UniqueConstraint("name", name="uq_portfolios_name"),
        CheckConstraint("execution_mode = 'paper'", name="ck_portfolios_paper_only"),
        CheckConstraint("currency = 'USD'", name="ck_portfolios_currency"),
        CheckConstraint("starting_bankroll > 0", name="ck_portfolios_starting_bankroll"),
        CheckConstraint("status = 'active'", name="ck_portfolios_status"),
        CheckConstraint(
            "length(creation_fingerprint) = 64",
            name="ck_portfolios_creation_fingerprint",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(10), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    starting_bankroll: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    creation_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PortfolioSnapshotRecord(Base):
    """Append-only authoritative portfolio accounting state."""

    __tablename__ = "portfolio_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "portfolio_id",
            "sequence",
            name="uq_portfolio_snapshots_sequence",
        ),
        UniqueConstraint(
            "id",
            "portfolio_id",
            name="uq_portfolio_snapshots_id_portfolio",
        ),
        CheckConstraint("sequence >= 0", name="ck_portfolio_snapshots_sequence"),
        CheckConstraint("execution_mode = 'paper'", name="ck_portfolio_snapshots_paper_only"),
        CheckConstraint("currency = 'USD'", name="ck_portfolio_snapshots_currency"),
        CheckConstraint(
            "starting_bankroll > 0 AND current_bankroll >= 0 "
            "AND cash_balance >= 0 AND reserved_capital >= 0 "
            "AND committed_capital >= 0 AND available_bankroll >= 0",
            name="ck_portfolio_snapshots_nonnegative_balances",
        ),
        CheckConstraint(
            "current_bankroll = starting_bankroll + realized_pnl",
            name="ck_portfolio_snapshots_current_bankroll",
        ),
        CheckConstraint(
            "cash_balance = current_bankroll - committed_capital",
            name="ck_portfolio_snapshots_cash_balance",
        ),
        CheckConstraint(
            "available_bankroll = cash_balance - reserved_capital",
            name="ck_portfolio_snapshots_available_bankroll",
        ),
        CheckConstraint(
            "open_position_value = committed_capital + unrealized_pnl",
            name="ck_portfolio_snapshots_open_position_value",
        ),
        CheckConstraint(
            "total_portfolio_value = cash_balance + open_position_value",
            name="ck_portfolio_snapshots_total_portfolio_value",
        ),
        CheckConstraint(
            "committed_capital + reserved_capital <= current_bankroll",
            name="ck_portfolio_snapshots_total_capital",
        ),
        CheckConstraint(
            "reason IN ('created', 'paper_entry_filled')",
            name="ck_portfolio_snapshots_reason",
        ),
        CheckConstraint(
            "(reason <> 'created') OR (sequence = 0 "
            "AND current_bankroll = starting_bankroll "
            "AND cash_balance = starting_bankroll "
            "AND available_bankroll = starting_bankroll "
            "AND reserved_capital = 0 AND committed_capital = 0 AND realized_pnl = 0 "
            "AND open_position_value = 0 AND unrealized_pnl = 0 "
            "AND total_portfolio_value = starting_bankroll "
            "AND previous_snapshot_id IS NULL)",
            name="ck_portfolio_snapshots_created_state",
        ),
        CheckConstraint(
            "length(state_fingerprint) = 64",
            name="ck_portfolio_snapshots_state_fingerprint",
        ),
        Index("ix_portfolio_snapshots_portfolio_captured", "portfolio_id", "captured_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    portfolio_id: Mapped[UUID] = mapped_column(
        ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(10), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    starting_bankroll: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    current_bankroll: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    cash_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    reserved_capital: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    committed_capital: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    available_bankroll: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    open_position_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_portfolio_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    previous_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("portfolio_snapshots.id", ondelete="RESTRICT"), nullable=True
    )
    reason: Mapped[str] = mapped_column(String(30), nullable=False)
    state_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PositionSizeProposalRecord(Base):
    """Advisory capital allocation awaiting a future risk decision."""

    __tablename__ = "position_size_proposals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["portfolio_snapshot_id", "portfolio_id"],
            ["portfolio_snapshots.id", "portfolio_snapshots.portfolio_id"],
            ondelete="RESTRICT",
            name="fk_position_size_proposals_snapshot_portfolio",
        ),
        UniqueConstraint(
            "portfolio_snapshot_id",
            "opportunity_id",
            "strategy_version",
            "input_fingerprint",
            name="uq_position_size_proposals_semantic_input",
        ),
        CheckConstraint("execution_mode = 'paper'", name="ck_position_size_proposals_paper_only"),
        CheckConstraint("direction IN ('yes', 'no')", name="ck_position_size_proposals_direction"),
        CheckConstraint(
            "state = 'awaiting_risk'",
            name="ck_position_size_proposals_state",
        ),
        CheckConstraint(
            "confidence_basis = 'not_available'",
            name="ck_position_size_proposals_confidence",
        ),
        CheckConstraint(
            "reference_price > 0 AND reference_price < 1 "
            "AND model_probability >= 0 AND model_probability <= 1",
            name="ck_position_size_proposals_probabilities",
        ),
        CheckConstraint(
            "raw_edge >= 0 AND raw_edge <= 1 AND raw_edge = model_probability - reference_price",
            name="ck_position_size_proposals_raw_edge",
        ),
        CheckConstraint(
            "available_bankroll > 0 AND proposed_capital > 0 "
            "AND proposed_capital <= available_bankroll",
            name="ck_position_size_proposals_capital",
        ),
        CheckConstraint(
            "target_exposure_fraction > 0 "
            "AND proposed_exposure_fraction > 0 "
            "AND proposed_exposure_fraction <= target_exposure_fraction "
            "AND target_exposure_fraction <= max_exposure_fraction "
            "AND max_exposure_fraction <= 1",
            name="ck_position_size_proposals_exposure",
        ),
        CheckConstraint(
            "proposed_exposure_fraction = trunc(proposed_capital / available_bankroll, 10)",
            name="ck_position_size_proposals_actual_exposure",
        ),
        CheckConstraint(
            "candidate_min_raw_edge < strong_min_raw_edge "
            "AND strong_min_raw_edge < very_strong_min_raw_edge",
            name="ck_position_size_proposals_edge_bands",
        ),
        CheckConstraint(
            "candidate_exposure_fraction < strong_exposure_fraction "
            "AND strong_exposure_fraction < very_strong_exposure_fraction "
            "AND very_strong_exposure_fraction <= max_exposure_fraction",
            name="ck_position_size_proposals_exposure_bands",
        ),
        CheckConstraint(
            "length(policy_fingerprint) = 64 "
            "AND length(input_fingerprint) = 64 "
            "AND length(opportunity_input_fingerprint) = 64",
            name="ck_position_size_proposals_fingerprints",
        ),
        CheckConstraint(
            "opportunity_evaluated_at <= proposed_at AND proposed_at <= opportunity_valid_until",
            name="ck_position_size_proposals_times",
        ),
        Index(
            "ix_position_size_proposals_portfolio_proposed",
            "portfolio_id",
            "proposed_at",
        ),
        Index("ix_position_size_proposals_opportunity", "opportunity_id"),
        Index(
            "ix_position_size_proposals_state_proposed",
            "state",
            "proposed_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    portfolio_id: Mapped[UUID] = mapped_column(nullable=False)
    portfolio_snapshot_id: Mapped[UUID] = mapped_column(nullable=False)
    opportunity_id: Mapped[UUID] = mapped_column(
        ForeignKey("opportunities.id", ondelete="RESTRICT"), nullable=False
    )
    market_id: Mapped[UUID] = mapped_column(
        ForeignKey("markets.id", ondelete="RESTRICT"), nullable=False
    )
    outcome_team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    execution_mode: Mapped[str] = mapped_column(String(10), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence_basis: Mapped[str] = mapped_column(String(30), nullable=False)
    reference_price: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    model_probability: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    raw_edge: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    available_bankroll: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    target_exposure_fraction: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    proposed_exposure_fraction: Mapped[Decimal] = mapped_column(Numeric(12, 10), nullable=False)
    proposed_capital: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(50), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    candidate_min_raw_edge: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    strong_min_raw_edge: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    very_strong_min_raw_edge: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    candidate_exposure_fraction: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    strong_exposure_fraction: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    very_strong_exposure_fraction: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    max_exposure_fraction: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    policy_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    opportunity_strategy_name: Mapped[str] = mapped_column(String(50), nullable=False)
    opportunity_strategy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    opportunity_input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    opportunity_evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    opportunity_valid_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    proposed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    audit_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)

    opportunity: Mapped[OpportunityRecord] = relationship(lazy="joined")
