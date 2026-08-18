from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.forecasts import ModelVersionRecord


class ForecastEvaluationRecord(Base):
    """Immutable score for one forecast against one frozen event outcome."""

    __tablename__ = "forecast_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "base_forecast_id",
            "policy_version",
            "input_fingerprint",
            name="uq_forecast_evaluations_semantic_input",
        ),
        CheckConstraint(
            "purpose IN ('operational', 'historical_replay')",
            name="ck_forecast_evaluations_purpose",
        ),
        CheckConstraint(
            "home_team_id <> away_team_id",
            name="ck_forecast_evaluations_distinct_teams",
        ),
        CheckConstraint(
            "result_home_score >= 0 AND result_away_score >= 0 "
            "AND result_home_score <> result_away_score "
            "AND ((home_won = true AND result_home_score > result_away_score) OR "
            "(home_won = false AND result_home_score < result_away_score))",
            name="ck_forecast_evaluations_result",
        ),
        CheckConstraint(
            "home_win_probability >= 0 AND home_win_probability <= 1 "
            "AND ((home_win_probability = 0.5 "
            "AND predicted_home_win IS NULL) OR "
            "(home_win_probability > 0.5 "
            "AND predicted_home_win IS TRUE) OR "
            "(home_win_probability < 0.5 "
            "AND predicted_home_win IS FALSE))",
            name="ck_forecast_evaluations_prediction",
        ),
        CheckConstraint(
            "brier_score >= 0 AND brier_score <= 1 "
            "AND brier_score = "
            "(home_win_probability - CASE WHEN home_won THEN 1 ELSE 0 END) * "
            "(home_win_probability - CASE WHEN home_won THEN 1 ELSE 0 END)",
            name="ck_forecast_evaluations_brier",
        ),
        CheckConstraint(
            "(predicted_home_win IS NULL AND correct IS NULL) OR "
            "(predicted_home_win IS NOT NULL "
            "AND correct IS NOT NULL "
            "AND correct = (predicted_home_win = home_won))",
            name="ck_forecast_evaluations_correctness",
        ),
        CheckConstraint(
            "(purpose = 'operational' "
            "AND forecast_as_of = forecast_generated_at "
            "AND forecast_as_of < result_scheduled_start_time) OR "
            "(purpose = 'historical_replay' "
            "AND forecast_as_of = result_scheduled_start_time "
            "AND forecast_generated_at >= forecast_as_of)",
            name="ck_forecast_evaluations_cutoff",
        ),
        CheckConstraint(
            "forecast_generated_at <= evaluated_at AND result_source_last_seen_at <= evaluated_at",
            name="ck_forecast_evaluations_times",
        ),
        CheckConstraint(
            "length(policy_fingerprint) = 64 "
            "AND length(outcome_fingerprint) = 64 "
            "AND length(input_fingerprint) = 64",
            name="ck_forecast_evaluations_fingerprints",
        ),
        CheckConstraint(
            "jsonb_typeof(audit_snapshot) = 'object'",
            name="ck_forecast_evaluations_source_snapshot",
        ),
        Index(
            "ix_forecast_evaluations_event_evaluated",
            "sports_event_id",
            "evaluated_at",
        ),
        Index(
            "ix_forecast_evaluations_model_purpose_event_date",
            "model_version_id",
            "purpose",
            "event_date",
        ),
        Index(
            "ix_forecast_evaluations_purpose_event_date",
            "purpose",
            "event_date",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    base_forecast_id: Mapped[UUID] = mapped_column(
        ForeignKey("base_forecasts.id", ondelete="RESTRICT"), nullable=False
    )
    sports_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("sports_events.id", ondelete="RESTRICT"), nullable=False
    )
    model_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("model_versions.id", ondelete="RESTRICT"), nullable=False
    )
    home_team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    away_team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    result_scheduled_start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    forecast_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    forecast_generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    result_source_last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    home_win_probability: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    predicted_home_win: Mapped[bool | None] = mapped_column(Boolean)
    home_won: Mapped[bool] = mapped_column(Boolean, nullable=False)
    result_home_score: Mapped[int] = mapped_column(Integer, nullable=False)
    result_away_score: Mapped[int] = mapped_column(Integer, nullable=False)
    brier_score: Mapped[Decimal] = mapped_column(Numeric(14, 12), nullable=False)
    correct: Mapped[bool | None] = mapped_column(Boolean)
    policy_name: Mapped[str] = mapped_column(String(50), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    model_version: Mapped[ModelVersionRecord] = relationship(lazy="joined")
