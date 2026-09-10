from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from uuid import UUID

from app.domain.nfl_shadow import NflShadowConfiguration, NflShadowPrediction, NflShadowTarget
from app.services.nfl_research.baseline import NflResearchGame, evaluate_games

NFL_SHADOW_SEED_FINGERPRINT = "9c70fcc1ee9089a3851794764e915eeca2fa3b1c7cfb533a0ba76a0cab320b0b"
NFL_SHADOW_VERSION = "nfl-shadow-frozen-preseason2026-v1"


def build_shadow_prediction(
    history: list[NflResearchGame], target: NflShadowTarget, as_of: datetime
) -> NflShadowPrediction:
    """Derive one pregame payout proxy from the immutable historical seed only."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("shadow as_of must be timezone-aware")
    as_of = as_of.astimezone(UTC)
    # Revalidate even callers using model_copy/model_construct; reject score fields.
    target = NflShadowTarget.model_validate(target.model_dump())
    if as_of >= target.scheduled_start:
        raise ValueError("shadow prediction requires as_of strictly before kickoff")
    if target.source_last_seen > as_of:
        raise ValueError("target source observation is in the future")
    if as_of - target.source_last_seen > timedelta(hours=24):
        raise ValueError("target source observation is stale")
    if any(game.source_last_seen > as_of for game in history):
        raise ValueError("seed source observation is in the future")
    report = evaluate_games(history)
    if report.input_fingerprint != NFL_SHADOW_SEED_FINGERPRINT:
        raise ValueError("shadow seed fingerprint mismatch; a new model release is required")

    config = report.config
    final_ratings: dict[UUID, float] = {}
    for row in report.games:
        if row.input_snapshot.season != 2025:
            continue
        delta = config.k_factor * (row.actual_home_payout - row.expected_home_payout)
        final_ratings[row.input_snapshot.home_team_id] = row.home_rating + delta
        final_ratings[row.input_snapshot.away_team_id] = row.away_rating - delta
    if target.home_team_id not in final_ratings or target.away_team_id not in final_ratings:
        raise ValueError("target teams lack pinned 2025 ratings; cold starts are blocked")
    retention = 1 - config.offseason_regression_fraction
    home_rating = (
        config.initial_rating
        + (final_ratings[target.home_team_id] - config.initial_rating) * retention
    )
    away_rating = (
        config.initial_rating
        + (final_ratings[target.away_team_id] - config.initial_rating) * retention
    )
    expected = 1 / (
        1 + 10 ** ((away_rating - home_rating - config.home_advantage) / config.rating_scale)
    )
    home_payout = Decimal(str(expected)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN)
    semantic_target = target.model_dump(mode="json", exclude={"source_last_seen"})
    target_fingerprint = hashlib.sha256(
        json.dumps(semantic_target, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return NflShadowPrediction(
        target_snapshot=target,
        as_of=as_of,
        expected_home_payout=home_payout,
        expected_away_payout=Decimal("1.000000") - home_payout,
        home_rating=home_rating,
        away_rating=away_rating,
        seed_fingerprint=report.input_fingerprint,
        baseline_version=report.version,
        config_version=NFL_SHADOW_VERSION,
        configuration=NflShadowConfiguration(
            initial_rating=config.initial_rating,
            k_factor=config.k_factor,
            rating_scale=config.rating_scale,
            home_advantage=config.home_advantage,
            offseason_regression_fraction=config.offseason_regression_fraction,
        ),
        target_fingerprint=target_fingerprint,
    )
