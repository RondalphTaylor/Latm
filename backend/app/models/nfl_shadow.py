from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NflShadowForecastRecord(Base):
    """Immutable research-only NFL payout estimate, never an operational forecast."""

    __tablename__ = "nfl_shadow_forecasts"
    __table_args__ = (
        CheckConstraint(
            "research_only = true AND trading_enabled = false", name="ck_nfl_shadow_safety"
        ),
        CheckConstraint(
            "expected_home_payout BETWEEN 0 AND 1 AND expected_away_payout BETWEEN 0 AND 1 "
            "AND expected_home_payout + expected_away_payout = 1 "
            "AND expected_yes_payout BETWEEN 0 AND 1 AND expected_no_payout BETWEEN 0 AND 1 "
            "AND expected_yes_payout + expected_no_payout = 1",
            name="ck_nfl_shadow_payouts",
        ),
        CheckConstraint(
            "target_source_last_seen_at <= generated_at AND generated_at < scheduled_start_time",
            name="ck_nfl_shadow_pregame",
        ),
        CheckConstraint(
            "seed_fingerprint ~ '^[0-9a-f]{64}$' AND input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_nfl_shadow_fingerprints",
        ),
        CheckConstraint("jsonb_typeof(audit) = 'object'", name="ck_nfl_shadow_audit"),
        Index("ix_nfl_shadow_event_generated", "sports_event_id", "generated_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    match_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_event_matches.id", ondelete="RESTRICT")
    )
    market_id: Mapped[UUID] = mapped_column(ForeignKey("markets.id", ondelete="RESTRICT"))
    sports_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("sports_events.id", ondelete="RESTRICT")
    )
    yes_team_id: Mapped[UUID] = mapped_column(ForeignKey("teams.id", ondelete="RESTRICT"))
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    seed_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    target_source_last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expected_home_payout: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    expected_away_payout: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    expected_yes_payout: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    expected_no_payout: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    research_only: Mapped[bool] = mapped_column(Boolean, nullable=False)
    trading_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    audit: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
