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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ModelVersionRecord(Base):
    """Immutable registry entry for one effective forecasting configuration."""

    __tablename__ = "model_versions"
    __table_args__ = (
        UniqueConstraint("model_name", "model_version", name="uq_model_versions_identity"),
        CheckConstraint(
            "length(configuration_fingerprint) = 64",
            name="ck_model_versions_fingerprint_length",
        ),
        Index("ix_model_versions_name_created", "model_name", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    model_name: Mapped[str] = mapped_column(String(50), nullable=False)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(50), nullable=False)
    configuration: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    configuration_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    formula: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BaseForecastRecord(Base):
    """Append-only base probability generated from one semantic input snapshot."""

    __tablename__ = "base_forecasts"
    __table_args__ = (
        UniqueConstraint(
            "sports_event_id",
            "model_version_id",
            "purpose",
            "input_fingerprint",
            name="uq_base_forecasts_semantic_input",
        ),
        CheckConstraint(
            "home_win_probability >= 0 AND home_win_probability <= 1 "
            "AND away_win_probability >= 0 AND away_win_probability <= 1",
            name="ck_base_forecasts_probability_range",
        ),
        CheckConstraint(
            "home_win_probability + away_win_probability = 1",
            name="ck_base_forecasts_probability_sum",
        ),
        CheckConstraint(
            "home_team_id <> away_team_id",
            name="ck_base_forecasts_distinct_teams",
        ),
        CheckConstraint(
            "purpose IN ('operational', 'historical_replay')",
            name="ck_base_forecasts_purpose",
        ),
        CheckConstraint(
            "training_games_seen >= 0 AND training_games_processed >= 0 "
            "AND training_games_processed <= training_games_seen "
            "AND skipped_tied_games >= 0 AND skipped_incomplete_games >= 0 "
            "AND home_prior_games >= 0 AND away_prior_games >= 0",
            name="ck_base_forecasts_counts",
        ),
        CheckConstraint(
            "length(training_data_fingerprint) = 64 AND length(input_fingerprint) = 64",
            name="ck_base_forecasts_fingerprint_lengths",
        ),
        Index(
            "ix_base_forecasts_event_generated",
            "sports_event_id",
            "generated_at",
        ),
        Index(
            "ix_base_forecasts_model_purpose_generated",
            "model_version_id",
            "purpose",
            "generated_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    sports_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("sports_events.id", ondelete="RESTRICT"), nullable=False
    )
    model_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("model_versions.id", ondelete="RESTRICT"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)
    home_team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    away_team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    home_win_probability: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    away_win_probability: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    home_team_rating: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    away_team_rating: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    adjusted_rating_difference: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    training_data_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    input_features: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    training_games_seen: Mapped[int] = mapped_column(Integer, nullable=False)
    training_games_processed: Mapped[int] = mapped_column(Integer, nullable=False)
    skipped_tied_games: Mapped[int] = mapped_column(Integer, nullable=False)
    skipped_incomplete_games: Mapped[int] = mapped_column(Integer, nullable=False)
    home_prior_games: Mapped[int] = mapped_column(Integer, nullable=False)
    away_prior_games: Mapped[int] = mapped_column(Integer, nullable=False)
    latest_training_event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    forecast_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_event_last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    model_version: Mapped[ModelVersionRecord] = relationship(lazy="joined")
