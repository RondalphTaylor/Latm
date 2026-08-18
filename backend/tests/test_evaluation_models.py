from __future__ import annotations

from decimal import Decimal
from typing import cast

from sqlalchemy import CheckConstraint, Numeric, Table, UniqueConstraint

from app.models.evaluation import ForecastEvaluationRecord


def test_forecast_evaluation_schema_freezes_exact_binary_score_facts() -> None:
    table = cast(Table, ForecastEvaluationRecord.__table__)
    constraints = {constraint.name for constraint in table.constraints}

    assert {
        "uq_forecast_evaluations_semantic_input",
        "ck_forecast_evaluations_purpose",
        "ck_forecast_evaluations_distinct_teams",
        "ck_forecast_evaluations_result",
        "ck_forecast_evaluations_prediction",
        "ck_forecast_evaluations_brier",
        "ck_forecast_evaluations_correctness",
        "ck_forecast_evaluations_cutoff",
        "ck_forecast_evaluations_times",
        "ck_forecast_evaluations_fingerprints",
        "ck_forecast_evaluations_source_snapshot",
    } <= constraints
    assert {
        "base_forecast_id",
        "sports_event_id",
        "model_version_id",
        "home_team_id",
        "away_team_id",
        "home_win_probability",
        "home_won",
        "brier_score",
        "outcome_fingerprint",
        "audit_snapshot",
    } <= set(table.columns.keys())

    brier_type = cast(Numeric[Decimal], table.c.brier_score.type)
    assert brier_type.precision == 14
    assert brier_type.scale == 12
    assert table.c.predicted_home_win.nullable is True
    assert table.c.correct.nullable is True
    assert table.c.audit_snapshot.nullable is False
    assert ForecastEvaluationRecord.model_version.property.lazy == "joined"


def test_forecast_evaluation_lineage_and_semantic_indexes_are_explicit() -> None:
    table = cast(Table, ForecastEvaluationRecord.__table__)
    foreign_key_targets = {foreign_key.target_fullname for foreign_key in table.foreign_keys}
    assert foreign_key_targets == {
        "base_forecasts.id",
        "sports_events.id",
        "model_versions.id",
        "teams.id",
    }

    semantic_unique = next(
        constraint
        for constraint in table.constraints
        if constraint.name == "uq_forecast_evaluations_semantic_input"
    )
    assert isinstance(semantic_unique, UniqueConstraint)
    assert [column.name for column in semantic_unique.columns] == [
        "base_forecast_id",
        "policy_version",
        "input_fingerprint",
    ]
    assert {index.name for index in table.indexes} == {
        "ix_forecast_evaluations_event_evaluated",
        "ix_forecast_evaluations_model_purpose_event_date",
        "ix_forecast_evaluations_purpose_event_date",
    }


def test_forecast_evaluation_checks_encode_cutoff_result_and_exact_brier_rules() -> None:
    table = cast(Table, ForecastEvaluationRecord.__table__)
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "forecast_as_of = forecast_generated_at" in checks["ck_forecast_evaluations_cutoff"]
    assert (
        "forecast_as_of = result_scheduled_start_time" in checks["ck_forecast_evaluations_cutoff"]
    )
    assert "result_home_score > result_away_score" in checks["ck_forecast_evaluations_result"]
    assert "CASE WHEN home_won THEN 1 ELSE 0 END" in checks["ck_forecast_evaluations_brier"]
    assert (
        "predicted_home_win IS NULL AND correct IS NULL"
        in checks["ck_forecast_evaluations_correctness"]
    )
    assert "home_win_probability = 0.5" in checks["ck_forecast_evaluations_prediction"]
    assert "predicted_home_win IS TRUE" in checks["ck_forecast_evaluations_prediction"]
    assert "correct IS NOT NULL" in checks["ck_forecast_evaluations_correctness"]
