from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NflPaperPreflightRecord(Base):
    """Immutable, cost-aware NFL review fact that cannot authorize execution."""

    __tablename__ = "nfl_paper_preflights"
    __table_args__ = (
        CheckConstraint(
            "execution_mode = 'paper' AND promotion_state = 'blocked' AND risk_decision = 'reject' AND NOT execution_enabled",
            name="ck_nfl_paper_preflight_safety",
        ),
        CheckConstraint(
            "direction IN ('yes', 'no') AND sizing_status IN ('cost_qualified', 'cost_disqualified', 'ineligible')",
            name="ck_nfl_paper_preflight_state",
        ),
        CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$' AND policy_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_nfl_paper_preflight_identity",
        ),
        CheckConstraint(
            "capital_cap > 0 AND quantity >= 0 AND gross_cost >= 0 AND estimated_fee >= 0 AND total_cost = gross_cost + estimated_fee AND total_cost <= capital_cap",
            name="ck_nfl_paper_preflight_costs",
        ),
        CheckConstraint(
            "(quantity = 0 AND effective_unit_cost IS NULL AND adjusted_edge IS NULL) OR (quantity > 0 AND execution_price > 0 AND execution_price < 1 AND effective_unit_cost > 0 AND effective_unit_cost < 1 AND adjusted_edge = round(expected_payout - effective_unit_cost, 6))",
            name="ck_nfl_paper_preflight_math",
        ),
        CheckConstraint("jsonb_typeof(audit) = 'object'", name="ck_nfl_paper_preflight_audit"),
        Index("ix_nfl_paper_preflights_reviewed", "reviewed_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    opportunity_id: Mapped[UUID] = mapped_column(
        ForeignKey("nfl_paper_opportunities.id", ondelete="RESTRICT"), nullable=False
    )
    market_id: Mapped[UUID] = mapped_column(
        ForeignKey("markets.id", ondelete="RESTRICT"), nullable=False
    )
    direction: Mapped[str] = mapped_column(String(3), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    capital_cap: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    expected_payout: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    direct_ask: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    raw_edge: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    execution_price: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    quantity: Mapped[int] = mapped_column(nullable=False)
    gross_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    estimated_fee: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    effective_unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    adjusted_edge: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    sizing_status: Mapped[str] = mapped_column(String(30), nullable=False)
    risk_decision: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(100), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(10), nullable=False)
    promotion_state: Mapped[str] = mapped_column(String(20), nullable=False)
    execution_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    audit: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
