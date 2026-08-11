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
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.forecasts import ModelVersionRecord


class OpportunityRecord(Base):
    """Append-only directional comparison; never a trade approval or order."""

    __tablename__ = "opportunities"
    __table_args__ = (
        UniqueConstraint(
            "market_id",
            "direction",
            "strategy_version",
            "input_fingerprint",
            name="uq_opportunities_semantic_input",
        ),
        CheckConstraint(
            "market_probability > 0 AND market_probability < 1 "
            "AND model_probability >= 0 AND model_probability <= 1",
            name="ck_opportunities_probability_range",
        ),
        CheckConstraint(
            "raw_edge >= -1 AND raw_edge <= 1 "
            "AND raw_edge = model_probability - market_probability",
            name="ck_opportunities_raw_edge",
        ),
        CheckConstraint(
            "direction IN ('yes', 'no')",
            name="ck_opportunities_direction",
        ),
        CheckConstraint(
            "price_source IN ('direct_yes_ask', 'direct_no_ask')",
            name="ck_opportunities_price_source",
        ),
        CheckConstraint(
            "status IN ('ignore', 'watch', 'trade_candidate')",
            name="ck_opportunities_status",
        ),
        CheckConstraint(
            "watch_min_raw_edge >= 0 "
            "AND watch_min_raw_edge < trade_candidate_min_raw_edge "
            "AND trade_candidate_min_raw_edge <= 1",
            name="ck_opportunities_thresholds",
        ),
        CheckConstraint(
            "(status = 'ignore' AND raw_edge < watch_min_raw_edge) OR "
            "(status = 'watch' AND raw_edge >= watch_min_raw_edge "
            "AND raw_edge < trade_candidate_min_raw_edge) OR "
            "(status = 'trade_candidate' "
            "AND raw_edge >= trade_candidate_min_raw_edge)",
            name="ck_opportunities_status_edge",
        ),
        CheckConstraint(
            "yes_team_id <> no_team_id AND "
            "((direction = 'yes' AND outcome_team_id = yes_team_id) OR "
            "(direction = 'no' AND outcome_team_id = no_team_id))",
            name="ck_opportunities_orientation",
        ),
        CheckConstraint(
            "max_market_price_age_seconds > 0 "
            "AND max_operational_forecast_age_seconds > 0 "
            "AND price_age_seconds >= 0 AND forecast_age_seconds >= 0",
            name="ck_opportunities_ages",
        ),
        CheckConstraint(
            "length(orientation_fingerprint) = 64 "
            "AND length(policy_fingerprint) = 64 "
            "AND length(input_fingerprint) = 64",
            name="ck_opportunities_fingerprint_lengths",
        ),
        CheckConstraint(
            "evaluated_at <= valid_until",
            name="ck_opportunities_valid_until",
        ),
        Index("ix_opportunities_market_evaluated", "market_id", "evaluated_at"),
        Index("ix_opportunities_event_evaluated", "sports_event_id", "evaluated_at"),
        Index(
            "ix_opportunities_status_direction_evaluated",
            "status",
            "direction",
            "evaluated_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    market_id: Mapped[UUID] = mapped_column(
        ForeignKey("markets.id", ondelete="RESTRICT"), nullable=False
    )
    market_price_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_prices.id", ondelete="RESTRICT"), nullable=False
    )
    market_event_match_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_event_matches.id", ondelete="RESTRICT"), nullable=False
    )
    sports_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("sports_events.id", ondelete="RESTRICT"), nullable=False
    )
    base_forecast_id: Mapped[UUID] = mapped_column(
        ForeignKey("base_forecasts.id", ondelete="RESTRICT"), nullable=False
    )
    model_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("model_versions.id", ondelete="RESTRICT"), nullable=False
    )
    outcome_team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    yes_team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    no_team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    price_source: Mapped[str] = mapped_column(String(30), nullable=False)
    mapping_method: Mapped[str] = mapped_column(String(100), nullable=False)
    orientation_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    market_probability: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    model_probability: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    raw_edge: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    status_reason: Mapped[str] = mapped_column(String(200), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(50), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    watch_min_raw_edge: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    trade_candidate_min_raw_edge: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    max_market_price_age_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    max_operational_forecast_age_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    price_retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    forecast_generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price_age_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    forecast_age_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    model_version: Mapped[ModelVersionRecord] = relationship(lazy="joined")
