from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal

from app.domain.nfl_shadow_evaluation import (
    NflShadowCalibrationBin,
    NflShadowFinalResult,
    NflShadowLabel,
    NflShadowModelPerformance,
    NflShadowPerformanceSummary,
    NflShadowScoringInput,
)

NFL_SHADOW_EVALUATION_VERSION = "nfl-shadow-payout-scoring-v1"
_ERROR_QUANTUM = Decimal("0.000000000001")


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _rounded(value: Decimal) -> Decimal:
    return value.quantize(_ERROR_QUANTUM, rounding=ROUND_HALF_EVEN)


def build_shadow_label(
    snapshot: NflShadowScoringInput, result: NflShadowFinalResult, evaluated_at: datetime
) -> NflShadowLabel:
    """Score an ordinary final NFL outcome against a preserved pregame snapshot."""
    snapshot = NflShadowScoringInput.model_validate(snapshot.model_dump())
    result = NflShadowFinalResult.model_validate(result.model_dump())
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("shadow label evaluation time must be timezone-aware")
    evaluated_at = evaluated_at.astimezone(UTC)
    if (
        snapshot.event_id != result.event_id
        or snapshot.provider_event_id != result.provider_event_id
        or snapshot.kickoff != result.scheduled_start
        or snapshot.home_team_id != result.home_team_id
        or snapshot.away_team_id != result.away_team_id
    ):
        raise ValueError("final result does not match exact shadow event, teams, and kickoff")
    if not snapshot.generated_at <= result.source_last_seen <= evaluated_at:
        raise ValueError("final result observation conflicts with snapshot/evaluation chronology")
    home_payout = (
        Decimal("1.000000")
        if result.home_score > result.away_score
        else Decimal("0.000000")
        if result.home_score < result.away_score
        else Decimal("0.500000")
    )
    yes_payout = (
        home_payout
        if snapshot.yes_team_id == snapshot.home_team_id
        else Decimal("1.000000") - home_payout
    )
    snapshot_fingerprint = _fingerprint(snapshot.model_dump(mode="json"))
    result_fingerprint = _fingerprint(result.model_dump(mode="json", exclude={"source_last_seen"}))
    label_fingerprint = _fingerprint(
        {
            "evaluation_version": NFL_SHADOW_EVALUATION_VERSION,
            "snapshot_fingerprint": snapshot_fingerprint,
            "result_fingerprint": result_fingerprint,
        }
    )
    return NflShadowLabel(
        snapshot=snapshot,
        result=result,
        evaluated_at=evaluated_at,
        actual_home_payout=home_payout,
        actual_yes_payout=yes_payout,
        squared_home_payout_error=_rounded((snapshot.expected_home_payout - home_payout) ** 2),
        constant_half_squared_error=_rounded((Decimal("0.5") - home_payout) ** 2),
        snapshot_fingerprint=snapshot_fingerprint,
        result_fingerprint=result_fingerprint,
        label_fingerprint=label_fingerprint,
        evaluation_version=NFL_SHADOW_EVALUATION_VERSION,
    )


def aggregate_shadow_labels(labels: list[NflShadowLabel]) -> NflShadowPerformanceSummary:
    """Score repository-canonical labels once per event in each separate model/seed."""
    groups: dict[tuple[str, str], list[NflShadowLabel]] = defaultdict(list)
    seen: set[tuple[str, str, str]] = set()
    for label in labels:
        verified = build_shadow_label(label.snapshot, label.result, label.evaluated_at)
        if verified != label:
            raise ValueError("shadow label integrity mismatch")
        key = (label.snapshot.model_version, label.snapshot.seed_fingerprint)
        local_key = (*key, f"local:{label.snapshot.event_id}")
        provider_key = (*key, f"provider:{label.snapshot.provider_event_id}")
        if local_key in seen or provider_key in seen:
            raise ValueError("duplicate shadow event in model/seed; canonicalize labels first")
        seen.update((local_key, provider_key))
        groups[key].append(label)
    reports: list[NflShadowModelPerformance] = []
    for (model_version, seed), rows in sorted(groups.items()):
        rows.sort(key=lambda row: (str(row.snapshot.event_id), str(row.snapshot.snapshot_id)))
        count = len(rows)
        bins: list[NflShadowCalibrationBin] = []
        for index in range(10):
            selected = [
                row for row in rows if min(int(row.snapshot.expected_home_payout * 10), 9) == index
            ]
            bins.append(
                NflShadowCalibrationBin(
                    lower_bound=Decimal(index) / 10,
                    upper_bound=Decimal(index + 1) / 10,
                    count=len(selected),
                    mean_expected_payout=_rounded(
                        sum((row.snapshot.expected_home_payout for row in selected), Decimal(0))
                        / len(selected)
                    )
                    if selected
                    else None,
                    mean_actual_payout=_rounded(
                        sum((row.actual_home_payout for row in selected), Decimal(0))
                        / len(selected)
                    )
                    if selected
                    else None,
                )
            )
        reports.append(
            NflShadowModelPerformance(
                model_version=model_version,
                seed_fingerprint=seed,
                count=count,
                tie_count=sum(row.actual_home_payout == Decimal("0.5") for row in rows),
                mean_squared_home_payout_error=_rounded(
                    sum((row.squared_home_payout_error for row in rows), Decimal(0)) / count
                ),
                constant_half_mean_squared_error=_rounded(
                    sum((row.constant_half_squared_error for row in rows), Decimal(0)) / count
                ),
                calibration_bins=tuple(bins),
            )
        )
    return NflShadowPerformanceSummary(
        count=len(labels),
        model_groups=tuple(reports),
        mean_squared_home_payout_error=reports[0].mean_squared_home_payout_error
        if len(reports) == 1
        else None,
        constant_half_mean_squared_error=reports[0].constant_half_mean_squared_error
        if len(reports) == 1
        else None,
    )
