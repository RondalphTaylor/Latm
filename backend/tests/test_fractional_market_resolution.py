from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain.markets import BinaryMarketResolution, OutcomeSide, SettlementResult


def resolution_payload(**updates: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "result": "scalar",
        "yes_payout": "0.333333",
        "no_payout": "0.666667",
        "resolution_type": "fractional_binary",
        "settled_at": datetime(2026, 9, 10, tzinfo=UTC),
        "retrieved_at": datetime(2026, 9, 10, 1, tzinfo=UTC),
        "source_snapshot": {},
    }
    payload.update(updates)
    return payload


@pytest.mark.parametrize("payout", ["0.000001", "0.333333", "0.500000", "0.999999"])
def test_fractional_resolution_preserves_explicit_complement(payout: str) -> None:
    result = BinaryMarketResolution.model_validate(
        resolution_payload(yes_payout=payout, no_payout=Decimal(1) - Decimal(payout))
    )
    assert result.result is SettlementResult.SCALAR
    assert result.yes_payout == Decimal(payout)
    assert result.yes_payout + result.no_payout == Decimal(1)
    assert "scalar" not in {side.value for side in OutcomeSide}


@pytest.mark.parametrize(
    "changes",
    [
        {"yes_payout": "0", "no_payout": "1"},
        {"yes_payout": "1", "no_payout": "0"},
        {"yes_payout": "0.3333333", "no_payout": "0.6666667"},
        {"no_payout": "0.5"},
        {"yes_payout": "NaN"},
        {"yes_payout": "Infinity"},
        {"resolution_type": "standard_binary"},
        {"result": "yes"},
        {"result": "no"},
        {"result": "void"},
        {"settled_at": "2026-09-10T00:00:00"},
        {"retrieved_at": "2026-09-09T00:00:00Z"},
    ],
)
def test_fractional_resolution_rejects_inconsistent_or_unsupported_data(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        BinaryMarketResolution.model_validate(resolution_payload(**changes))


@pytest.mark.parametrize("side,payout", [(OutcomeSide.YES, "1"), (OutcomeSide.NO, "0")])
def test_existing_standard_binary_inputs_still_work(side: OutcomeSide, payout: str) -> None:
    result = BinaryMarketResolution.model_validate(
        resolution_payload(
            result=side,
            yes_payout=payout,
            no_payout=Decimal(1) - Decimal(payout),
            resolution_type="standard_binary",
        )
    )
    assert result.result.value == side.value
    assert result.resolution_type == "standard_binary"
