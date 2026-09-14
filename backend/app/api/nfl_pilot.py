import csv
import hashlib
import io
import json
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, TradingMode, get_settings
from app.db.session import get_session
from app.services.nfl_pilot.entries import NflPilotEntryService
from app.services.nfl_pilot.lifecycle import NflPilotLifecycleService
from app.services.nfl_pilot.service import NflPilotScenarioService

router = APIRouter(tags=["nfl-paper-pilot"])


class NflPilotScenarioResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)
    id: UUID
    portfolio_id: UUID
    profile: str
    starting_bankroll: Decimal
    per_entry_exposure: Decimal
    aggregate_exposure: Decimal
    live_trading_enabled: bool


class NflPilotEntryResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)
    id: UUID
    scenario_id: UUID
    preflight_id: UUID
    entered_at: datetime
    status: str
    direction: str
    quantity: int
    total_cost: Decimal
    adjusted_edge: Decimal
    entry_cap: Decimal
    aggregate_cap: Decimal
    execution_mode: str
    live_trading_enabled: bool
    warnings: tuple[str, ...] = (
        "This is a simulated NFL paper entry, not a provider order or live position.",
        "NFL promotion to live trading remains blocked.",
    )


class NflPilotEntryRunResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    created: bool
    entry: NflPilotEntryResponse


class NflPilotPositionEventResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)
    id: UUID
    position_id: UUID
    event_type: str
    mark_price: Decimal | None
    market_value: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    recorded_at: datetime
    execution_mode: str
    live_trading_enabled: bool
    warnings: tuple[str, ...] = (
        "This is an NFL paper-ledger event, not a provider order or live position.",
    )


class NflPilotPositionEventRunResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    created: bool
    event: NflPilotPositionEventResponse


class NflPilotDispositionEventResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)
    id: UUID
    decision_id: UUID
    position_id: UUID
    action: str
    quantity: int
    execution_price: Decimal
    gross_proceeds: Decimal
    allocated_cost_basis: Decimal
    realized_pnl_increment: Decimal
    recorded_at: datetime
    execution_mode: str
    live_trading_enabled: bool
    warnings: tuple[str, ...] = (
        "This is a simulated NFL paper disposition, not a provider order or live position.",
        "The action was revalidated against the same fresh immutable recommendation evidence.",
    )


class NflPilotDispositionRunResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    created: bool
    disposition: NflPilotDispositionEventResponse


class NflPilotPositionResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)
    id: UUID
    entry_id: UUID
    scenario_id: UUID
    market_id: UUID
    direction: str
    quantity: int
    remaining_quantity: int
    disposed_quantity: int
    total_cost_basis: Decimal
    remaining_cost_basis: Decimal
    status: str
    mark_price: Decimal | None
    market_value: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    updated_at: datetime
    execution_mode: str
    live_trading_enabled: bool


class NflPilotLedgerResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    open_positions: int
    settled_positions: int
    committed_capital: Decimal
    realized_pnl: Decimal
    current_bankroll: Decimal
    available_bankroll: Decimal


class NflPilotMonitorResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    examined: int
    quote_checks_created: int
    fresh: int
    stale: int
    unusable: int
    missing: int
    marks_created: int
    skipped: int
    holds: int
    reduces: int
    closes: int
    attention_required: int


class NflPilotMonitoringDecisionResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)
    id: UUID
    position_id: UUID
    recommendation: str
    reason: str
    requires_attention: bool
    remaining_edge: Decimal | None
    evaluated_at: datetime


class NflPilotRecommendationAuditResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    decision_id: UUID
    position_id: UUID
    recommendation: str
    reason: str
    requires_attention: bool
    remaining_edge: Decimal | None
    evaluated_at: datetime
    quote_status: str | None
    quote_age_seconds: int | None
    quote_retrieved_at: datetime | None
    forecast_id: UUID | None
    forecast_valid_until: datetime | None
    forecast_valid_at_decision: bool | None
    disposition_action: str | None
    disposition_recorded_at: datetime | None


class NflPilotRecommendationAuditSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    total: int
    hold: int
    reduce: int
    close: int
    attention_required: int


class NflPilotRecommendationAuditExportMetadataResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    generated_at: datetime
    scenario_id: UUID
    recommendation_filter: str | None
    limit: int
    offset: int
    row_count: int
    scenario_policy_version: str
    scenario_policy_fingerprint: str
    retention_policy_version: str
    export_fingerprint: str


class NflPilotRecommendationAuditVerificationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    provided_fingerprint: str
    current_fingerprint: str
    matches: bool
    row_count: int
    scenario_policy_version: str
    scenario_policy_fingerprint: str
    retention_policy_version: str


def _audit_export_fingerprint(
    metadata: dict[str, object], payload: list[NflPilotRecommendationAuditResponse]
) -> str:
    """Hash the export's semantic slice, deliberately excluding wall-clock generation time."""
    canonical = {
        "schema_version": "nfl-pilot-audit-export-v1",
        "scenario_id": str(metadata["scenario_id"]),
        "recommendation_filter": metadata["recommendation_filter"],
        "limit": metadata["limit"],
        "offset": metadata["offset"],
        "row_count": metadata["row_count"],
        "scenario_policy_version": metadata["scenario_policy_version"],
        "scenario_policy_fingerprint": metadata["scenario_policy_fingerprint"],
        "retention_policy_version": metadata["retention_policy_version"],
        "records": [item.model_dump(mode="json") for item in payload],
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


async def _audit_export_slice(
    session: AsyncSession,
    scenario_id: UUID,
    recommendation: str | None,
    limit: int,
    offset: int,
) -> tuple[
    NflPilotRecommendationAuditExportMetadataResponse, list[NflPilotRecommendationAuditResponse]
]:
    service = NflPilotLifecycleService(session)
    records = await service.recommendation_audit(scenario_id, recommendation, limit, offset)
    payload = [NflPilotRecommendationAuditResponse.model_validate(record) for record in records]
    metadata_values = await service.recommendation_audit_export_metadata(
        scenario_id, recommendation, limit, offset, len(payload)
    )
    metadata = NflPilotRecommendationAuditExportMetadataResponse.model_validate(
        metadata_values
        | {"export_fingerprint": _audit_export_fingerprint(metadata_values, payload)}
    )
    return metadata, payload


class NflPilotAlertResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)
    id: UUID
    decision_id: UUID
    severity: str
    message: str
    created_at: datetime


