from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.sports import SportsEventRecord


class MlbLineupSnapshotRecord(Base):
    """Append-only official MLB probable-pitcher and batting-order observation."""

    __tablename__ = "mlb_lineup_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "sports_event_id",
            "input_fingerprint",
            name="uq_mlb_lineup_snapshots_semantic_input",
        ),
        CheckConstraint("provider_name = 'mlb'", name="ck_mlb_lineup_snapshots_provider"),
        CheckConstraint("home_team_id <> away_team_id", name="ck_mlb_lineup_snapshots_teams"),
        CheckConstraint(
            "observation_phase IN ('pregame', 'live', 'postgame')",
            name="ck_mlb_lineup_snapshots_phase",
        ),
        CheckConstraint(
            "home_lineup_state IN ('unavailable', 'partial', 'posted') "
            "AND away_lineup_state IN ('unavailable', 'partial', 'posted')",
            name="ck_mlb_lineup_snapshots_states",
        ),
        CheckConstraint(
            "(home_lineup_state = 'unavailable' AND jsonb_array_length(home_lineup) = 0) OR "
            "(home_lineup_state = 'partial' AND jsonb_array_length(home_lineup) BETWEEN 1 AND 8) "
            "OR (home_lineup_state = 'posted' AND jsonb_array_length(home_lineup) = 9)",
            name="ck_mlb_lineup_snapshots_home_count",
        ),
        CheckConstraint(
            "(away_lineup_state = 'unavailable' AND jsonb_array_length(away_lineup) = 0) OR "
            "(away_lineup_state = 'partial' AND jsonb_array_length(away_lineup) BETWEEN 1 AND 8) "
            "OR (away_lineup_state = 'posted' AND jsonb_array_length(away_lineup) = 9)",
            name="ck_mlb_lineup_snapshots_away_count",
        ),
        CheckConstraint(
            "complete_for_pregame_model = "
            "(observation_phase = 'pregame' AND source_updated_at <= retrieved_at "
            "AND source_updated_at < scheduled_start_time AND retrieved_at < scheduled_start_time "
            "AND home_lineup_state = 'posted' AND away_lineup_state = 'posted' "
            "AND home_probable_pitcher IS NOT NULL AND away_probable_pitcher IS NOT NULL)",
            name="ck_mlb_lineup_snapshots_complete",
        ),
        CheckConstraint(
            "input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_mlb_lineup_snapshots_fingerprint",
        ),
        Index(
            "ix_mlb_lineup_snapshots_event_retrieved",
            "sports_event_id",
            "retrieved_at",
        ),
        Index(
            "ix_mlb_lineup_snapshots_phase_complete",
            "observation_phase",
            "complete_for_pregame_model",
            "retrieved_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    sports_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("sports_events.id", ondelete="RESTRICT"), nullable=False
    )
    provider_name: Mapped[str] = mapped_column(
        ForeignKey("providers.name", ondelete="RESTRICT"), nullable=False
    )
    provider_event_id: Mapped[str] = mapped_column(String(100), nullable=False)
    home_team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    away_team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    scheduled_start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_abstract_state: Mapped[str] = mapped_column(String(30), nullable=False)
    source_detailed_state: Mapped[str] = mapped_column(String(100), nullable=False)
    observation_phase: Mapped[str] = mapped_column(String(20), nullable=False)
    home_probable_pitcher: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    away_probable_pitcher: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    home_lineup_state: Mapped[str] = mapped_column(String(20), nullable=False)
    away_lineup_state: Mapped[str] = mapped_column(String(20), nullable=False)
    home_lineup: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    away_lineup: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    complete_for_pregame_model: Mapped[bool] = mapped_column(Boolean, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)

    sports_event: Mapped[SportsEventRecord] = relationship(lazy="joined")
