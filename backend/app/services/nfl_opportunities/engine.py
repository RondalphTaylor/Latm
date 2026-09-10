from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from pydantic import ValidationError

from app.domain.markets import MarketPrice
from app.domain.nfl_forecasting import NflPayoutForecastCandidate
from app.domain.nfl_opportunities import (
    ComparisonStatus,
    NflPaperOpportunityComparison,
    NflPaperOpportunityPolicy,
)
from app.services.nfl_research.shadow import NFL_SHADOW_SEED_FINGERPRINT, NFL_SHADOW_VERSION

NFL_PAPER_OPPORTUNITY_VERSION = "nfl-paper-direct-ask-v1"


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def build_nfl_paper_opportunity_comparison(
    *,
    forecast: NflPayoutForecastCandidate,
    forecast_id: UUID,
    latest_market_price_id: UUID | None,
    market_price: MarketPrice | None,
    evaluated_at: datetime,
    policy: NflPaperOpportunityPolicy | None = None,
) -> NflPaperOpportunityComparison:
    forecast = NflPayoutForecastCandidate.model_validate(forecast.model_dump())
    if (
        forecast.model_version != NFL_SHADOW_VERSION
        or forecast.seed_fingerprint != NFL_SHADOW_SEED_FINGERPRINT
    ):
        raise ValueError("opportunity forecast model/seed is not pinned")
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("opportunity evaluation time must be timezone-aware")
    now = evaluated_at.astimezone(UTC)
    if not forecast.generated_at <= now < forecast.valid_until:
        raise ValueError("opportunity forecast is future-dated or expired")
    policy = NflPaperOpportunityPolicy.model_validate(
        (policy or NflPaperOpportunityPolicy()).model_dump()
    )
    raw_price = market_price.model_dump(mode="json") if market_price is not None else None
    reason: str | None = None
    price_time: datetime | None = None
    price_expiry: datetime | None = None
    if market_price is None or latest_market_price_id is None:
        reason = "missing_quote"
    else:
        try:
            market_price = MarketPrice.model_validate(market_price.model_dump())
        except ValidationError:
            reason = "invalid_book"
        if reason is None:
            observed = market_price.retrieved_at
            if observed.tzinfo is None or observed.utcoffset() is None:
                reason = "invalid_quote_time"
            else:
                price_time = observed.astimezone(UTC)
                price_expiry = price_time + timedelta(seconds=policy.max_price_age_seconds)
                if price_time > now:
                    reason = "future_quote"
                elif now >= price_expiry:
                    reason = "stale_quote"
            if reason is None and (
                (
                    market_price.yes_bid is not None
                    and market_price.yes_ask is not None
                    and market_price.yes_bid > market_price.yes_ask
                )
                or (
                    market_price.no_bid is not None
                    and market_price.no_ask is not None
                    and market_price.no_bid > market_price.no_ask
                )
                or (
                    market_price.yes_bid is not None
                    and market_price.no_bid is not None
                    and market_price.yes_bid + market_price.no_bid > 1
                )
                or (
                    market_price.yes_ask is not None
                    and market_price.no_ask is not None
                    and market_price.yes_ask + market_price.no_ask < 1
                )
            ):
                reason = "crossed_book"

    def compare(
        expected: Decimal, ask: Decimal | None
    ) -> tuple[Decimal | None, ComparisonStatus, str]:
        if reason is not None:
            return None, "ineligible", reason
        if ask is None:
            return None, "ineligible", "missing_side_ask"
        if not Decimal(0) < ask < Decimal(1):
            return None, "ineligible", "invalid_side_ask"
        edge = (expected - ask).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        if edge < policy.watch_threshold:
            return edge, "ignore", "below_watch_threshold"
        if edge < policy.candidate_threshold:
            return edge, "watch", "watch_threshold_met"
        return edge, "paper_candidate", "candidate_threshold_met"

    yes_ask = (
        market_price.yes_ask if market_price is not None and reason != "invalid_book" else None
    )
    no_ask = market_price.no_ask if market_price is not None and reason != "invalid_book" else None
    yes_edge, yes_status, yes_reason = compare(forecast.expected_yes_payout, yes_ask)
    no_edge, no_status, no_reason = compare(forecast.expected_no_payout, no_ask)
    comparable = yes_status != "ineligible" or no_status != "ineligible"
    policy_hash = _hash(
        {
            "version": NFL_PAPER_OPPORTUNITY_VERSION,
            "policy": policy.model_dump(mode="json"),
            "formula": "expected_payout-direct_same_side_ask",
            "rounding": "half_up_6dp",
        }
    )
    fingerprint = _hash(
        {
            "forecast": forecast.model_dump(mode="json"),
            "forecast_id": str(forecast_id),
            "price_id": str(latest_market_price_id) if latest_market_price_id else None,
            "price": raw_price,
            "policy_fingerprint": policy_hash,
            "evaluated_at": now.isoformat(),
        }
    )
    return NflPaperOpportunityComparison(
        forecast_id=forecast_id,
        market_id=forecast.market_id,
        match_id=forecast.match_id,
        event_id=forecast.event_id,
        price_id=latest_market_price_id,
        price_retrieved_at=price_time,
        evaluated_at=now,
        valid_until=min(forecast.valid_until, price_expiry)
        if comparable and price_expiry
        else None,
        yes_expected_payout=forecast.expected_yes_payout,
        no_expected_payout=forecast.expected_no_payout,
        yes_direct_ask=yes_ask,
        no_direct_ask=no_ask,
        yes_raw_edge=yes_edge,
        no_raw_edge=no_edge,
        yes_status=yes_status,
        no_status=no_status,
        yes_reason=yes_reason,
        no_reason=no_reason,
        policy_version=NFL_PAPER_OPPORTUNITY_VERSION,
        policy_fingerprint=policy_hash,
        input_fingerprint=fingerprint,
    )
