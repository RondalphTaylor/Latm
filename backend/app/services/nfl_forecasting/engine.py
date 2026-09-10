from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.domain.nfl_forecasting import NflPayoutForecastCandidate
from app.domain.nfl_shadow import NflShadowConfiguration, NflShadowPrediction
from app.services.nfl_research.baseline import NFL_BASELINE_VERSION, NflBaselineConfig
from app.services.nfl_research.shadow import NFL_SHADOW_SEED_FINGERPRINT, NFL_SHADOW_VERSION

NFL_PAYOUT_CANDIDATE_VERSION = "nfl-paper-payout-candidate-v1"


def _aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def build_nfl_payout_forecast_candidate(
    *,
    prediction: NflShadowPrediction,
    match_id: UUID,
    market_id: UUID,
    yes_team_id: UUID,
    source_shadow_snapshot_id: UUID,
    market_close_time: datetime,
    market_last_seen_at: datetime,
) -> NflPayoutForecastCandidate:
    """Wrap a freshly computed pinned payout proxy without granting trading authority.

    The repository must obtain current, locked source identities and build the
    shadow prediction anew. This pure wrapper never fits or changes that model.
    """
    prediction = NflShadowPrediction.model_validate(prediction.model_dump())
    if (
        prediction.seed_fingerprint != NFL_SHADOW_SEED_FINGERPRINT
        or prediction.config_version != NFL_SHADOW_VERSION
        or prediction.baseline_version != NFL_BASELINE_VERSION
    ):
        raise ValueError("candidate model version or seed is not the pinned release")
    baseline = NflBaselineConfig()
    expected_config = NflShadowConfiguration(
        initial_rating=baseline.initial_rating,
        k_factor=baseline.k_factor,
        rating_scale=baseline.rating_scale,
        home_advantage=baseline.home_advantage,
        offseason_regression_fraction=baseline.offseason_regression_fraction,
    )
    if prediction.configuration != expected_config:
        raise ValueError("candidate model configuration differs from the pinned release")
    target = prediction.target_snapshot
    if prediction.target_fingerprint != _fingerprint(
        target.model_dump(mode="json", exclude={"source_last_seen"})
    ):
        raise ValueError("candidate source target fingerprint mismatch")
    generated = _aware(prediction.as_of, "prediction as_of")
    close = _aware(market_close_time, "market close time")
    market_seen = _aware(market_last_seen_at, "market observation")
    event_seen = _aware(target.source_last_seen, "event observation")
    if market_seen > generated or event_seen > generated:
        raise ValueError("candidate source observation cannot postdate generation")
    valid_until = min(
        generated + timedelta(minutes=15),
        target.scheduled_start,
        close,
        event_seen + timedelta(hours=24),
        market_seen + timedelta(hours=24),
    )
    yes_payout = (
        prediction.expected_home_payout
        if yes_team_id == target.home_team_id
        else prediction.expected_away_payout
    )
    no_payout = (
        prediction.expected_away_payout
        if yes_team_id == target.home_team_id
        else prediction.expected_home_payout
    )
    candidate = NflPayoutForecastCandidate(
        match_id=match_id,
        market_id=market_id,
        event_id=target.event_id,
        home_team_id=target.home_team_id,
        away_team_id=target.away_team_id,
        yes_team_id=yes_team_id,
        model_version=prediction.config_version,
        seed_fingerprint=prediction.seed_fingerprint,
        source_shadow_snapshot_id=source_shadow_snapshot_id,
        generated_at=generated,
        valid_until=valid_until,
        expected_home_payout=prediction.expected_home_payout,
        expected_away_payout=prediction.expected_away_payout,
        expected_yes_payout=yes_payout,
        expected_no_payout=no_payout,
        input_fingerprint="0" * 64,
    )
    fingerprint = _fingerprint(
        {
            "candidate_version": NFL_PAYOUT_CANDIDATE_VERSION,
            "candidate": candidate.model_dump(mode="json", exclude={"input_fingerprint"}),
            "prediction": prediction.model_dump(mode="json"),
            "market_close_time": close.isoformat(),
            "market_last_seen_at": market_seen.isoformat(),
        }
    )
    return candidate.model_copy(update={"input_fingerprint": fingerprint})
