from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MarketEventMatchRecord(Base):
    """Append-oriented, semantically idempotent market-to-event decision."""

    __tablename__ = "market_event_matches"
    __table_args__ = (
        UniqueConstraint(
            "market_id",
            "matcher_version",
            "input_fingerprint",
            name="uq_market_event_matches_semantic_input",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_market_event_matches_confidence",
        ),
        CheckConstraint(
            "min_confidence >= 0 AND min_confidence <= 1 "
            "AND ambiguity_margin >= 0 AND ambiguity_margin <= 1",
            name="ck_market_event_matches_policy_confidence",
        ),
        CheckConstraint(
            "time_window_hours >= 1 AND time_window_hours <= 168",
            name="ck_market_event_matches_time_window",
        ),
        CheckConstraint(
            "length(input_fingerprint) = 64",
            name="ck_market_event_matches_fingerprint_length",
        ),
        CheckConstraint(
            "status IN ('matched', 'ambiguous', 'unmatched')",
            name="ck_market_event_matches_status",
        ),
        CheckConstraint(
            "league IN ('nba', 'mlb')",
            name="ck_market_event_matches_league",
        ),
        CheckConstraint(
            "(status = 'matched' AND sports_event_id IS NOT NULL "
            "AND confidence >= min_confidence "
            "AND ((league = 'nba' AND automatic_trading_eligible = true) "
            "OR (league = 'mlb' AND automatic_trading_eligible = false))) OR "
            "(status IN ('ambiguous', 'unmatched') AND sports_event_id IS NULL "
            "AND automatic_trading_eligible = false)",
            name="ck_market_event_matches_safety_state",
        ),
        Index(
            "ix_market_event_matches_market_evaluated",
            "market_id",
            "evaluated_at",
        ),
        Index("ix_market_event_matches_league_evaluated", "league", "evaluated_at"),
        Index(
            "ix_market_event_matches_status_eligible",
            "status",
            "automatic_trading_eligible",
            "evaluated_at",
        ),
        Index("ix_market_event_matches_event", "sports_event_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    market_id: Mapped[UUID] = mapped_column(
        ForeignKey("markets.id", ondelete="CASCADE"), nullable=False
    )
    league: Mapped[str] = mapped_column(String(20), nullable=False)
    sports_event_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("sports_events.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    method: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    matcher_version: Mapped[str] = mapped_column(String(50), nullable=False)
    min_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    ambiguity_margin: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    time_window_hours: Mapped[int] = mapped_column(nullable=False)
    automatic_trading_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    team_signals: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    candidate_scores: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    evidence: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
