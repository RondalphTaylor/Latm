from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

Payout = Annotated[Decimal, Field(ge=0, le=1, decimal_places=6, allow_inf_nan=False)]
PayoutError = Annotated[Decimal, Field(ge=0, le=1, decimal_places=12, allow_inf_nan=False)]
Fingerprint = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class NflShadowScoringInput(BaseModel):
    """Immutable pregame research snapshot to score, never a position or order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: UUID
    event_id: UUID
    provider_event_id: str = Field(min_length=1, max_length=100)
    model_version: str = Field(min_length=1, max_length=100)
    seed_fingerprint: Fingerprint
    generated_at: AwareDatetime
    kickoff: AwareDatetime
    home_team_id: UUID
    away_team_id: UUID
    yes_team_id: UUID
    expected_home_payout: Payout
    expected_yes_payout: Payout

    @field_validator("generated_at", "kickoff")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @field_validator("expected_home_payout", "expected_yes_payout")
    @classmethod
    def normalize_payout(cls, value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.000001"))

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if self.home_team_id == self.away_team_id:
            raise ValueError("shadow snapshot requires distinct teams")
        if self.yes_team_id not in {self.home_team_id, self.away_team_id}:
            raise ValueError("YES team must belong to the shadow game")
        expected = (
            self.expected_home_payout
            if self.yes_team_id == self.home_team_id
            else Decimal("1") - self.expected_home_payout
        )
        if self.expected_yes_payout != expected:
            raise ValueError("shadow YES payout does not match selected team orientation")
        if self.generated_at >= self.kickoff:
            raise ValueError("shadow snapshot must be generated strictly before kickoff")
        return self


class NflShadowFinalResult(BaseModel):
    """Observed ordinary final-game scores, not exchange financial settlement."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: UUID
    provider_event_id: str = Field(min_length=1, max_length=100)
    scheduled_start: AwareDatetime
    home_team_id: UUID
    away_team_id: UUID
    home_score: int = Field(ge=0, strict=True)
    away_score: int = Field(ge=0, strict=True)
    source_last_seen: AwareDatetime
    status: Literal["final"]

    @field_validator("scheduled_start", "source_last_seen")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.home_team_id == self.away_team_id:
            raise ValueError("final NFL result requires distinct teams")
        if self.source_last_seen < self.scheduled_start:
            raise ValueError("final NFL result observation cannot precede kickoff")
        return self


class NflShadowLabel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot: NflShadowScoringInput
    result: NflShadowFinalResult
    evaluated_at: AwareDatetime
    actual_home_payout: Payout
    actual_yes_payout: Payout
    squared_home_payout_error: PayoutError
    constant_half_squared_error: PayoutError
    snapshot_fingerprint: Fingerprint
    result_fingerprint: Fingerprint
    label_fingerprint: Fingerprint
    evaluation_version: str
    research_only: Literal[True] = True
    trading_enabled: Literal[False] = False


class NflShadowCalibrationBin(BaseModel):
    model_config = ConfigDict(frozen=True)

    lower_bound: Payout
    upper_bound: Payout
    count: int
    mean_expected_payout: PayoutError | None
    mean_actual_payout: PayoutError | None


class NflShadowModelPerformance(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_version: str
    seed_fingerprint: Fingerprint
    count: int
    tie_count: int
    mean_squared_home_payout_error: PayoutError | None
    constant_half_mean_squared_error: PayoutError | None
    calibration_bins: tuple[NflShadowCalibrationBin, ...]


class NflShadowPerformanceSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    count: int
    model_groups: tuple[NflShadowModelPerformance, ...]
    # Convenience values are defined only for exactly one model/seed, never pooled.
    mean_squared_home_payout_error: PayoutError | None = None
    constant_half_mean_squared_error: PayoutError | None = None
    research_only: Literal[True] = True
    trading_enabled: Literal[False] = False
    warnings: tuple[str, ...] = (
        "Research payout scoring only; no financial settlement, trades, or profitability claim.",
        "Each model/seed counts at most one canonical pregame snapshot per event.",
        "Model/seed groups are not pooled; empty or multiple-group headline metrics are null.",
    )
