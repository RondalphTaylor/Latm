from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NflPaperOpportunityRecord(Base):
    """Immutable direct-ask comparison; never an executable trading opportunity."""

    __tablename__ = "nfl_paper_opportunities"
    __table_args__ = (
        CheckConstraint(
            "execution_mode = 'paper' AND promotion_state = 'blocked' AND NOT operational_eligible AND NOT trading_enabled AND NOT costs_included AND NOT depth_verified",
            name="ck_nfl_paper_opp_safety",
        ),
        CheckConstraint(
            "yes_expected_payout BETWEEN 0 AND 1 AND no_expected_payout BETWEEN 0 AND 1 AND yes_expected_payout + no_expected_payout = 1",
            name="ck_nfl_paper_opp_payouts",
        ),
        CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$' AND policy_fingerprint ~ '^[0-9a-f]{64}$' AND input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_nfl_paper_opp_identity",
        ),
        CheckConstraint(
            "(yes_status = 'ineligible' AND no_status = 'ineligible' AND valid_until IS NULL) OR (valid_until > evaluated_at AND price_id IS NOT NULL AND price_retrieved_at <= evaluated_at AND price_retrieved_at IS NOT NULL)",
            name="ck_nfl_paper_opp_times",
        ),
        CheckConstraint("jsonb_typeof(audit) = 'object'", name="ck_nfl_paper_opp_audit"),
        CheckConstraint(
            "(yes_direct_ask IS NULL OR yes_direct_ask BETWEEN 0 AND 1) AND ((yes_status = 'ineligible' AND yes_raw_edge IS NULL) OR (yes_status IN ('ignore','watch','paper_candidate') AND yes_direct_ask > 0 AND yes_direct_ask < 1 AND yes_raw_edge IS NOT NULL AND yes_raw_edge = round(yes_expected_payout - yes_direct_ask, 6)))",
            name="ck_nfl_paper_opp_yes",
        ),
        CheckConstraint(
            "(no_direct_ask IS NULL OR no_direct_ask BETWEEN 0 AND 1) AND ((no_status = 'ineligible' AND no_raw_edge IS NULL) OR (no_status IN ('ignore','watch','paper_candidate') AND no_direct_ask > 0 AND no_direct_ask < 1 AND no_raw_edge IS NOT NULL AND no_raw_edge = round(no_expected_payout - no_direct_ask, 6)))",
            name="ck_nfl_paper_opp_no",
        ),
        Index("ix_nfl_paper_opp_evaluated", "evaluated_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    forecast_id: Mapped[UUID] = mapped_column(
        ForeignKey("nfl_payout_forecasts.id", ondelete="RESTRICT"), nullable=False
    )
    market_id: Mapped[UUID] = mapped_column(
        ForeignKey("markets.id", ondelete="RESTRICT"), nullable=False
    )
    match_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_event_matches.id", ondelete="RESTRICT"), nullable=False
    )
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("sports_events.id", ondelete="RESTRICT"), nullable=False
    )
    price_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("market_prices.id", ondelete="RESTRICT"), nullable=True
    )
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    price_retrieved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    yes_expected_payout: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    no_expected_payout: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    yes_direct_ask: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    no_direct_ask: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    yes_raw_edge: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)
    no_raw_edge: Mapped[Decimal | None] = mapped_column(Numeric(8, 6), nullable=True)
    yes_status: Mapped[str] = mapped_column(String(100), nullable=False)
    no_status: Mapped[str] = mapped_column(String(100), nullable=False)
    yes_reason: Mapped[str] = mapped_column(String(100), nullable=False)
    no_reason: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_fingerprint: Mapped[str] = mapped_column(String(100), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(100), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(100), nullable=False)
    promotion_state: Mapped[str] = mapped_column(String(100), nullable=False)
    operational_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    trading_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    costs_included: Mapped[bool] = mapped_column(Boolean, nullable=False)
    depth_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    audit: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
