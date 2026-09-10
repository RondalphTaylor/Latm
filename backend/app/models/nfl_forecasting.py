from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NflPayoutForecastRecord(Base):
    """Immutable unpromoted paper candidate, separate from operational forecasts."""

    __tablename__ = "nfl_payout_forecasts"
    __table_args__ = (
        CheckConstraint(
            "purpose = 'paper_candidate' AND metric_kind = 'expected_payout' AND execution_mode = 'paper' AND promotion_state = 'blocked' AND operational_eligible = false AND trading_enabled = false",
            name="ck_nfl_payout_forecast_safety",
        ),
        CheckConstraint(
            "event_source_last_seen_at <= generated_at AND market_source_last_seen_at <= generated_at AND generated_at < valid_until AND valid_until <= generated_at + interval '15 minutes' AND valid_until <= scheduled_start_time AND valid_until <= market_close_time AND valid_until <= event_source_last_seen_at + interval '24 hours' AND valid_until <= market_source_last_seen_at + interval '24 hours'",
            name="ck_nfl_payout_forecast_times",
        ),
        CheckConstraint(
            "expected_home_payout BETWEEN 0 AND 1 AND expected_away_payout BETWEEN 0 AND 1 AND expected_home_payout + expected_away_payout = 1 AND expected_yes_payout BETWEEN 0 AND 1 AND expected_no_payout BETWEEN 0 AND 1 AND expected_yes_payout + expected_no_payout = 1",
            name="ck_nfl_payout_forecast_payouts",
        ),
        CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$' AND seed_fingerprint ~ '^[0-9a-f]{64}$' AND input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_nfl_payout_forecast_identity",
        ),
        CheckConstraint("jsonb_typeof(audit) = 'object'", name="ck_nfl_payout_forecast_audit"),
        Index("ix_nfl_payout_forecast_generated", "generated_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    match_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_event_matches.id", ondelete="RESTRICT"), nullable=False
    )
    market_id: Mapped[UUID] = mapped_column(
        ForeignKey("markets.id", ondelete="RESTRICT"), nullable=False
    )
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("sports_events.id", ondelete="RESTRICT"), nullable=False
    )
    source_shadow_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("nfl_shadow_forecasts.id", ondelete="RESTRICT"), nullable=False
    )
    home_team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    away_team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    yes_team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    seed_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    metric_kind: Mapped[str] = mapped_column(String(100), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(100), nullable=False)
    promotion_state: Mapped[str] = mapped_column(String(100), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    market_close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_source_last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    market_source_last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expected_home_payout: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    expected_away_payout: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    expected_yes_payout: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    expected_no_payout: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    operational_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    trading_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    audit: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
