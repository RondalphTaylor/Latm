from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import cast
from uuid import UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.mlb_dataset_quality import (
    MlbDatasetQualityExample,
    MlbDatasetQualityReport,
)
from app.domain.mlb_modeling import MlbDatasetReadinessAssessment
from app.models.mlb import (
    MlbDatasetQualityAuditExampleRecord,
    MlbDatasetQualityAuditRecord,
)

_NAMESPACE = UUID("30654709-239f-48c2-abd0-75221724b84a")


def _canonical_hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def mlb_dataset_quality_audit_record_id(input_fingerprint: str) -> UUID:
    return uuid5(_NAMESPACE, f"audit:{input_fingerprint}")


def mlb_dataset_quality_audit_example_record_id(audit_id: UUID, example_id: UUID) -> UUID:
    return uuid5(_NAMESPACE, f"lineage:{audit_id}:{example_id}")


class MlbDatasetQualityRepository:
    """Persist immutable quality reports and their exact canonical example lineage."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def database_time(self) -> datetime:
        value = await self._session.scalar(select(func.clock_timestamp()))
        if value is None:
            raise RuntimeError("database clock did not return a timestamp")
        return cast(datetime, value)

    @staticmethod
    def _manifest(examples: tuple[MlbDatasetQualityExample, ...]) -> list[dict[str, object]]:
        ordered = sorted(
            examples,
            key=lambda item: (item.scheduled_start_time, item.sports_event_id, item.example_id),
        )
        return [
            {
                "ordinal": ordinal,
                "example_id": str(example.example_id),
                "game_feature_vector_id": str(example.game_feature_vector_id),
                "sports_event_id": str(example.sports_event_id),
                "scheduled_start_time": example.scheduled_start_time.isoformat(),
                "split": example.split.value,
                "availability_basis": example.availability_basis.value,
                "feature_vector_input_fingerprint": (example.feature_vector_input_fingerprint),
                "outcome_fingerprint": example.outcome_fingerprint,
                "example_fingerprint": example.example_fingerprint,
            }
            for ordinal, example in enumerate(ordered)
        ]

    async def persist_audit(
        self,
        *,
        report: MlbDatasetQualityReport,
        readiness: MlbDatasetReadinessAssessment,
        examples: tuple[MlbDatasetQualityExample, ...],
        evaluated_at: datetime,
    ) -> tuple[MlbDatasetQualityAuditRecord, bool]:
        manifest = self._manifest(examples)
        if len(manifest) != report.selected_example_count:
            raise ValueError("MLB quality audit lineage count is inconsistent")
        if _canonical_hash(manifest) != report.source_data_fingerprint:
            raise ValueError("MLB quality audit source manifest fingerprint changed")
        if readiness.split_policy_fingerprint != report.split_policy_fingerprint:
            raise ValueError("MLB quality audit readiness uses a different split policy")

        audit_id = mlb_dataset_quality_audit_record_id(report.input_fingerprint)
        report_json = report.model_dump(mode="json")
        report_fingerprint = _canonical_hash(report_json)
        values = {
            "id": audit_id,
            "policy_name": report.policy_name,
            "policy_version": report.policy_version,
            "policy_fingerprint": report.policy_fingerprint,
            "readiness_policy_fingerprint": readiness.policy_fingerprint,
            "split_policy_fingerprint": report.split_policy_fingerprint,
            "feature_policy_fingerprint": report.feature_policy_fingerprint,
            "source_data_fingerprint": report.source_data_fingerprint,
            "report_fingerprint": report_fingerprint,
            "input_fingerprint": report.input_fingerprint,
            "selected_example_count": report.selected_example_count,
            "operational_example_count": report.operational_example_count,
            "retrospective_example_count": report.retrospective_example_count,
            "unique_event_count": report.unique_event_count,
            "unique_team_count": report.unique_team_count,
            "home_win_count": report.home_win_count,
            "away_win_count": report.away_win_count,
            "error_count": report.error_count,
            "warning_count": report.warning_count,
            "quality_passed": report.quality_passed,
            "first_scheduled_start_time": report.first_scheduled_start_time,
            "last_scheduled_start_time": report.last_scheduled_start_time,
            "report": report_json,
            "readiness_snapshot": readiness.model_dump(mode="json"),
            "source_manifest": manifest,
            "evaluated_at": evaluated_at,
            "research_only": True,
            "probability_generated": False,
            "automatic_trading_eligible": False,
        }
        try:
            created_id = await self._session.scalar(
                insert(MlbDatasetQualityAuditRecord)
                .values(values)
                .on_conflict_do_nothing()
                .returning(MlbDatasetQualityAuditRecord.id)
            )
            created = created_id is not None
            record = await self._session.scalar(
                select(MlbDatasetQualityAuditRecord)
                .where(MlbDatasetQualityAuditRecord.input_fingerprint == report.input_fingerprint)
                .options(selectinload(MlbDatasetQualityAuditRecord.examples))
            )
            if record is None or (
                record.id != audit_id
                or record.report_fingerprint != report_fingerprint
                or record.source_data_fingerprint != report.source_data_fingerprint
            ):
                raise ValueError("MLB quality audit conflicts with persisted semantic identity")
            if created and examples:
                ordered = sorted(
                    examples,
                    key=lambda item: (
                        item.scheduled_start_time,
                        item.sports_event_id,
                        item.example_id,
                    ),
                )
                await self._session.execute(
                    insert(MlbDatasetQualityAuditExampleRecord).values(
                        [
                            {
                                "id": mlb_dataset_quality_audit_example_record_id(
                                    audit_id, example.example_id
                                ),
                                "audit_id": audit_id,
                                "example_id": example.example_id,
                                "ordinal": ordinal,
                                "split": example.split.value,
                                "availability_basis": example.availability_basis.value,
                                "example_fingerprint": example.example_fingerprint,
                                "feature_vector_input_fingerprint": (
                                    example.feature_vector_input_fingerprint
                                ),
                                "research_only": True,
                            }
                            for ordinal, example in enumerate(ordered)
                        ]
                    )
                )
            await self._session.commit()
        except Exception:
            await self._session.rollback()
            raise

        persisted = await self.get_audit(audit_id)
        if persisted is None:
            raise RuntimeError("persisted MLB dataset-quality audit could not be reloaded")
        if len(persisted.examples) != report.selected_example_count:
            raise RuntimeError("persisted MLB dataset-quality audit lineage is incomplete")
        return persisted, created

    async def list_audits(
        self,
        *,
        limit: int,
        offset: int,
    ) -> list[MlbDatasetQualityAuditRecord]:
        result = await self._session.scalars(
            select(MlbDatasetQualityAuditRecord)
            .options(selectinload(MlbDatasetQualityAuditRecord.examples))
            .order_by(
                MlbDatasetQualityAuditRecord.evaluated_at.desc(),
                MlbDatasetQualityAuditRecord.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return list(result.unique().all())

    async def get_audit(self, audit_id: UUID) -> MlbDatasetQualityAuditRecord | None:
        result = await self._session.scalars(
            select(MlbDatasetQualityAuditRecord)
            .where(MlbDatasetQualityAuditRecord.id == audit_id)
            .options(selectinload(MlbDatasetQualityAuditRecord.examples))
            .execution_options(populate_existing=True)
        )
        return result.unique().one_or_none()
