from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

NFL_BASELINE_VERSION = "nfl-research-elo-payout-v1"
ResearchSplit = Literal["development", "validation", "test"]
_SPLITS: tuple[ResearchSplit, ...] = ("development", "validation", "test")


class NflResearchGame(BaseModel):
    """Historical final-score input; not evidence available prospectively."""

    model_config = ConfigDict(frozen=True)

    event_id: UUID
    provider_event_id: str = Field(min_length=1, max_length=100)
    season: int = Field(ge=2018, le=2025, strict=True)
    week: int = Field(ge=1, le=18, strict=True)
    scheduled_start: AwareDatetime
    home_team_id: UUID
    away_team_id: UUID
    home_score: int = Field(ge=0, strict=True)
    away_score: int = Field(ge=0, strict=True)
    source_last_seen: AwareDatetime

    @field_validator("scheduled_start", "source_last_seen")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_game(self) -> Self:
        if self.home_team_id == self.away_team_id:
            raise ValueError("NFL research games require distinct teams")
        year, month = self.scheduled_start.year, self.scheduled_start.month
        if not ((year == self.season and month >= 8) or (year == self.season + 1 and month <= 2)):
            raise ValueError("NFL game kickoff conflicts with its season")
        if self.source_last_seen < self.scheduled_start:
            raise ValueError("final score source cannot precede kickoff")
        return self


class NflBaselineConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    initial_rating: float = 1500.0
    k_factor: float = 20.0
    rating_scale: float = 400.0
    home_advantage: float = 0.0
    offseason_regression_fraction: float = 1.0 / 3.0
    calibration_bin_count: int = 10
    development_seasons: tuple[int, ...] = (2018, 2019, 2020, 2021, 2022)
    validation_seasons: tuple[int, ...] = (2023, 2024)
    test_seasons: tuple[int, ...] = (2025,)


