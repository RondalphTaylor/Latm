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
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
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

    @property
    def complete_for_research_features(self) -> bool:
        """Whether exact pitcher and nine-player lineups exist, regardless of observation time."""

        return (
            self.home_lineup_state == "posted"
            and self.away_lineup_state == "posted"
            and self.home_probable_pitcher is not None
            and self.away_probable_pitcher is not None
            and len(self.home_lineup) == 9
            and len(self.away_lineup) == 9
        )


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
        UniqueConstraint(
            "id",
            "sports_event_id",
            name="uq_mlb_game_feature_vectors_id_event",
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


class MlbLabeledFeatureExampleRecord(Base):
    """Append-only official outcome label for one exact MLB feature vector."""

    __tablename__ = "mlb_labeled_feature_examples"
    __table_args__ = (
        UniqueConstraint(
            "game_feature_vector_id",
            "split_policy_fingerprint",
            "outcome_fingerprint",
            name="uq_mlb_labeled_feature_examples_semantic_input",
        ),
        ForeignKeyConstraint(
            ["game_feature_vector_id", "sports_event_id"],
            ["mlb_game_feature_vectors.id", "mlb_game_feature_vectors.sports_event_id"],
            name="fk_mlb_labeled_feature_examples_vector_event",
            ondelete="RESTRICT",
        ),
        CheckConstraint("outcome_status = 'final'", name="ck_mlb_labeled_examples_final"),
        CheckConstraint(
            "home_score >= 0 AND away_score >= 0 AND home_score <> away_score",
            name="ck_mlb_labeled_examples_score",
        ),
        CheckConstraint(
            "home_won = (home_score > away_score)", name="ck_mlb_labeled_examples_winner"
        ),
        CheckConstraint(
            "availability_basis IN ('operational_pregame', 'retrospective') "
            "AND split IN ('train', 'validation', 'test', 'prospective_holdout')",
            name="ck_mlb_labeled_examples_roles",
        ),
        CheckConstraint(
            "validation_start < test_start AND test_start < prospective_holdout_start",
            name="ck_mlb_labeled_examples_boundaries",
        ),
        CheckConstraint(
            "(split = 'train' AND scheduled_start_time < validation_start) OR "
            "(split = 'validation' AND scheduled_start_time >= validation_start "
            "AND scheduled_start_time < test_start) OR "
            "(split = 'test' AND scheduled_start_time >= test_start "
            "AND scheduled_start_time < prospective_holdout_start) OR "
            "(split = 'prospective_holdout' "
            "AND scheduled_start_time >= prospective_holdout_start)",
            name="ck_mlb_labeled_examples_split",
        ),
        CheckConstraint(
            "outcome_source_last_seen_at >= scheduled_start_time "
            "AND labeled_at >= outcome_source_last_seen_at",
            name="ck_mlb_labeled_examples_timing",
        ),
        CheckConstraint(
            "research_only = true AND probability_generated = false "
            "AND automatic_trading_eligible = false",
            name="ck_mlb_labeled_examples_safety",
        ),
        CheckConstraint(
            "feature_vector_input_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND feature_policy_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND split_policy_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND outcome_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND example_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_mlb_labeled_examples_fingerprints",
        ),
        CheckConstraint(
            "jsonb_typeof(outcome_source_snapshot) = 'object'",
            name="ck_mlb_labeled_examples_source_snapshot",
        ),
        Index(
            "ix_mlb_labeled_examples_policy_split_start",
            "split_policy_fingerprint",
            "split",
            "scheduled_start_time",
        ),
        Index(
            "ix_mlb_labeled_examples_event_labeled",
            "sports_event_id",
            "labeled_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    game_feature_vector_id: Mapped[UUID] = mapped_column(nullable=False)
    sports_event_id: Mapped[UUID] = mapped_column(
        ForeignKey("sports_events.id", ondelete="RESTRICT"), nullable=False
    )
    feature_vector_input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_policy_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    availability_basis: Mapped[str] = mapped_column(String(30), nullable=False)
    scheduled_start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome_status: Mapped[str] = mapped_column(String(30), nullable=False)
    home_score: Mapped[int] = mapped_column(Integer, nullable=False)
    away_score: Mapped[int] = mapped_column(Integer, nullable=False)
    home_won: Mapped[bool] = mapped_column(Boolean, nullable=False)
    outcome_source_last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    outcome_source_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    split: Mapped[str] = mapped_column(String(30), nullable=False)
    split_policy_name: Mapped[str] = mapped_column(String(100), nullable=False)
    split_policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    validation_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    test_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    prospective_holdout_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    split_policy_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    example_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    labeled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    research_only: Mapped[bool] = mapped_column(Boolean, nullable=False)
    probability_generated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    automatic_trading_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)

    feature_vector: Mapped[MlbGameFeatureVectorRecord] = relationship(
        lazy="joined", overlaps="sports_event"
    )
    sports_event: Mapped[SportsEventRecord] = relationship(lazy="joined")


class MlbFittedResearchModelRecord(Base):
    """Immutable, readiness-gated MLB research model artifact without trading authority."""

    __tablename__ = "mlb_fitted_research_models"
    __table_args__ = (
        UniqueConstraint(
            "effective_model_version",
            name="uq_mlb_fitted_research_models_version",
        ),
        UniqueConstraint(
            "model_fingerprint",
            name="uq_mlb_fitted_research_models_fingerprint",
        ),
        UniqueConstraint(
            "input_fingerprint",
            name="uq_mlb_fitted_research_models_input",
        ),
        CheckConstraint(
            "train_example_count >= 500 AND validation_example_count >= 150 "
            "AND test_example_count >= 150",
            name="ck_mlb_fitted_research_models_readiness",
        ),
        CheckConstraint(
            "selected_regularization_strength > 0",
            name="ck_mlb_fitted_research_models_regularization",
        ),
        CheckConstraint(
            "jsonb_typeof(selected_features) = 'array' "
            "AND jsonb_array_length(selected_features) = 8 "
            "AND jsonb_typeof(standardized_coefficients) = 'object' "
            "AND jsonb_typeof(feature_means) = 'object' "
            "AND jsonb_typeof(feature_scales) = 'object' "
            "AND jsonb_typeof(validation_metrics) = 'object' "
            "AND jsonb_typeof(test_metrics) = 'object' "
            "AND jsonb_typeof(candidate_results) = 'array' "
            "AND jsonb_array_length(candidate_results) > 0 "
            "AND jsonb_typeof(readiness_snapshot) = 'object' "
            "AND jsonb_typeof(source_manifest) = 'array'",
            name="ck_mlb_fitted_research_models_json",
        ),
        CheckConstraint(
            "jsonb_array_length(source_manifest) = "
            "train_example_count + validation_example_count + test_example_count",
            name="ck_mlb_fitted_research_models_manifest_count",
        ),
        CheckConstraint(
            "research_only = true AND operational_probability_enabled = false "
            "AND automatic_trading_enabled = false",
            name="ck_mlb_fitted_research_models_safety",
        ),
        CheckConstraint(
            "fitting_policy_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND readiness_policy_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND split_policy_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND training_data_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND model_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND input_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_mlb_fitted_research_models_fingerprints",
        ),
        Index(
            "ix_mlb_fitted_research_models_name_fitted",
            "model_name",
            "fitted_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    effective_model_version: Mapped[str] = mapped_column(String(150), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(100), nullable=False)
    fitting_policy_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    readiness_policy_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    split_policy_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    training_data_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    model_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    selected_features: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    selected_regularization_strength: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False
    )
    standardized_intercept: Mapped[Decimal] = mapped_column(Numeric(24, 12), nullable=False)
    standardized_coefficients: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    feature_means: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    feature_scales: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    train_example_count: Mapped[int] = mapped_column(Integer, nullable=False)
    validation_example_count: Mapped[int] = mapped_column(Integer, nullable=False)
    test_example_count: Mapped[int] = mapped_column(Integer, nullable=False)
    validation_metrics: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    test_metrics: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    candidate_results: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    readiness_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    source_manifest: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    fitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    research_only: Mapped[bool] = mapped_column(Boolean, nullable=False)
    operational_probability_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    automatic_trading_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)

    examples: Mapped[list[MlbFittedResearchModelExampleRecord]] = relationship(
        back_populates="model",
        lazy="selectin",
        order_by="MlbFittedResearchModelExampleRecord.ordinal",
    )


class MlbFittedResearchModelExampleRecord(Base):
    """Foreign-key-protected ordered lineage for one fitted research artifact."""

    __tablename__ = "mlb_fitted_research_model_examples"
    __table_args__ = (
        UniqueConstraint(
            "model_id",
            "example_id",
            name="uq_mlb_fitted_model_examples_example",
        ),
        UniqueConstraint(
            "model_id",
            "ordinal",
            name="uq_mlb_fitted_model_examples_ordinal",
        ),
        CheckConstraint("ordinal >= 0", name="ck_mlb_fitted_model_examples_ordinal"),
        CheckConstraint(
            "split IN ('train', 'validation', 'test')",
            name="ck_mlb_fitted_model_examples_split",
        ),
        CheckConstraint(
            "availability_basis IN ('operational_pregame', 'retrospective')",
            name="ck_mlb_fitted_model_examples_basis",
        ),
        CheckConstraint(
            "example_fingerprint ~ '^[0-9a-f]{64}$' AND research_only = true",
            name="ck_mlb_fitted_model_examples_safety",
        ),
        Index(
            "ix_mlb_fitted_model_examples_model_split_ordinal",
            "model_id",
            "split",
            "ordinal",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    model_id: Mapped[UUID] = mapped_column(
        ForeignKey("mlb_fitted_research_models.id", ondelete="RESTRICT"), nullable=False
    )
    example_id: Mapped[UUID] = mapped_column(
        ForeignKey("mlb_labeled_feature_examples.id", ondelete="RESTRICT"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    split: Mapped[str] = mapped_column(String(30), nullable=False)
    availability_basis: Mapped[str] = mapped_column(String(30), nullable=False)
    example_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    research_only: Mapped[bool] = mapped_column(Boolean, nullable=False)

    model: Mapped[MlbFittedResearchModelRecord] = relationship(back_populates="examples")
    example: Mapped[MlbLabeledFeatureExampleRecord] = relationship(lazy="joined")


class MlbBackfillCheckpointRecord(Base):
    """Mutable cursor projection for the approved historical MLB research workflow."""

    __tablename__ = "mlb_backfill_checkpoints"
    __table_args__ = (
        UniqueConstraint("policy_fingerprint", name="uq_mlb_backfill_checkpoints_policy"),
        CheckConstraint(
            "status IN ('active', 'complete', 'exhausted')",
            name="ck_mlb_backfill_checkpoints_status",
        ),
        CheckConstraint(
            "regular_season_start < validation_start_date "
            "AND validation_start_date < test_start_date "
            "AND test_start_date < prospective_holdout_start_date",
            name="ck_mlb_backfill_checkpoints_boundaries",
        ),
        CheckConstraint(
            "train_cursor_date BETWEEN regular_season_start - 1 "
            "AND validation_start_date - 1 "
            "AND validation_cursor_date BETWEEN regular_season_start - 1 "
            "AND test_start_date - 1 "
            "AND test_cursor_date BETWEEN regular_season_start - 1 "
            "AND prospective_holdout_start_date - 1",
            name="ck_mlb_backfill_checkpoints_cursors",
        ),
        CheckConstraint(
            "train_cursor_offset >= 0 AND validation_cursor_offset >= 0 "
            "AND test_cursor_offset >= 0 AND batch_limit BETWEEN 1 AND 10",
            name="ck_mlb_backfill_checkpoints_offsets",
        ),
        CheckConstraint(
            "version >= 0 AND batches_completed >= 0 AND events_examined >= 0 "
            "AND examples_created >= 0",
            name="ck_mlb_backfill_checkpoints_counts",
        ),
        CheckConstraint(
            "(status = 'active' AND finished_at IS NULL) "
            "OR (status IN ('complete', 'exhausted') AND finished_at IS NOT NULL)",
            name="ck_mlb_backfill_checkpoints_terminal",
        ),
        CheckConstraint(
            "research_only = true AND probability_generated = false "
            "AND automatic_trading_eligible = false",
            name="ck_mlb_backfill_checkpoints_safety",
        ),
        CheckConstraint(
            "policy_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND split_policy_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND state_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_mlb_backfill_checkpoints_fingerprints",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    policy_name: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    split_policy_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    regular_season_start: Mapped[date] = mapped_column(Date, nullable=False)
    validation_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    test_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    prospective_holdout_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    train_cursor_date: Mapped[date] = mapped_column(Date, nullable=False)
    train_cursor_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    validation_cursor_date: Mapped[date] = mapped_column(Date, nullable=False)
    validation_cursor_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    test_cursor_date: Mapped[date] = mapped_column(Date, nullable=False)
    test_cursor_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    batches_completed: Mapped[int] = mapped_column(Integer, nullable=False)
    events_examined: Mapped[int] = mapped_column(Integer, nullable=False)
    examples_created: Mapped[int] = mapped_column(Integer, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    research_only: Mapped[bool] = mapped_column(Boolean, nullable=False)
    probability_generated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    automatic_trading_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class MlbBackfillBatchRecord(Base):
    """Append-only audit fact for one successfully checkpointed historical batch."""

    __tablename__ = "mlb_backfill_batches"
    __table_args__ = (
        UniqueConstraint("checkpoint_id", "sequence", name="uq_mlb_backfill_batches_sequence"),
        UniqueConstraint(
            "checkpoint_id", "input_fingerprint", name="uq_mlb_backfill_batches_input"
        ),
        CheckConstraint(
            "split IN ('train', 'validation', 'test')",
            name="ck_mlb_backfill_batches_split",
        ),
        CheckConstraint(
            "sequence >= 1 AND batch_offset >= 0 AND batch_limit BETWEEN 1 AND 10",
            name="ck_mlb_backfill_batches_cursor",
        ),
        CheckConstraint(
            "events_refreshed >= 0 AND examined >= 0 "
            "AND retrospective_vectors_built >= 0 AND examples_labeled >= 0 "
            "AND examples_created >= 0 AND examples_created <= examples_labeled",
            name="ck_mlb_backfill_batches_counts",
        ),
        CheckConstraint(
            "jsonb_typeof(result_counts) = 'object' "
            "AND jsonb_typeof(event_results) = 'array' "
            "AND jsonb_typeof(readiness_before) = 'object' "
            "AND jsonb_typeof(readiness_after) = 'object'",
            name="ck_mlb_backfill_batches_json",
        ),
        CheckConstraint(
            "research_only = true AND probability_generated = false "
            "AND automatic_trading_eligible = false",
            name="ck_mlb_backfill_batches_safety",
        ),
        CheckConstraint(
            "input_fingerprint ~ '^[0-9a-f]{64}$' AND result_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_mlb_backfill_batches_fingerprints",
        ),
        Index("ix_mlb_backfill_batches_checkpoint_run", "checkpoint_id", "run_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    checkpoint_id: Mapped[UUID] = mapped_column(
        ForeignKey("mlb_backfill_checkpoints.id", ondelete="RESTRICT"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    split: Mapped[str] = mapped_column(String(30), nullable=False)
    window_date: Mapped[date] = mapped_column(Date, nullable=False)
    offset: Mapped[int] = mapped_column("batch_offset", Integer, nullable=False)
    batch_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    cursor_date_after: Mapped[date] = mapped_column(Date, nullable=False)
    cursor_offset_after: Mapped[int] = mapped_column(Integer, nullable=False)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    events_refreshed: Mapped[int] = mapped_column(Integer, nullable=False)
    examined: Mapped[int] = mapped_column(Integer, nullable=False)
    retrospective_vectors_built: Mapped[int] = mapped_column(Integer, nullable=False)
    examples_labeled: Mapped[int] = mapped_column(Integer, nullable=False)
    examples_created: Mapped[int] = mapped_column(Integer, nullable=False)
    result_counts: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False)
    event_results: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    readiness_before: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    readiness_after: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    research_only: Mapped[bool] = mapped_column(Boolean, nullable=False)
    probability_generated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    automatic_trading_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    checkpoint: Mapped[MlbBackfillCheckpointRecord] = relationship(lazy="joined")