@router.post("/nfl-pilot-scenarios/register", response_model=NflPilotScenarioResponse)
async def register_nfl_pilot_scenario(
    portfolio_id: UUID,
    profile: Annotated[Literal["conservative", "baseline", "assertive"], Query()],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> NflPilotScenarioResponse:
    if settings.trading_mode is not TradingMode.PAPER:
        raise HTTPException(status_code=409, detail="NFL pilot scenarios require paper mode")
    try:
        record, _ = await NflPilotScenarioService(session).register(portfolio_id, profile)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return NflPilotScenarioResponse.model_validate(record)


@router.post("/nfl-pilot-entries/run", response_model=NflPilotEntryRunResponse)
async def run_nfl_pilot_entry(
    scenario_id: UUID,
    preflight_id: UUID,
    idempotency_key: Annotated[str, Query(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> NflPilotEntryRunResponse:
    """Create one independently auditable simulated NFL entry from a fresh preflight."""
    if settings.trading_mode is not TradingMode.PAPER:
        raise HTTPException(status_code=409, detail="NFL pilot entries require paper mode")
    try:
        record, created = await NflPilotEntryService(session).run(
            scenario_id, preflight_id, idempotency_key
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return NflPilotEntryRunResponse(
        created=created, entry=NflPilotEntryResponse.model_validate(record)
    )


@router.post("/nfl-pilot-positions/mark", response_model=NflPilotPositionEventRunResponse)
async def mark_nfl_pilot_position(
    entry_id: UUID,
    idempotency_key: Annotated[str, Query(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> NflPilotPositionEventRunResponse:
    if settings.trading_mode is not TradingMode.PAPER:
        raise HTTPException(status_code=409, detail="NFL pilot position marks require paper mode")
    try:
        record, created = await NflPilotLifecycleService(session).mark(entry_id, idempotency_key)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return NflPilotPositionEventRunResponse(
        created=created, event=NflPilotPositionEventResponse.model_validate(record)
    )


@router.post("/nfl-pilot-positions/settle", response_model=NflPilotPositionEventRunResponse)
async def settle_nfl_pilot_position(
    entry_id: UUID,
    idempotency_key: Annotated[str, Query(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> NflPilotPositionEventRunResponse:
    if settings.trading_mode is not TradingMode.PAPER:
        raise HTTPException(status_code=409, detail="NFL pilot settlement requires paper mode")
    try:
        record, created = await NflPilotLifecycleService(session).settle(entry_id, idempotency_key)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return NflPilotPositionEventRunResponse(
        created=created, event=NflPilotPositionEventResponse.model_validate(record)
    )


@router.post("/nfl-pilot-dispositions/run", response_model=NflPilotDispositionRunResponse)
async def run_nfl_pilot_disposition(
    decision_id: UUID,
    idempotency_key: Annotated[str, Query(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> NflPilotDispositionRunResponse:
    """Apply a still-current immutable REDUCE/CLOSE recommendation to the paper ledger only."""
    if settings.trading_mode is not TradingMode.PAPER:
        raise HTTPException(status_code=409, detail="NFL pilot dispositions require paper mode")
    try:
        record, created = await NflPilotLifecycleService(session).dispose(
            decision_id, idempotency_key
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return NflPilotDispositionRunResponse(
        created=created, disposition=NflPilotDispositionEventResponse.model_validate(record)
    )


@router.get("/nfl-pilot-scenarios/{scenario_id}/ledger", response_model=NflPilotLedgerResponse)
async def get_nfl_pilot_ledger(
    scenario_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NflPilotLedgerResponse:
    try:
        result = await NflPilotLifecycleService(session).summary(scenario_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return NflPilotLedgerResponse.model_validate(result)


@router.get("/nfl-pilot-monitor/decisions", response_model=list[NflPilotMonitoringDecisionResponse])
async def list_nfl_pilot_monitoring_decisions(
    scenario_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    attention_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[NflPilotMonitoringDecisionResponse]:
    records = await NflPilotLifecycleService(session).decisions(
        scenario_id, attention_only, limit, offset
    )
    return [NflPilotMonitoringDecisionResponse.model_validate(record) for record in records]


@router.get("/nfl-pilot-monitor/audit", response_model=list[NflPilotRecommendationAuditResponse])
async def list_nfl_pilot_recommendation_audit(
    scenario_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    recommendation: Annotated[Literal["hold", "reduce", "close"] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=25)] = 8,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[NflPilotRecommendationAuditResponse]:
    """Read immutable recommendation evidence and any linked paper disposition."""
    records = await NflPilotLifecycleService(session).recommendation_audit(
        scenario_id, recommendation, limit, offset
    )
    return [NflPilotRecommendationAuditResponse.model_validate(record) for record in records]


@router.get(
    "/nfl-pilot-monitor/audit/summary",
    response_model=NflPilotRecommendationAuditSummaryResponse,
)
async def get_nfl_pilot_recommendation_audit_summary(
    scenario_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NflPilotRecommendationAuditSummaryResponse:
    """Read scenario-level immutable recommendation counts for audit review."""
    summary = await NflPilotLifecycleService(session).recommendation_audit_summary(scenario_id)
    return NflPilotRecommendationAuditSummaryResponse.model_validate(summary)


@router.get("/nfl-pilot-monitor/audit/export")
async def export_nfl_pilot_recommendation_audit(
    scenario_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    format: Annotated[Literal["csv", "json"], Query()] = "csv",
    recommendation: Annotated[Literal["hold", "reduce", "close"] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> Response:
    """Download a bounded immutable audit slice; this endpoint never performs a disposition."""
    try:
        metadata, payload = await _audit_export_slice(
            session, scenario_id, recommendation, limit, offset
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    filename = f"nfl-pilot-audit-{scenario_id}-{offset}.{format}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if format == "json":
        return Response(
            content=json.dumps(
                {
                    "metadata": metadata.model_dump(mode="json"),
                    "records": [item.model_dump(mode="json") for item in payload],
                }
            ),
            media_type="application/json",
            headers=headers,
        )
    buffer = io.StringIO(newline="")
    fields = tuple(NflPilotRecommendationAuditExportMetadataResponse.model_fields) + tuple(
        NflPilotRecommendationAuditResponse.model_fields
    )
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    metadata_values = metadata.model_dump(mode="json")
    writer.writerows(metadata_values | item.model_dump(mode="json") for item in payload)
    return Response(content=buffer.getvalue(), media_type="text/csv", headers=headers)


@router.get(
    "/nfl-pilot-monitor/audit/verify",
    response_model=NflPilotRecommendationAuditVerificationResponse,
)
async def verify_nfl_pilot_recommendation_audit_export(
    scenario_id: UUID,
    fingerprint: Annotated[str, Query(pattern="^[0-9a-fA-F]{64}$")],
    session: Annotated[AsyncSession, Depends(get_session)],
    recommendation: Annotated[Literal["hold", "reduce", "close"] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> NflPilotRecommendationAuditVerificationResponse:
    """Compare a pasted export fingerprint with the current bounded immutable audit slice."""
    try:
        metadata, _ = await _audit_export_slice(session, scenario_id, recommendation, limit, offset)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return NflPilotRecommendationAuditVerificationResponse(
        provided_fingerprint=fingerprint.lower(),
        current_fingerprint=metadata.export_fingerprint,
        matches=fingerprint.lower() == metadata.export_fingerprint,
        row_count=metadata.row_count,
        scenario_policy_version=metadata.scenario_policy_version,
        scenario_policy_fingerprint=metadata.scenario_policy_fingerprint,
        retention_policy_version=metadata.retention_policy_version,
    )


@router.get(
    "/nfl-pilot-monitor/audit/{decision_id}",
    response_model=NflPilotRecommendationAuditResponse,
)
async def get_nfl_pilot_recommendation_audit_detail(
    decision_id: UUID,
    scenario_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NflPilotRecommendationAuditResponse:
    """Read one immutable decision lineage; this endpoint has no execution behavior."""
    record = await NflPilotLifecycleService(session).recommendation_audit_detail(
        scenario_id, decision_id
    )
    if record is None:
        raise HTTPException(
            status_code=404, detail="NFL pilot audit decision not found in scenario"
        )
    return NflPilotRecommendationAuditResponse.model_validate(record)


@router.get("/nfl-pilot-monitor/attention", response_model=list[NflPilotMonitoringDecisionResponse])
async def list_nfl_pilot_attention(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=25)] = 8,
) -> list[NflPilotMonitoringDecisionResponse]:
    records = await NflPilotLifecycleService(session).attention(limit)
    return [NflPilotMonitoringDecisionResponse.model_validate(record) for record in records]


@router.get("/nfl-pilot-alerts", response_model=list[NflPilotAlertResponse])
async def list_nfl_pilot_alerts(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=25)] = 8,
) -> list[NflPilotAlertResponse]:
    records = await NflPilotLifecycleService(session).alerts(limit)
    return [NflPilotAlertResponse.model_validate(record) for record in records]


@router.get("/nfl-pilot-dispositions", response_model=list[NflPilotDispositionEventResponse])
async def list_nfl_pilot_dispositions(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=25)] = 8,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[NflPilotDispositionEventResponse]:
    """Expose immutable simulated exits for observational dashboard use only."""
    records = await NflPilotLifecycleService(session).dispositions(limit, offset)
    return [NflPilotDispositionEventResponse.model_validate(record) for record in records]


@router.get("/nfl-pilot-positions", response_model=list[NflPilotPositionResponse])
async def list_nfl_pilot_positions(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=25)] = 8,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[NflPilotPositionResponse]:
    """Expose the isolated paper-pilot projection without an execution capability."""
    records = await NflPilotLifecycleService(session).positions(limit, offset)
    return [NflPilotPositionResponse.model_validate(record) for record in records]


@router.post("/nfl-pilot-monitor/run", response_model=NflPilotMonitorResponse)
async def run_nfl_pilot_monitor(
    scenario_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> NflPilotMonitorResponse:
    if settings.trading_mode is not TradingMode.PAPER:
        raise HTTPException(status_code=409, detail="NFL pilot monitoring requires paper mode")
    try:
        (
            examined,
            quote_checks_created,
            fresh,
            stale,
            unusable,
            missing,
            marks_created,
            skipped,
            holds,
            reduces,
            closes,
            attention_required,
        ) = await NflPilotLifecycleService(session).monitor(scenario_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return NflPilotMonitorResponse(
        examined=examined,
        quote_checks_created=quote_checks_created,
        fresh=fresh,
        stale=stale,
        unusable=unusable,
        missing=missing,
        marks_created=marks_created,
        skipped=skipped,
        holds=holds,
        reduces=reduces,
        closes=closes,
        attention_required=attention_required,
    )
