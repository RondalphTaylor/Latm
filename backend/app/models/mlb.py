from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
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
        UniqueConstraint(
            "id",
            "sports_event_id",
            name="uq_mlb_lineup_snapshots_id_event",
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


class MlbStatcastFeatureSnapshotRecord(Base):
    """Append-only official Statcast quantitative features for one posted lineup."""

    __tablename__ = "mlb_statcast_feature_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "lineup_snapshot_id",
            "input_fingerprint",
            name="uq_mlb_statcast_feature_snapshots_semantic_input",
        ),
        UniqueConstraint(
            "id",
            "sports_event_id",
            "lineup_snapshot_id",
            name="uq_mlb_statcast_feature_snapshots_id_event_lineup",
        ),
        ForeignKeyConstraint(
            ["lineup_snapshot_id", "sports_event_id"],
            ["mlb_lineup_snapshots.id", "mlb_lineup_snapshots.sports_event_id"],
            name="fk_mlb_statcast_feature_snapshots_lineup_event",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "provider_name = 'baseball_savant'",
            name="ck_mlb_statcast_feature_snapshots_provider",
        ),
        CheckConstraint(
            "observation_basis IN ('operational_pregame', 'retrospective')",
            name="ck_mlb_statcast_feature_snapshots_basis",
        ),
        CheckConstraint(
            "(observation_basis = 'operational_pregame' "
            "AND operational_pregame_eligible = true "
            "AND source_retrieved_at < scheduled_start_time) OR "
            "(observation_basis = 'retrospective' "
            "AND operational_pregame_eligible = false "
            "AND source_retrieved_at >= scheduled_start_time)",
            name="ck_mlb_statcast_feature_snapshots_eligibility",
        ),
        CheckConstraint(
            "window_end_date < target_event_date "
            "AND window_end_date - window_start_date + 1 = lookback_days",
            name="ck_mlb_statcast_feature_snapshots_window",
        ),
        CheckConstraint(
            "lookback_days BETWEEN 1 AND 90",
            name="ck_mlb_statcast_feature_snapshots_lookback",
        ),
        CheckConstraint(
            "jsonb_array_length(home_batters) = 9 AND jsonb_array_length(away_batters) = 9",
            name="ck_mlb_statcast_feature_snapshots_batters",
        ),
        CheckConstraint(
            "jsonb_typeof(source_rows) = 'array'",
            name="ck_mlb_statcast_feature_snapshots_source_rows",
        ),
        CheckConstraint(
            "policy_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND source_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_mlb_statcast_feature_snapshots_fingerprints",
        ),
        Index(
            "ix_mlb_statcast_feature_snapshots_event_retrieved",
            "sports_event_id",
            "source_retrieved_at",
        ),
        Index(
            "ix_mlb_statcast_feature_snapshots_eligible_retrieved",
            "operational_pregame_eligible",
            "source_retrieved_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    sports_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("sports_events.id", ondelete="RESTRICT"), nullable=False
    )
    lineup_snapshot_id: Mapped[UUID] = mapped_column(nullable=False)
    provider_name: Mapped[str] = mapped_column(
        ForeignKey("providers.name", ondelete="RESTRICT"), nullable=False
    )
    provider_event_id: Mapped[str] = mapped_column(String(100), nullable=False)
    target_event_date: Mapped[date] = mapped_column(Date, nullable=False)
    scheduled_start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    window_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=False)
    source_retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observation_basis: Mapped[str] = mapped_column(String(30), nullable=False)
    operational_pregame_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    policy_name: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    home_starting_pitcher: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    away_starting_pitcher: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    home_batters: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    away_batters: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_manifest: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    source_rows: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)

    sports_event: Mapped[SportsEventRecord] = relationship(lazy="joined")
    lineup_snapshot: Mapped[MlbLineupSnapshotRecord] = relationship(
        lazy="joined",
        overlaps="sports_event",
    )


class MlbGameFeatureVectorRecord(Base):
    """Append-only leakage-safe candidate feature vector; never a probability."""

    __tablename__ = "mlb_game_feature_vectors"
    __table_args__ = (
        UniqueConstraint(
            "statcast_snapshot_id",
            "input_fingerprint",
            name="uq_mlb_game_feature_vectors_semantic_input",
        ),
        ForeignKeyConstraint(
            ["statcast_snapshot_id", "sports_event_id", "lineup_snapshot_id"],
            [
                "mlb_statcast_feature_snapshots.id",
                "mlb_statcast_feature_snapshots.sports_event_id",
                "mlb_statcast_feature_snapshots.lineup_snapshot_id",
            ],
            name="fk_mlb_game_feature_vectors_statcast_lineage",
            ondelete="RESTRICT",
        ),
        CheckConstraint("home_team_id <> away_team_id", name="ck_mlb_game_feature_vectors_teams"),
        CheckConstraint(
            "source_observation_basis IN ('operational_pregame', 'retrospective') "
            "AND feature_availability_basis IN ('operational_pregame', 'retrospective')",
            name="ck_mlb_game_feature_vectors_basis",
        ),
        CheckConstraint(
            "jsonb_typeof(source_metrics) = 'object' "
            "AND jsonb_typeof(coverage) = 'object' "
            "AND jsonb_typeof(feature_values) = 'object' "
            "AND jsonb_typeof(missing_features) = 'array'",
            name="ck_mlb_game_feature_vectors_json",
        ),
        CheckConstraint(
            "complete_feature_vector = (jsonb_array_length(missing_features) = 0)",
            name="ck_mlb_game_feature_vectors_complete",
        ),
        CheckConstraint(
            "operational_model_input_eligible = (complete_feature_vector "
            "AND source_observation_basis = 'operational_pregame' "
            "AND feature_availability_basis = 'operational_pregame' "
            "AND source_retrieved_at < scheduled_start_time "
            "AND built_at < scheduled_start_time)",
            name="ck_mlb_game_feature_vectors_eligibility",
        ),
        CheckConstraint(
            "research_only = true AND probability_generated = false "
            "AND automatic_trading_eligible = false",
            name="ck_mlb_game_feature_vectors_safety",
        ),
        CheckConstraint(
            "policy_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND source_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_mlb_game_feature_vectors_fingerprints",
        ),
        Index(
            "ix_mlb_game_feature_vectors_event_built",
            "sports_event_id",
            "built_at",
        ),
        Index(
            "ix_mlb_game_feature_vectors_eligible_built",
            "operational_model_input_eligible",
            "built_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    sports_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("sports_events.id", ondelete="RESTRICT"), nullable=False
    )
    lineup_snapshot_id: Mapped[UUID] = mapped_column(nullable=False)
    statcast_snapshot_id: Mapped[UUID] = mapped_column(nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(100), nullable=False)
    target_event_date: Mapped[date] = mapped_column(Date, nullable=False)
    scheduled_start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    home_team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    away_team_id: Mapped[UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False
    )
    source_retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_observation_basis: Mapped[str] = mapped_column(String(30), nullable=False)
    built_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    feature_availability_basis: Mapped[str] = mapped_column(String(30), nullable=False)
    policy_name: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    model_candidate_name: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_metrics: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    coverage: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    feature_values: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    missing_features: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    complete_feature_vector: Mapped[bool] = mapped_column(Boolean, nullable=False)
    operational_model_input_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    research_only: Mapped[bool] = mapped_column(Boolean, nullable=False)
    probability_generated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    automatic_trading_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    sports_event: Mapped[SportsEventRecord] = relationship(lazy="joined")
    statcast_snapshot: Mapped[MlbStatcastFeatureSnapshotRecord] = relationship(
        lazy="joined",
        overlaps="sports_event",
    )
