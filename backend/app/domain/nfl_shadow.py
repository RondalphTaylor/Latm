from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class NflShadowTarget(BaseModel):
    """Source-observed upcoming game; contains no outcome or 2026 score inputs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: UUID
    provider_event_id: str = Field(min_length=1, max_length=100)
    season: Literal[2026]
    week: int = Field(ge=1, le=18, strict=True)
    scheduled_start: AwareDatetime
    home_team_id: UUID
    away_team_id: UUID
    source_last_seen: AwareDatetime

    @field_validator("scheduled_start", "source_last_seen")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        if self.home_team_id == self.away_team_id:
            raise ValueError("NFL shadow target requires distinct teams")
        if not (
            (self.scheduled_start.year == 2026 and self.scheduled_start.month >= 9)
            or (self.scheduled_start.year == 2027 and self.scheduled_start.month == 1)
        ):
            raise ValueError("target kickoff does not belong to the 2026 regular season")
        return self


class NflShadowConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    initial_rating: float
    k_factor: float
    rating_scale: float
    home_advantage: float
    offseason_regression_fraction: float
    target_season: Literal[2026] = 2026
    rating_policy: Literal["frozen_preseason2026"] = "frozen_preseason2026"
    target_freshness_seconds: Literal[86400] = 86400
    payout_decimal_places: Literal[6] = 6


class NflShadowPrediction(BaseModel):
    """Unpromoted payout proxy, deliberately outside operational forecasts."""

    model_config = ConfigDict(frozen=True)

    target_snapshot: NflShadowTarget
    as_of: AwareDatetime
    expected_home_payout: Decimal = Field(ge=0, le=1, decimal_places=6)
    expected_away_payout: Decimal = Field(ge=0, le=1, decimal_places=6)
    home_rating: float = Field(allow_inf_nan=False)
    away_rating: float = Field(allow_inf_nan=False)
    seed_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_version: str
    config_version: str
    configuration: NflShadowConfiguration
    target_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    research_only: Literal[True] = True
    trading_enabled: Literal[False] = False
    warnings: tuple[str, ...] = (
        "Unpromoted research shadow expected-payout proxy; not a win probability or trade signal.",
        "Frozen preseason2026 ratings never incorporate 2026 results and become stale during the season.",
        "Archived seed observations and model configuration are pinned; changes require a new release.",
    )

    @model_validator(mode="after")
    def validate_complement(self) -> Self:
        if self.expected_home_payout + self.expected_away_payout != Decimal("1"):
            raise ValueError("shadow home and away expected payouts must sum to one")
        return self
