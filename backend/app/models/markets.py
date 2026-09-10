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
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Provider(Base):
    """An external read-only data provider."""

    __tablename__ = "providers"

    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_read_only: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PredictionMarketRecord(Base):
    """Persisted provider-neutral prediction market."""

    __tablename__ = "markets"
    __table_args__ = (
        UniqueConstraint(
            "provider_name",
            "provider_market_id",
            name="uq_markets_provider_market_id",
        ),
        Index("ix_markets_is_nba_status", "is_nba", "status"),
        CheckConstraint(
            "(sports_league IS NULL AND sports_market_type IS NULL "
            "AND sports_classification_method IS NULL "
            "AND sports_classification_version IS NULL "
            "AND sports_classification_fingerprint IS NULL) OR "
            "(sports_league IN ('nba', 'mlb', 'nfl') "
            "AND sports_market_type = 'single_game_winner' "
            "AND sports_classification_method IS NOT NULL "
            "AND sports_classification_version IS NOT NULL "
            "AND length(sports_classification_fingerprint) = 64)",
            name="ck_markets_sports_classification",
        ),
        Index(
            "ix_markets_sports_classification_status",
            "sports_league",
            "sports_market_type",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    provider_name: Mapped[str] = mapped_column(
        ForeignKey("providers.name", ondelete="RESTRICT"), nullable=False
    )
    provider_market_id: Mapped[str] = mapped_column(String(200), nullable=False)
    provider_event_id: Mapped[str | None] = mapped_column(String(200))
    series_ticker: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(100))
    market_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    subtitle: Mapped[str | None] = mapped_column(Text)
    rules_primary: Mapped[str | None] = mapped_column(Text)
    rules_secondary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    is_nba: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sports_league: Mapped[str | None] = mapped_column(String(20))
    sports_market_type: Mapped[str | None] = mapped_column(String(50))
    sports_classification_method: Mapped[str | None] = mapped_column(String(50))
    sports_classification_version: Mapped[str | None] = mapped_column(String(50))
    sports_classification_fingerprint: Mapped[str | None] = mapped_column(String(64))
    open_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    close_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    occurrence_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_data: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    outcomes: Mapped[list[MarketOutcomeRecord]] = relationship(
        back_populates="market",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    prices: Mapped[list[MarketPriceRecord]] = relationship(
        back_populates="market",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by=lambda: MarketPriceRecord.retrieved_at.desc(),
    )
    resolutions: Mapped[list[MarketResolutionRecord]] = relationship(
        back_populates="market",
        lazy="selectin",
        order_by=lambda: (
            MarketResolutionRecord.settled_at.desc(),
            MarketResolutionRecord.retrieved_at.desc(),
            MarketResolutionRecord.id.desc(),
        ),
    )


class MarketOutcomeRecord(Base):
    """Persisted normalized YES or NO market outcome."""

    __tablename__ = "market_outcomes"
    __table_args__ = (
        UniqueConstraint(
            "market_id",
            "provider_outcome_id",
            name="uq_market_outcomes_provider_outcome_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    market_id: Mapped[UUID] = mapped_column(
        ForeignKey("markets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_outcome_id: Mapped[str] = mapped_column(String(100), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    market: Mapped[PredictionMarketRecord] = relationship(back_populates="outcomes")


class MarketPriceRecord(Base):
    """Append-oriented point-in-time market price snapshot."""

    __tablename__ = "market_prices"
    __table_args__ = (
        UniqueConstraint("market_id", "retrieved_at", name="uq_market_prices_observation"),
        Index("ix_market_prices_market_retrieved", "market_id", "retrieved_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    market_id: Mapped[UUID] = mapped_column(
        ForeignKey("markets.id", ondelete="CASCADE"), nullable=False
    )
    yes_bid: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    yes_ask: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    no_bid: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    no_ask: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    last_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    volume: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    volume_24h: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    open_interest: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    liquidity: Mapped[Decimal | None] = mapped_column(Numeric(24, 4))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    market: Mapped[PredictionMarketRecord] = relationship(back_populates="prices")


class MarketResolutionRecord(Base):
    """Append-only official settlement for a standard binary market."""

    __tablename__ = "market_resolutions"
    __table_args__ = (
        UniqueConstraint(
            "market_id",
            "input_fingerprint",
            name="uq_market_resolutions_semantic_input",
        ),
        CheckConstraint("result IN ('yes', 'no')", name="ck_market_resolutions_result"),
        CheckConstraint(
            "resolution_type = 'standard_binary' AND source = 'official_provider'",
            name="ck_market_resolutions_source",
        ),
        CheckConstraint(
            "yes_payout >= 0 AND yes_payout <= 1 "
            "AND no_payout >= 0 AND no_payout <= 1 "
            "AND yes_payout + no_payout = 1 "
            "AND ((result = 'yes' AND yes_payout = 1 AND no_payout = 0) "
            "OR (result = 'no' AND yes_payout = 0 AND no_payout = 1))",
            name="ck_market_resolutions_binary_payout",
        ),
        CheckConstraint(
            "settled_at <= retrieved_at",
            name="ck_market_resolutions_times",
        ),
        CheckConstraint(
            "length(input_fingerprint) = 64",
            name="ck_market_resolutions_fingerprint",
        ),
        Index(
            "ix_market_resolutions_market_settled",
            "market_id",
            "settled_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    market_id: Mapped[UUID] = mapped_column(
        ForeignKey("markets.id", ondelete="RESTRICT"), nullable=False
    )
    result: Mapped[str] = mapped_column(String(10), nullable=False)
    yes_payout: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    no_payout: Mapped[Decimal] = mapped_column(Numeric(7, 6), nullable=False)
    resolution_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    settled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)

    market: Mapped[PredictionMarketRecord] = relationship(back_populates="resolutions")
