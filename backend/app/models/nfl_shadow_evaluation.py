from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NflShadowEvaluationRecord(Base):
    """Immutable research-only scoring of a captured NFL shadow forecast."""

    __tablename__ = "nfl_shadow_evaluations"
    __table_args__ = (
        CheckConstraint(
            "research_only = true AND trading_enabled = false", name="ck_nfl_evaluation_safety"
        ),
        CheckConstraint(
            "generated_at < scheduled_start_time AND scheduled_start_time <= result_source_last_seen_at "
            "AND result_source_last_seen_at <= label_time",
            name="ck_nfl_evaluation_times",
        ),
        CheckConstraint(
            "expected_home_payout BETWEEN 0 AND 1 AND expected_yes_payout BETWEEN 0 AND 1 "
            "AND actual_home_payout IN (0, 0.5, 1) AND actual_yes_payout IN (0, 0.5, 1) "
            "AND squared_home_payout_error = (expected_home_payout - actual_home_payout) * (expected_home_payout - actual_home_payout) "
            "AND constant_half_squared_error = (0.5 - actual_home_payout) * (0.5 - actual_home_payout)",
            name="ck_nfl_evaluation_scores",
        ),
        CheckConstraint(
            "seed_fingerprint ~ '^[0-9a-f]{64}$' AND input_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND snapshot_fingerprint ~ '^[0-9a-f]{64}$' AND result_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_nfl_evaluation_fingerprints",
        ),
        CheckConstraint("jsonb_typeof(audit) = 'object'", name="ck_nfl_evaluation_audit"),
        Index("ix_nfl_evaluation_snapshot_time", "snapshot_id", "label_time"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey("nfl_shadow_forecasts.id", ondelete="RESTRICT")
    )
    sports_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("sports_events.id", ondelete="RESTRICT")
    )
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    seed_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluation_version: Mapped[str] = mapped_column(String(100), nullable=False)
    snapshot_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    label_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result_source_last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expected_home_payout: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    expected_yes_payout: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    actual_home_payout: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    actual_yes_payout: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    squared_home_payout_error: Mapped[Decimal] = mapped_column(Numeric(13, 12), nullable=False)
    constant_half_squared_error: Mapped[Decimal] = mapped_column(Numeric(13, 12), nullable=False)
    research_only: Mapped[bool] = mapped_column(Boolean, nullable=False)
    trading_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    audit: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
