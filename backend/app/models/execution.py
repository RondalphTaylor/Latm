from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PaperTradeRecord(Base):
    """Immutable terminal paper-entry attempt consuming one risk decision."""

    __tablename__ = "trades"
    __table_args__ = (
        UniqueConstraint("risk_decision_id", name="uq_trades_risk_decision"),
        CheckConstraint("execution_mode = 'paper'", name="ck_trades_paper_only"),
        CheckConstraint("action = 'buy'", name="ck_trades_entry_only"),
        CheckConstraint("direction IN ('yes', 'no')", name="ck_trades_direction"),
        CheckConstraint("status IN ('filled', 'rejected')", name="ck_trades_status"),
        CheckConstraint(
            "(status = 'filled' AND portfolio_snapshot_after_id IS NOT NULL "
            "AND execution_price IS NOT NULL "
            "AND slippage_amount_per_contract IS NOT NULL "
            "AND requested_quantity >= 1 "
            "AND executed_quantity >= 1 AND gross_cost IS NOT NULL "
            "AND reference_gross_cost IS NOT NULL AND slippage_cost IS NOT NULL "
            "AND fee_amount IS NOT NULL AND total_cost IS NOT NULL "
            "AND unused_capital IS NOT NULL AND effective_unit_cost IS NOT NULL "
            "AND adjusted_edge IS NOT NULL AND mark_price IS NOT NULL "
            "AND mark_basis IS NOT NULL AND market_value IS NOT NULL "
            "AND unrealized_pnl IS NOT NULL AND executed_at IS NOT NULL "
            "AND jsonb_array_length(failed_rules) = 0) OR "
            "(status = 'rejected' AND portfolio_snapshot_after_id IS NULL "
            "AND execution_price IS NULL "
            "AND slippage_amount_per_contract IS NULL "
            "AND requested_quantity IS NULL "
            "AND executed_quantity IS NULL AND gross_cost IS NULL "
            "AND reference_gross_cost IS NULL AND slippage_cost IS NULL "
            "AND fee_amount IS NULL AND total_cost IS NULL "
            "AND unused_capital IS NULL AND effective_unit_cost IS NULL "
            "AND adjusted_edge IS NULL AND mark_price IS NULL "
            "AND mark_basis IS NULL AND market_value IS NULL "
            "AND unrealized_pnl IS NULL AND executed_at IS NULL "
            "AND jsonb_array_length(failed_rules) > 0)",
            name="ck_trades_terminal_state",
        ),
        CheckConstraint(
            "proposed_capital > 0 AND reference_price > 0 AND reference_price < 1 "
            "AND slippage_bps >= 0 AND fee_bps >= 0",
            name="ck_trades_input_values",
        ),
        CheckConstraint(
            "mark_basis IS NULL OR mark_basis IN ('directional_bid', 'directional_ask_fallback')",
            name="ck_trades_mark_basis",
        ),
        CheckConstraint(
            "status = 'rejected' OR (execution_price > 0 AND execution_price < 1 "
            "AND reference_gross_cost >= 0 AND gross_cost >= 0 "
            "AND slippage_cost >= 0 "
            "AND gross_cost = reference_gross_cost + slippage_cost "
            "AND fee_amount >= 0 AND total_cost = gross_cost + fee_amount "
            "AND total_cost <= proposed_capital "
            "AND unused_capital = proposed_capital - total_cost "
            "AND market_value >= 0 "
            "AND unrealized_pnl = market_value - total_cost)",
            name="ck_trades_fill_accounting",
        ),
        CheckConstraint(
            "length(execution_policy_fingerprint) = 64 "
            "AND length(risk_input_fingerprint) = 64 "
            "AND length(input_fingerprint) = 64",
            name="ck_trades_fingerprints",
        ),
        Index("ix_trades_portfolio_attempted", "portfolio_id", "attempted_at"),
        Index("ix_trades_market_attempted", "market_id", "attempted_at"),
        Index("ix_trades_status_attempted", "status", "attempted_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    risk_decision_id: Mapped[UUID] = mapped_column(
        ForeignKey("risk_decisions.id", ondelete="RESTRICT"), nullable=False
    )
    position_size_proposal_id: Mapped[UUID] = mapped_column(
        ForeignKey("position_size_proposals.id", ondelete="RESTRICT"), nullable=False
    )
    portfolio_id: Mapped[UUID] = mapped_column(
        ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False
    )
    portfolio_snapshot_before_id: Mapped[UUID] = mapped_column(
        ForeignKey("portfolio_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    portfolio_snapshot_after_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("portfolio_snapshots.id", ondelete="RESTRICT")
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
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    failed_rules: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    check_results: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    proposed_capital: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    reference_price: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    execution_price: Mapped[Decimal | None] = mapped_column(Numeric(7, 6))
    slippage_bps: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    slippage_amount_per_contract: Mapped[Decimal | None] = mapped_column(Numeric(7, 6))
    requested_quantity: Mapped[int | None] = mapped_column(Integer)
    executed_quantity: Mapped[int | None] = mapped_column(Integer)
    reference_gross_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    gross_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    slippage_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    fee_bps: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    fee_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    total_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    unused_capital: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    effective_unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    model_probability: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    raw_edge: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    adjusted_edge: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    mark_price: Mapped[Decimal | None] = mapped_column(Numeric(7, 6))
    mark_basis: Mapped[str | None] = mapped_column(String(40))
    market_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    unrealized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    sizing_strategy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    risk_policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    execution_policy_name: Mapped[str] = mapped_column(String(50), nullable=False)
    execution_policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    execution_policy_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    audit_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)


class PaperPositionRecord(Base):
    """Entry-only open paper position created from exactly one filled trade."""

    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("opening_trade_id", name="uq_positions_opening_trade"),
        CheckConstraint("execution_mode = 'paper'", name="ck_positions_paper_only"),
        CheckConstraint("direction IN ('yes', 'no')", name="ck_positions_direction"),
        CheckConstraint("status = 'open'", name="ck_positions_status"),
        CheckConstraint("quantity >= 1", name="ck_positions_quantity"),
        CheckConstraint(
            "average_entry_price > 0 AND average_entry_price < 1 "
            "AND mark_price >= 0 AND mark_price < 1",
            name="ck_positions_prices",
        ),
        CheckConstraint(
            "mark_basis IN ('directional_bid', 'directional_ask_fallback')",
            name="ck_positions_mark_basis",
        ),
        CheckConstraint(
            "gross_cost_basis >= 0 AND entry_fees >= 0 "
            "AND total_cost_basis = gross_cost_basis + entry_fees "
            "AND market_value >= 0 "
            "AND unrealized_pnl = market_value - total_cost_basis "
            "AND realized_pnl = 0",
            name="ck_positions_accounting",
        ),
        CheckConstraint("length(input_fingerprint) = 64", name="ck_positions_fingerprint"),
        Index(
            "uq_positions_open_portfolio_market",
            "portfolio_id",
            "market_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_positions_market_opened", "market_id", "opened_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    opening_trade_id: Mapped[UUID] = mapped_column(
        ForeignKey("trades.id", ondelete="RESTRICT"), nullable=False
    )
    portfolio_id: Mapped[UUID] = mapped_column(
        ForeignKey("portfolios.id", ondelete="RESTRICT"), nullable=False
    )
    market_id: Mapped[UUID] = mapped_column(
        ForeignKey("markets.id", ondelete="RESTRICT"), nullable=False
    )
    outcome_team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    market_price_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_prices.id", ondelete="RESTRICT"), nullable=False
    )
    execution_mode: Mapped[str] = mapped_column(String(10), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    average_entry_price: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    gross_cost_basis: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    entry_fees: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_cost_basis: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    mark_price: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    mark_basis: Mapped[str] = mapped_column(String(40), nullable=False)
    market_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
