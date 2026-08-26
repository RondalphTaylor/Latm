from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import Table

from app.api.mlb_dataset_quality import (
    get_mlb_dataset_quality_repository,
    get_mlb_dataset_quality_service,
)
from app.domain.mlb_dataset_quality import (
    MlbDatasetQualityInput,
    MlbDatasetQualityPolicy,
)
from app.domain.mlb_modeling import (
    MlbDatasetReadinessInput,
    MlbFeatureSelectionPolicy,
    approved_mlb_dataset_readiness_policy,
)
from app.main import create_app
from app.models.mlb import (
    MlbDatasetQualityAuditExampleRecord,
    MlbDatasetQualityAuditRecord,
)
from app.services.mlb_modeling.engine import (
    DeterministicMlbDatasetReadinessEngine,
    mlb_chronological_split_policy_fingerprint,
    mlb_feature_selection_policy_fingerprint,
)
from app.services.mlb_modeling.quality import DeterministicMlbDatasetQualityEngine
from app.services.mlb_modeling.quality_service import MlbDatasetQualityAuditResult

AUDIT_ID = UUID("92000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 8, 26, 16, 30, tzinfo=UTC)


def _audit_record() -> MlbDatasetQualityAuditRecord:
    readiness_policy = approved_mlb_dataset_readiness_policy()
    split_fingerprint = mlb_chronological_split_policy_fingerprint(readiness_policy.split_policy)
    report = DeterministicMlbDatasetQualityEngine().evaluate(
        MlbDatasetQualityInput(
            split_policy_fingerprint=split_fingerprint,
            split_policy=readiness_policy.split_policy,
            feature_policy_fingerprint=mlb_feature_selection_policy_fingerprint(
                MlbFeatureSelectionPolicy()
            ),
            examples=(),
            policy=MlbDatasetQualityPolicy(),
        )
    )
    readiness = DeterministicMlbDatasetReadinessEngine().evaluate(
        MlbDatasetReadinessInput(
            split_policy_fingerprint=split_fingerprint,
            operational_split_counts={},
            retrospective_split_counts={},
            policy=readiness_policy,
        )
    )
    return MlbDatasetQualityAuditRecord(
        id=AUDIT_ID,
        policy_name=report.policy_name,
        policy_version=report.policy_version,
        policy_fingerprint=report.policy_fingerprint,
        readiness_policy_fingerprint=readiness.policy_fingerprint,
        split_policy_fingerprint=report.split_policy_fingerprint,
        feature_policy_fingerprint=report.feature_policy_fingerprint,
        source_data_fingerprint=report.source_data_fingerprint,
        report_fingerprint="a" * 64,
        input_fingerprint=report.input_fingerprint,
        selected_example_count=0,
        operational_example_count=0,
        retrospective_example_count=0,
        unique_event_count=0,
        unique_team_count=0,
        home_win_count=0,
        away_win_count=0,
        error_count=0,
        warning_count=1,
        quality_passed=True,
        first_scheduled_start_time=None,
        last_scheduled_start_time=None,
        report=report.model_dump(mode="json"),
        readiness_snapshot=readiness.model_dump(mode="json"),
        source_manifest=[],
        evaluated_at=NOW,
        research_only=True,
        probability_generated=False,
        automatic_trading_eligible=False,
        examples=[],
    )


class AuditService:
    async def run(self) -> MlbDatasetQualityAuditResult:
        return MlbDatasetQualityAuditResult(created=True, audit=_audit_record())


class EmptyAuditRepository:
    async def list_audits(self, **_: object) -> list[object]:
        return []

    async def get_audit(self, _: UUID) -> None:
        return None


def test_quality_run_is_parameterless_research_only_and_exposes_readiness_separately() -> None:
    app = create_app()
    app.dependency_overrides[get_mlb_dataset_quality_service] = AuditService
    with TestClient(app) as client:
        response = client.post("/mlb-dataset-quality-audits/run")
        operation = client.get("/openapi.json").json()["paths"]["/mlb-dataset-quality-audits/run"][
            "post"
        ]

    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    assert body["audit"]["report"]["quality_passed"] is True
    assert body["audit"]["report"]["selected_example_count"] == 0
    assert body["audit"]["readiness_snapshot"]["exploratory_fit_data_ready"] is False
    assert body["audit"]["probability_generated"] is False
    assert body["audit"]["automatic_trading_eligible"] is False
    assert "requestBody" not in operation
    assert "parameters" not in operation


def test_quality_reads_are_bounded_and_missing_detail_is_404() -> None:
    app = create_app()
    app.dependency_overrides[get_mlb_dataset_quality_repository] = EmptyAuditRepository
    with TestClient(app) as client:
        listed = client.get("/mlb-dataset-quality-audits?limit=10&offset=0")
        invalid = client.get("/mlb-dataset-quality-audits?limit=101")
        missing = client.get(f"/mlb-dataset-quality-audits/{AUDIT_ID}")

    assert listed.status_code == 200
    assert listed.json() == []
    assert invalid.status_code == 422
    assert missing.status_code == 404


def test_quality_tables_enforce_lineage_identity_and_research_safety() -> None:
    audit_table = cast(Table, MlbDatasetQualityAuditRecord.__table__)
    lineage_table = cast(Table, MlbDatasetQualityAuditExampleRecord.__table__)
    audit_constraints = {item.name for item in audit_table.constraints}
    lineage_constraints = {item.name for item in lineage_table.constraints}

    assert {
        "uq_mlb_dataset_quality_audits_input",
        "ck_mlb_dataset_quality_audits_reconciliation",
        "ck_mlb_dataset_quality_audits_json",
        "ck_mlb_dataset_quality_audits_safety",
    } <= audit_constraints
    assert {
        "uq_mlb_dataset_quality_audit_examples_example",
        "uq_mlb_dataset_quality_audit_examples_ordinal",
        "ck_mlb_dataset_quality_audit_examples_roles",
        "ck_mlb_dataset_quality_audit_examples_safety",
    } <= lineage_constraints