class NflGamePrediction(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_snapshot: NflResearchGame
    split: ResearchSplit
    home_rating: float
    away_rating: float
    expected_home_payout: float
    actual_home_payout: float
    prior_home_payout: float
    prior_game_count: int


class NflCalibrationBin(BaseModel):
    model_config = ConfigDict(frozen=True)

    lower_bound: float
    upper_bound: float
    count: int
    mean_expected_payout: float | None
    mean_actual_payout: float | None


class NflSplitMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    split: ResearchSplit
    count: int
    mean_squared_payout_error: float | None
    constant_half_mean_squared_payout_error: float | None
    prior_home_mean_squared_payout_error: float | None
    calibration_bins: tuple[NflCalibrationBin, ...]


class NflSeasonCoverage(BaseModel):
    model_config = ConfigDict(frozen=True)

    season: int
    game_count: int
    weeks_observed: tuple[int, ...]
    team_count: int
    first_kickoff: datetime | None
    last_kickoff: datetime | None
    completeness: Literal["unverified"] = "unverified"


class NflResearchReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str = NFL_BASELINE_VERSION
    config: NflBaselineConfig
    input_fingerprint: str
    games: tuple[NflGamePrediction, ...]
    split_metrics: tuple[NflSplitMetrics, ...]
    season_coverage: tuple[NflSeasonCoverage, ...]
    research_only: Literal[True] = True
    promotion_ready: Literal[False] = False
    coverage_verified: Literal[False] = False
    warnings: tuple[str, ...] = (
        "Coverage is unverified and may be partial; game counts do not establish completeness.",
        "This is a retrospective expected-payout proxy, not a win probability or trading signal.",
        "Parameters are fixed and unvalidated; no tuning or operational promotion is performed.",
        "Historical corrected final scores are not proof of information available at prediction time.",
    )


def _split(season: int) -> ResearchSplit:
    if season <= 2022:
        return "development"
    return "validation" if season <= 2024 else "test"


def _metrics(split: ResearchSplit, predictions: list[NflGamePrediction]) -> NflSplitMetrics:
    selected = [prediction for prediction in predictions if prediction.split == split]
    count = len(selected)
    bins: list[NflCalibrationBin] = []
    for index in range(10):
        rows = [row for row in selected if min(int(row.expected_home_payout * 10), 9) == index]
        bins.append(
            NflCalibrationBin(
                lower_bound=index / 10,
                upper_bound=(index + 1) / 10,
                count=len(rows),
                mean_expected_payout=(
                    sum(row.expected_home_payout for row in rows) / len(rows) if rows else None
                ),
                mean_actual_payout=(
                    sum(row.actual_home_payout for row in rows) / len(rows) if rows else None
                ),
            )
        )
    return NflSplitMetrics(
        split=split,
        count=count,
        mean_squared_payout_error=(
            sum((row.expected_home_payout - row.actual_home_payout) ** 2 for row in selected)
            / count
            if count
            else None
        ),
        constant_half_mean_squared_payout_error=(
            sum((0.5 - row.actual_home_payout) ** 2 for row in selected) / count if count else None
        ),
        prior_home_mean_squared_payout_error=(
            sum((row.prior_home_payout - row.actual_home_payout) ** 2 for row in selected) / count
            if count
            else None
        ),
        calibration_bins=tuple(bins),
    )


def evaluate_games(games: list[NflResearchGame]) -> NflResearchReport:
    """Replay fixed Elo updates only after each complete supplied season/week batch.

    Missing weeks are not synthesized. All predictions within a week share only
    earlier-week evidence, including the expanding home-score benchmark.
    """
    if not games:
        raise ValueError("NFL research evaluation blocked: no historical games")
    if len({game.event_id for game in games}) != len(games) or len(
        {game.provider_event_id for game in games}
    ) != len(games):
        raise ValueError("duplicate NFL event or provider identity")
    ordered = sorted(
        games, key=lambda game: (game.season, game.week, game.scheduled_start, str(game.event_id))
    )
    grouped: dict[tuple[int, int], list[NflResearchGame]] = defaultdict(list)
    for game in ordered:
        grouped[(game.season, game.week)].append(game)
    latest_prior_kickoff: datetime | None = None
    for week_games in grouped.values():
        teams = [team for game in week_games for team in (game.home_team_id, game.away_team_id)]
        if len(set(teams)) != len(teams):
            raise ValueError("team appears twice in an NFL season/week")
        first_kickoff = min(game.scheduled_start for game in week_games)
        if latest_prior_kickoff is not None and first_kickoff <= latest_prior_kickoff:
            raise ValueError("NFL week order conflicts with kickoff chronology")
        latest_prior_kickoff = max(game.scheduled_start for game in week_games)

    config = NflBaselineConfig()
    canonical = {
        "version": NFL_BASELINE_VERSION,
        "config": config.model_dump(mode="json"),
        "games": [game.model_dump(mode="json") for game in ordered],
    }
    fingerprint = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    ratings: dict[UUID, float] = {}
    previous_season: int | None = None
    prior_count = 0
    prior_home_sum = 0.0
    predictions: list[NflGamePrediction] = []
    for (season, _), week_games in grouped.items():
        if previous_season is not None and season != previous_season:
            retention = (1 - config.offseason_regression_fraction) ** (season - previous_season)
            ratings = {
                team: config.initial_rating + (rating - config.initial_rating) * retention
                for team, rating in ratings.items()
            }
        previous_season = season
        updates: list[tuple[UUID, UUID, float, float, float]] = []
        week_home_sum = 0.0
        for game in week_games:
            home = ratings.get(game.home_team_id, config.initial_rating)
            away = ratings.get(game.away_team_id, config.initial_rating)
            expected = 1 / (1 + 10 ** ((away - home - config.home_advantage) / config.rating_scale))
            actual = (
                1.0
                if game.home_score > game.away_score
                else 0.0
                if game.home_score < game.away_score
                else 0.5
            )
            predictions.append(
                NflGamePrediction(
                    input_snapshot=game,
                    split=_split(season),
                    home_rating=home,
                    away_rating=away,
                    expected_home_payout=expected,
                    actual_home_payout=actual,
                    prior_home_payout=prior_home_sum / prior_count if prior_count else 0.5,
                    prior_game_count=prior_count,
                )
            )
            updates.append(
                (
                    game.home_team_id,
                    game.away_team_id,
                    home,
                    away,
                    config.k_factor * (actual - expected),
                )
            )
            week_home_sum += actual
        for home_id, away_id, home, away, delta in updates:
            ratings[home_id] = home + delta
            ratings[away_id] = away - delta
        prior_count += len(week_games)
        prior_home_sum += week_home_sum

    coverage: list[NflSeasonCoverage] = []
    for season in range(2018, 2026):
        rows = [game for game in ordered if game.season == season]
        coverage.append(
            NflSeasonCoverage(
                season=season,
                game_count=len(rows),
                weeks_observed=tuple(sorted({game.week for game in rows})),
                team_count=len(
                    {team for game in rows for team in (game.home_team_id, game.away_team_id)}
                ),
                first_kickoff=min((game.scheduled_start for game in rows), default=None),
                last_kickoff=max((game.scheduled_start for game in rows), default=None),
            )
        )
    return NflResearchReport(
        config=config,
        input_fingerprint=fingerprint,
        games=tuple(predictions),
        split_metrics=tuple(_metrics(split, predictions) for split in _SPLITS),
        season_coverage=tuple(coverage),
    )
