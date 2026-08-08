from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from app.domain.matching import CandidateScore, MarketEventMatchStatus, TeamSignal
from app.models.matching import MarketEventMatchRecord

_EVIDENCE_ADAPTER = TypeAdapter(dict[str, JsonValue])


class MarketEventMatchResponse(BaseModel):
    """Typed matching decision without raw provider payloads."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    market_id: UUID
    sports_event_id: UUID | None
    status: MarketEventMatchStatus
    confidence: Annotated[Decimal, Field(ge=Decimal("0"), le=Decimal("1"))]
    method: str
    reason: str
    matcher_version: str
    min_confidence: Decimal
    ambiguity_margin: Decimal
    time_window_hours: int
    automatic_trading_eligible: bool
    input_fingerprint: str
    team_signals: tuple[TeamSignal, ...]
    candidate_scores: tuple[CandidateScore, ...]
    evidence: dict[str, JsonValue]
    evaluated_at: datetime

    @classmethod
    def from_record(cls, record: MarketEventMatchRecord) -> MarketEventMatchResponse:
        """Validate persisted JSON audit fields before returning them."""
        return cls(
            id=record.id,
            market_id=record.market_id,
            sports_event_id=record.sports_event_id,
            status=MarketEventMatchStatus(record.status),
            confidence=record.confidence,
            method=record.method,
            reason=record.reason,
            matcher_version=record.matcher_version,
            min_confidence=record.min_confidence,
            ambiguity_margin=record.ambiguity_margin,
            time_window_hours=record.time_window_hours,
            automatic_trading_eligible=record.automatic_trading_eligible,
            input_fingerprint=record.input_fingerprint,
            team_signals=tuple(TeamSignal.model_validate(item) for item in record.team_signals),
            candidate_scores=tuple(
                CandidateScore.model_validate(item) for item in record.candidate_scores
            ),
            evidence=_EVIDENCE_ADAPTER.validate_python(record.evidence),
            evaluated_at=record.evaluated_at,
        )


class MatchingRunResponse(BaseModel):
    """Counts returned by a bounded local matching run."""

    model_config = ConfigDict(frozen=True)

    matcher_version: str
    start_date: date
    end_date: date
    examined: int
    persisted: int
    matched: int
    ambiguous: int
    unmatched: int
