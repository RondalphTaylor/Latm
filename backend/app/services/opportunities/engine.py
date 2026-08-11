from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal

from app.domain.opportunities import (
    OpportunityDecision,
    OpportunityEvaluationInput,
    OpportunityPolicy,
    OpportunityStatus,
)

EDGE_FORMULA = "raw_edge=model_probability-side_ask_probability"
_EDGE_QUANTUM = Decimal("0.000001")


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def policy_fingerprint(policy: OpportunityPolicy) -> str:
    """Hash every parameter and formula that defines opportunity classification."""
    return _canonical_hash(
        {
            "policy": policy.model_dump(mode="json"),
            "formula": EDGE_FORMULA,
            "edge_precision": str(_EDGE_QUANTUM),
            "market_probability_source": "directional_ask",
        }
    )


def effective_strategy_version(policy: OpportunityPolicy) -> str:
    fingerprint = policy_fingerprint(policy)
    return f"{policy.code_version}+cfg.{fingerprint[:12]}"


class RawEdgeOpportunityEngine:
    """Compare independent model probabilities to directional entry asks."""

    def __init__(self, policy: OpportunityPolicy) -> None:
        self.policy = policy
        self.policy_fingerprint = policy_fingerprint(policy)
        self.strategy_version = effective_strategy_version(policy)

    def evaluate(self, source: OpportunityEvaluationInput) -> OpportunityDecision:
        """Return a deterministic research classification for one contract side."""
        raw_edge = (source.model_probability - source.market_probability).quantize(
            _EDGE_QUANTUM,
            rounding=ROUND_HALF_UP,
        )
        if raw_edge < self.policy.watch_min_raw_edge:
            opportunity_status = OpportunityStatus.IGNORE
            reason = "raw edge is below the watch threshold"
        elif raw_edge < self.policy.trade_candidate_min_raw_edge:
            opportunity_status = OpportunityStatus.WATCH
            reason = "raw edge meets the watch threshold"
        else:
            opportunity_status = OpportunityStatus.TRADE_CANDIDATE
            reason = "raw edge meets the trade-candidate research threshold"

        input_fingerprint = _canonical_hash(
            {
                "market_id": str(source.market_id),
                "market_price_id": str(source.market_price_id),
                "market_event_match_id": str(source.market_event_match_id),
                "sports_event_id": str(source.sports_event_id),
                "base_forecast_id": str(source.base_forecast_id),
                "model_version_id": str(source.model_version_id),
                "outcome_team_id": str(source.outcome_team_id),
                "yes_team_id": str(source.yes_team_id),
                "no_team_id": str(source.no_team_id),
                "direction": source.direction.value,
                "price_source": source.price_source.value,
                "mapping_method": source.mapping_method,
                "orientation_fingerprint": source.orientation_fingerprint,
                "match_input_fingerprint": source.match_input_fingerprint,
                "forecast_input_fingerprint": source.forecast_input_fingerprint,
                "market_probability": str(source.market_probability),
                "model_probability": str(source.model_probability),
                "valid_until": source.valid_until.isoformat(),
                "source_snapshot": source.source_snapshot,
                "policy_fingerprint": self.policy_fingerprint,
            }
        )
        return OpportunityDecision(
            market_id=source.market_id,
            market_price_id=source.market_price_id,
            market_event_match_id=source.market_event_match_id,
            sports_event_id=source.sports_event_id,
            base_forecast_id=source.base_forecast_id,
            model_version_id=source.model_version_id,
            outcome_team_id=source.outcome_team_id,
            yes_team_id=source.yes_team_id,
            no_team_id=source.no_team_id,
            direction=source.direction,
            price_source=source.price_source,
            mapping_method=source.mapping_method,
            orientation_fingerprint=source.orientation_fingerprint,
            market_probability=source.market_probability,
            model_probability=source.model_probability,
            raw_edge=raw_edge,
            status=opportunity_status,
            status_reason=reason,
            strategy_name=self.policy.strategy_name,
            strategy_version=self.strategy_version,
            watch_min_raw_edge=self.policy.watch_min_raw_edge,
            trade_candidate_min_raw_edge=self.policy.trade_candidate_min_raw_edge,
            max_market_price_age_seconds=self.policy.max_market_price_age_seconds,
            max_operational_forecast_age_seconds=(self.policy.max_operational_forecast_age_seconds),
            policy_fingerprint=self.policy_fingerprint,
            input_fingerprint=input_fingerprint,
            price_retrieved_at=source.price_retrieved_at,
            forecast_generated_at=source.forecast_generated_at,
            price_age_seconds=int(
                (source.evaluated_at - source.price_retrieved_at).total_seconds()
            ),
            forecast_age_seconds=int(
                (source.evaluated_at - source.forecast_generated_at).total_seconds()
            ),
            valid_until=source.valid_until,
            evaluated_at=source.evaluated_at,
            source_snapshot=source.source_snapshot,
        )
