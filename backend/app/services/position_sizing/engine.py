from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal

from app.domain.portfolio import (
    PositionSizeProposal,
    PositionSizingInput,
    PositionSizingPolicy,
    exposure_fraction,
    floor_money,
)

SIZING_FORMULA = "capital=floor_cents(available_bankroll*edge_band_exposure)"


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def sizing_policy_fingerprint(policy: PositionSizingPolicy) -> str:
    """Hash every effective position-sizing parameter and formula."""
    return _canonical_hash(
        {
            "policy": policy.model_dump(mode="json"),
            "formula": SIZING_FORMULA,
            "money_precision": "0.01",
            "money_rounding": "ROUND_DOWN",
            "exposure_precision": "0.0000000001",
            "confidence_basis": "not_available",
        }
    )


def effective_sizing_strategy_version(policy: PositionSizingPolicy) -> str:
    fingerprint = sizing_policy_fingerprint(policy)
    return f"{policy.code_version}+cfg.{fingerprint[:12]}"


@dataclass(frozen=True)
class PositionSizingEvaluation:
    """One pure sizing result, including conservative non-proposal reasons."""

    proposal: PositionSizeProposal | None
    skip_reason: str | None


class RulesPositionSizer:
    """Apply conservative raw-edge bands to a paper balance snapshot."""

    def __init__(self, policy: PositionSizingPolicy) -> None:
        self.policy = policy
        self.policy_fingerprint = sizing_policy_fingerprint(policy)
        self.strategy_version = effective_sizing_strategy_version(policy)

    def evaluate(self, source: PositionSizingInput) -> PositionSizingEvaluation:
        """Return an advisory proposal or an explicit skip reason."""
        if source.portfolio.mode.value != "paper":
            return PositionSizingEvaluation(None, "portfolio_not_paper")
        if source.opportunity_status != "trade_candidate":
            return PositionSizingEvaluation(None, "not_trade_candidate")
        if source.raw_edge < self.policy.candidate_min_raw_edge:
            return PositionSizingEvaluation(None, "below_sizing_edge_threshold")
        if source.portfolio.available_bankroll <= 0:
            return PositionSizingEvaluation(None, "no_available_bankroll")

        target_exposure, band = self._target_exposure(source.raw_edge)
        proposed_capital = floor_money(source.portfolio.available_bankroll * target_exposure)
        if proposed_capital < Decimal("0.01"):
            return PositionSizingEvaluation(None, "below_minimum_currency_unit")
        actual_exposure = exposure_fraction(
            proposed_capital,
            source.portfolio.available_bankroll,
        )
        input_fingerprint = _canonical_hash(
            {
                "portfolio_id": str(source.portfolio.portfolio_id),
                "portfolio_snapshot_id": str(source.portfolio_snapshot_id),
                "portfolio_snapshot": source.portfolio.model_dump(mode="json"),
                "opportunity_id": str(source.opportunity_id),
                "opportunity_input_fingerprint": source.opportunity_input_fingerprint,
                "reference_price": str(source.reference_price),
                "model_probability": str(source.model_probability),
                "raw_edge": str(source.raw_edge),
                "opportunity_valid_until": source.opportunity_valid_until.isoformat(),
                "target_exposure_fraction": str(target_exposure),
                "proposed_capital": str(proposed_capital),
                "policy_fingerprint": self.policy_fingerprint,
            }
        )
        audit_snapshot = {
            "portfolio_snapshot": source.portfolio.model_dump(mode="json"),
            "opportunity": {
                "id": str(source.opportunity_id),
                "market_id": str(source.market_id),
                "outcome_team_id": str(source.outcome_team_id),
                "direction": source.direction,
                "reference_price": str(source.reference_price),
                "model_probability": str(source.model_probability),
                "raw_edge": str(source.raw_edge),
                "strategy_name": source.opportunity_strategy_name,
                "strategy_version": source.opportunity_strategy_version,
                "input_fingerprint": source.opportunity_input_fingerprint,
                "evaluated_at": source.opportunity_evaluated_at.isoformat(),
                "valid_until": source.opportunity_valid_until.isoformat(),
                "source_snapshot": source.source_snapshot,
            },
            "sizing": {
                "band": band,
                "target_exposure_fraction": str(target_exposure),
                "confidence_basis": "not_available",
                "formula": SIZING_FORMULA,
            },
        }
        return PositionSizingEvaluation(
            PositionSizeProposal(
                portfolio_id=source.portfolio.portfolio_id,
                portfolio_snapshot_id=source.portfolio_snapshot_id,
                opportunity_id=source.opportunity_id,
                market_id=source.market_id,
                outcome_team_id=source.outcome_team_id,
                mode=source.portfolio.mode,
                direction=source.direction,
                reference_price=source.reference_price,
                model_probability=source.model_probability,
                raw_edge=source.raw_edge,
                available_bankroll=source.portfolio.available_bankroll,
                target_exposure_fraction=target_exposure,
                proposed_exposure_fraction=actual_exposure,
                proposed_capital=proposed_capital,
                strategy_name=self.policy.strategy_name,
                strategy_version=self.strategy_version,
                candidate_min_raw_edge=self.policy.candidate_min_raw_edge,
                strong_min_raw_edge=self.policy.strong_min_raw_edge,
                very_strong_min_raw_edge=self.policy.very_strong_min_raw_edge,
                candidate_exposure_fraction=self.policy.candidate_exposure_fraction,
                strong_exposure_fraction=self.policy.strong_exposure_fraction,
                very_strong_exposure_fraction=(self.policy.very_strong_exposure_fraction),
                max_exposure_fraction=self.policy.max_exposure_fraction,
                policy_fingerprint=self.policy_fingerprint,
                input_fingerprint=input_fingerprint,
                opportunity_strategy_name=source.opportunity_strategy_name,
                opportunity_strategy_version=source.opportunity_strategy_version,
                opportunity_input_fingerprint=source.opportunity_input_fingerprint,
                opportunity_evaluated_at=source.opportunity_evaluated_at,
                opportunity_valid_until=source.opportunity_valid_until,
                proposed_at=source.proposed_at,
                reason=f"raw edge qualified for the {band} sizing band",
                audit_snapshot=audit_snapshot,
            ),
            None,
        )

    def _target_exposure(self, raw_edge: Decimal) -> tuple[Decimal, str]:
        if raw_edge >= self.policy.very_strong_min_raw_edge:
            return self.policy.very_strong_exposure_fraction, "very_strong"
        if raw_edge >= self.policy.strong_min_raw_edge:
            return self.policy.strong_exposure_fraction, "strong"
        return self.policy.candidate_exposure_fraction, "candidate"
