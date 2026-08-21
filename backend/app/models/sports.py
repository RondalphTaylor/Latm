from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TeamRecord(Base):
    """Persisted provider-neutral sports team."""

    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint(
            "provider_name",
            "provider_team_id",
            name="uq_teams_provider_team_id",
        ),
        Index("ix_teams_league_abbreviation", "league", "abbreviation"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    provider_name: Mapped[str] = mapped_column(
        ForeignKey("providers.name", ondelete="RESTRICT"), nullable=False
    )
    provider_team_id: Mapped[str] = mapped_column(String(100), nullable=False)
    league: Mapped[str] = mapped_column(String(20), nullable=False)
    abbreviation: Mapped[str] = mapped_column(String(10), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    conference: Mapped[str | None] = mapped_column(String(50))
    division: Mapped[str | None] = mapped_column(String(100))
    raw_data: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SportsEventRecord(Base):
    """Persisted provider-neutral sports event."""

    __tablename__ = "sports_events"
    __table_args__ = (
        UniqueConstraint(
            "provider_name",
            "provider_event_id",
            name="uq_sports_events_provider_event_id",
        ),
        CheckConstraint("home_team_id <> away_team_id", name="ck_sports_events_distinct_teams"),
        CheckConstraint(
            "home_score IS NULL OR home_score >= 0",
            name="ck_sports_events_home_score_nonnegative",
        ),
        CheckConstraint(
            "away_score IS NULL OR away_score >= 0",
            name="ck_sports_events_away_score_nonnegative",
        ),
        CheckConstraint(
            "(home_score IS NULL) = (away_score IS NULL)",
            name="ck_sports_events_score_pair",
        ),
        Index(
            "ix_sports_events_league_start_status",
            "league",
            "scheduled_start_time",
            "status",
        ),
        Index("ix_sports_events_home_start", "home_team_id", "scheduled_start_time"),
        Index("ix_sports_events_away_start", "away_team_id", "scheduled_start_time"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    provider_name: Mapped[str] = mapped_column(
        ForeignKey("providers.name", ondelete="RESTRICT"), nullable=False
    )
    provider_event_id: Mapped[str] = mapped_column(String(100), nullable=False)
    league: Mapped[str] = mapped_column(String(20), nullable=False)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    scheduled_start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    status_detail: Mapped[str] = mapped_column(String(100), nullable=False)
    period: Mapped[int] = mapped_column(Integer, nullable=False)
    clock: Mapped[str | None] = mapped_column(String(50))
    postseason: Mapped[bool] = mapped_column(Boolean, nullable=False)
    postponed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    tournament_stage: Mapped[str | None] = mapped_column(String(100))
    home_team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    away_team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    home_score: Mapped[int | None] = mapped_column(Integer)
    away_score: Mapped[int | None] = mapped_column(Integer)
    venue: Mapped[str | None] = mapped_column(String(300))
    raw_data: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    home_team: Mapped[TeamRecord] = relationship(
        foreign_keys=[home_team_id],
        lazy="joined",
    )
    away_team: Mapped[TeamRecord] = relationship(
        foreign_keys=[away_team_id],
        lazy="joined",
    )
