from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domain.mlb_dataset_quality import MlbDatasetQualityReport
from app.domain.mlb_modeling import MlbDatasetReadinessAssessment
from app.models.mlb import MlbDatasetQualityAuditRecord


class MlbDatasetQualityAuditResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    report: MlbDatasetQualityReport
    readiness_snapshot: MlbDatasetReadinessAssessment
    report_fingerprint: str
    example_ids: tuple[UUID, ...]
    evaluated_at: datetime
    research_only: Literal[True]
    probability_generated: Literal[False]
    automatic_trading_eligible: Literal[False]
    warnings: tuple[str, ...]

    @classmethod
    def from_record(cls, record: MlbDatasetQualityAuditRecord) -> MlbDatasetQualityAuditResponse:
        report = MlbDatasetQualityReport.model_validate(record.report)
        readiness = MlbDatasetReadinessAssessment.model_validate(record.readiness_snapshot)
        warnings = [
            "quality_passed means structural audit checks passed; it does not mean data thresholds are ready",
            "feature statistics are descriptive and do not publish an MLB probability",
        ]
        if readiness.blockers:
            warnings.append("approved dataset readiness still has sample-count blockers")
        if report.retrospective_example_count:
            warnings.append(
                "retrospective examples may support exploratory fitting but cannot establish live pregame performance"
            )
        return cls(
            id=record.id,
            report=report,
            readiness_snapshot=readiness,
            report_fingerprint=record.report_fingerprint,
            example_ids=tuple(link.example_id for link in record.examples),
            evaluated_at=record.evaluated_at,
            research_only=record.research_only,
            probability_generated=record.probability_generated,
            automatic_trading_eligible=record.automatic_trading_eligible,
            warnings=tuple(warnings),
        )


class MlbDatasetQualityAuditRunResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    created: bool
    audit: MlbDatasetQualityAuditResponse
