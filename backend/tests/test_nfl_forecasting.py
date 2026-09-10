from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.domain.nfl_forecasting import NflPayoutForecastCandidate
from app.domain.nfl_shadow import NflShadowPrediction, NflShadowTarget
from app.services.nfl_forecasting.engine import build_nfl_payout_forecast_candidate
from app.services.nfl_research.baseline import NflResearchGame
from app.services.nfl_research.shadow import build_shadow_prediction

_NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)


@pytest.fixture(scope="module")
def prediction() -> NflShadowPrediction:
    archive = Path(__file__).resolve().parents[2] / "docs/research/nfl-baseline-2026-09-10"
    history = [
        NflResearchGame.model_validate(row)
        for season in range(2018, 2026)
        for row in json.loads((archive / f"inputs-{season}.json").read_text(encoding="utf-8"))
    ]
    target = NflShadowTarget(
        event_id=UUID(int=2026),
        provider_event_id="fixture-nfl",
        season=2026,
        week=1,
        scheduled_start=_NOW + timedelta(hours=1),
        home_team_id=history[-1].home_team_id,
        away_team_id=history[-1].away_team_id,
        source_last_seen=_NOW,
    )
    return build_shadow_prediction(history, target, _NOW)


def candidate(
    prediction: NflShadowPrediction,
    *,
    away_yes: bool = False,
    close: datetime = _NOW + timedelta(hours=2),
    market_seen: datetime = _NOW,
) -> NflPayoutForecastCandidate:
    return build_nfl_payout_forecast_candidate(
        prediction=prediction,
        match_id=UUID(int=1),
        market_id=UUID(int=2),
        source_shadow_snapshot_id=UUID(int=3),
        yes_team_id=prediction.target_snapshot.away_team_id
        if away_yes
        else prediction.target_snapshot.home_team_id,
        market_close_time=close,
        market_last_seen_at=market_seen,
    )


def test_paper_candidate_preserves_math_and_cannot_trade(prediction: NflShadowPrediction) -> None:
    result = candidate(prediction)
    assert result.expected_home_payout == prediction.expected_home_payout
    assert result.expected_yes_payout == result.expected_home_payout
    assert result.expected_no_payout == result.expected_away_payout
    assert result.generated_at == prediction.as_of
    assert result.valid_until == _NOW + timedelta(minutes=15)
    assert result.purpose == "paper_candidate"
    assert result.metric_kind == "expected_payout"
    assert result.execution_mode == "paper"
    assert not result.operational_eligible and not result.trading_enabled
    assert result.promotion_state == "blocked"
    assert result.block_reasons == ("promotion_review_required",)
    assert candidate(prediction) == result


def test_away_yes_inverts_payouts_and_fingerprint(prediction: NflShadowPrediction) -> None:
    home = candidate(prediction)
    away = candidate(prediction, away_yes=True)
    assert away.expected_yes_payout == home.expected_no_payout
    assert away.expected_no_payout == home.expected_yes_payout
    assert away.input_fingerprint != home.input_fingerprint


def test_expiry_is_capped_by_market_close(prediction: NflShadowPrediction) -> None:
    close = _NOW + timedelta(minutes=2)
    assert candidate(prediction, close=close).valid_until == close


@pytest.mark.parametrize("minutes", [1, 7])
def test_expiry_is_capped_by_source_freshness(
    prediction: NflShadowPrediction, minutes: int
) -> None:
    observed = _NOW - timedelta(hours=24) + timedelta(minutes=minutes)
    assert candidate(prediction, market_seen=observed).valid_until == _NOW + timedelta(
        minutes=minutes
    )
    changed = prediction.model_copy(
        update={
            "target_snapshot": prediction.target_snapshot.model_copy(
                update={"source_last_seen": observed}
            )
        }
    )
    assert candidate(changed).valid_until == _NOW + timedelta(minutes=minutes)


def test_expiry_is_capped_by_kickoff(prediction: NflShadowPrediction) -> None:
    # Freshly generated later against the same observed, still-fresh target.
    later = prediction.model_copy(
        update={"as_of": prediction.target_snapshot.scheduled_start - timedelta(minutes=5)}
    )
    assert candidate(later).valid_until == prediction.target_snapshot.scheduled_start


@pytest.mark.parametrize(
    "changes",
    [
        {"seed_fingerprint": "a" * 64},
        {"config_version": "unreviewed-model"},
        {"baseline_version": "different-baseline"},
        {"target_fingerprint": "b" * 64},
        {"as_of": _NOW.replace(tzinfo=None)},
        {"expected_away_payout": Decimal("0")},
    ],
)
def test_wrong_or_malformed_prediction_rejected(
    prediction: NflShadowPrediction, changes: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        candidate(prediction.model_copy(update=changes))


def test_config_tampering_rejected_despite_same_version(prediction: NflShadowPrediction) -> None:
    altered = prediction.model_copy(
        update={"configuration": prediction.configuration.model_copy(update={"k_factor": 50})}
    )
    with pytest.raises(ValueError, match="configuration"):
        candidate(altered)


@pytest.mark.parametrize(
    "observed",
    [_NOW + timedelta(seconds=1), _NOW - timedelta(hours=24), _NOW - timedelta(hours=25)],
)
def test_future_or_expired_source_rejected(
    prediction: NflShadowPrediction, observed: datetime
) -> None:
    with pytest.raises(ValueError):
        candidate(prediction, market_seen=observed)


@pytest.mark.parametrize("close", [_NOW, _NOW - timedelta(seconds=1), _NOW.replace(tzinfo=None)])
def test_expired_or_ambiguous_market_close_rejected(
    prediction: NflShadowPrediction, close: datetime
) -> None:
    with pytest.raises(ValueError):
        candidate(prediction, close=close)


def test_market_close_is_required_and_never_inferred(prediction: NflShadowPrediction) -> None:
    with pytest.raises(ValueError, match="market close"):
        candidate(prediction, close=None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    [
        {"operational_eligible": True},
        {"trading_enabled": True},
        {"execution_mode": "live"},
        {"promotion_state": "approved"},
        {"block_reasons": ()},
        {"metric_kind": "win_probability"},
    ],
)
def test_candidate_contract_rejects_authority_escalation(
    prediction: NflShadowPrediction, changes: dict[str, object]
) -> None:
    payload = candidate(prediction).model_dump()
    payload.update(changes)
    with pytest.raises(ValidationError):
        NflPayoutForecastCandidate.model_validate(payload)


def test_foreign_yes_team_rejected(prediction: NflShadowPrediction) -> None:
    with pytest.raises(ValueError, match="YES team"):
        build_nfl_payout_forecast_candidate(
            prediction=prediction,
            match_id=UUID(int=1),
            market_id=UUID(int=2),
            source_shadow_snapshot_id=UUID(int=3),
            yes_team_id=UUID(int=999),
            market_close_time=_NOW + timedelta(hours=2),
            market_last_seen_at=_NOW,
        )
