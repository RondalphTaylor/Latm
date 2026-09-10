from decimal import Decimal

import pytest

from app.domain.nfl_paper_preflight import (
    NflPaperPreflightInput,
    NflPaperPreflightPolicy,
    evaluate_nfl_paper_preflight,
)

POLICY = NflPaperPreflightPolicy(
    slippage_bps=Decimal("25"), fee_bps=Decimal("50"), minimum_adjusted_edge=Decimal("0.03")
)


def source(**changes: Decimal) -> NflPaperPreflightInput:
    values: dict[str, Decimal] = {
        "expected_payout": Decimal("0.60"),
        "direct_ask": Decimal("0.50"),
        "raw_edge": Decimal("0.100000"),
        "capital_cap": Decimal("10.00"),
    }
    values.update(changes)
    return NflPaperPreflightInput(**values)


def test_cost_aware_preflight_is_always_execution_blocked() -> None:
    result = evaluate_nfl_paper_preflight(source(), POLICY)
    assert result.execution_price == Decimal("0.502500")
    assert result.quantity == 19
    assert result.gross_cost == Decimal("9.55")
    assert result.estimated_fee == Decimal("0.05")
    assert result.total_cost == Decimal("9.60")
    assert result.effective_unit_cost == Decimal("0.505264")
    assert result.adjusted_edge == Decimal("0.094736")
    assert result.sizing_status == "cost_qualified"
    assert result.risk_decision == "reject"
    assert not result.execution_enabled and result.reason == "nfl_pilot_not_approved"


def test_one_contract_cap_and_unbuyable_price_fail_closed() -> None:
    one = evaluate_nfl_paper_preflight(source(capital_cap=Decimal("0.52")), POLICY)
    assert one.quantity == 1 and one.total_cost == Decimal("0.52")
    unavailable = evaluate_nfl_paper_preflight(source(capital_cap=Decimal("0.51")), POLICY)
    assert unavailable.quantity == 0
    assert unavailable.reason == "capital_cap_cannot_buy_one_contract"


def test_invalid_raw_edge_is_rejected() -> None:
    with pytest.raises(ValueError, match="raw_edge"):
        source(raw_edge=Decimal("0.09"))
