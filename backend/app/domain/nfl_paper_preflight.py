from __future__ import annotations

import hashlib
import json
from decimal import ROUND_CEILING, ROUND_DOWN, Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_PRICE_QUANTUM = Decimal("0.000001")
_MONEY_QUANTUM = Decimal("0.01")


def _ceil_price(value: Decimal) -> Decimal:
    return value.quantize(_PRICE_QUANTUM, rounding=ROUND_CEILING)


def _ceil_money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY_QUANTUM, rounding=ROUND_CEILING)


class NflPaperPreflightPolicy(BaseModel):
    """Fixed cost assumptions for a non-authorizing NFL paper preflight."""

    model_config = ConfigDict(frozen=True)

    code_version: str = "nfl-paper-preflight-v1"
    slippage_bps: Decimal = Field(ge=Decimal("0"), le=Decimal("10000"))
    fee_bps: Decimal = Field(ge=Decimal("0"), le=Decimal("10000"))
    minimum_adjusted_edge: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))


def preflight_policy_fingerprint(policy: NflPaperPreflightPolicy) -> str:
    """Fingerprint every cost assumption and the unconditional pilot block."""
    payload = {
        "policy": policy.model_dump(mode="json"),
        "price_rounding": "ROUND_CEILING_0.000001",
        "money_rounding": "ROUND_CEILING_0.01",
        "risk_decision": "reject",
        "execution_enabled": False,
        "reason": "nfl_pilot_not_approved",
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class NflPaperPreflightInput(BaseModel):
    """A direct-ask opportunity and a bounded, non-reserving capital cap."""

    model_config = ConfigDict(frozen=True)

    expected_payout: Decimal = Field(ge=Decimal("0"), le=Decimal("1"))
    direct_ask: Decimal = Field(gt=Decimal("0"), lt=Decimal("1"))
    raw_edge: Decimal = Field(ge=Decimal("-1"), le=Decimal("1"))
    capital_cap: Decimal = Field(gt=Decimal("0"))

    @model_validator(mode="after")
    def validate_raw_edge(self) -> NflPaperPreflightInput:
        if self.raw_edge != (self.expected_payout - self.direct_ask).quantize(_PRICE_QUANTUM):
            raise ValueError("raw_edge must equal expected_payout minus direct_ask")
        return self


class NflPaperPreflightResult(BaseModel):
    """Cost-aware advisory result that cannot authorize an NFL entry."""

    model_config = ConfigDict(frozen=True)

    execution_price: Decimal | None
    quantity: int
    gross_cost: Decimal
    estimated_fee: Decimal
    total_cost: Decimal
    effective_unit_cost: Decimal | None
    adjusted_edge: Decimal | None
    sizing_status: str
    risk_decision: str
    execution_enabled: bool
    reason: str


def evaluate_nfl_paper_preflight(
    source: NflPaperPreflightInput, policy: NflPaperPreflightPolicy
) -> NflPaperPreflightResult:
    """Compute conservative paper costs while retaining the NFL promotion block.

    The result is intentionally not a proposal, risk authorization, trade, or order.
    """
    execution_price = _ceil_price(source.direct_ask + policy.slippage_bps / Decimal("10000"))
    if execution_price >= Decimal("1"):
        return NflPaperPreflightResult(
            execution_price=None,
            quantity=0,
            gross_cost=Decimal("0.00"),
            estimated_fee=Decimal("0.00"),
            total_cost=Decimal("0.00"),
            effective_unit_cost=None,
            adjusted_edge=None,
            sizing_status="ineligible",
            risk_decision="reject",
            execution_enabled=False,
            reason="slippage_adjusted_price_not_buyable",
        )

    def total_cost(quantity: int) -> tuple[Decimal, Decimal, Decimal]:
        gross = _ceil_money(execution_price * quantity)
        fee = (
            _ceil_money(gross * policy.fee_bps / Decimal("10000"))
            if policy.fee_bps
            else Decimal("0.00")
        )
        return gross, fee, gross + fee

    quantity = int((source.capital_cap / execution_price).to_integral_value(rounding=ROUND_DOWN))
    while quantity > 0 and total_cost(quantity)[2] > source.capital_cap:
        quantity -= 1
    if quantity == 0:
        return NflPaperPreflightResult(
            execution_price=execution_price,
            quantity=0,
            gross_cost=Decimal("0.00"),
            estimated_fee=Decimal("0.00"),
            total_cost=Decimal("0.00"),
            effective_unit_cost=None,
            adjusted_edge=None,
            sizing_status="ineligible",
            risk_decision="reject",
            execution_enabled=False,
            reason="capital_cap_cannot_buy_one_contract",
        )
    gross_cost, estimated_fee, all_in_cost = total_cost(quantity)
    effective_unit_cost = _ceil_price(all_in_cost / quantity)
    adjusted_edge = (source.expected_payout - effective_unit_cost).quantize(_PRICE_QUANTUM)
    status = (
        "cost_qualified" if adjusted_edge >= policy.minimum_adjusted_edge else "cost_disqualified"
    )
    return NflPaperPreflightResult(
        execution_price=execution_price,
        quantity=quantity,
        gross_cost=gross_cost,
        estimated_fee=estimated_fee,
        total_cost=all_in_cost,
        effective_unit_cost=effective_unit_cost,
        adjusted_edge=adjusted_edge,
        sizing_status=status,
        risk_decision="reject",
        execution_enabled=False,
        reason="nfl_pilot_not_approved",
    )
