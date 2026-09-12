from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pytest

from app.models.markets import MarketResolutionRecord
from app.services.nfl_pilot.lifecycle import _floor_cent, _official_resolution


def test_nfl_pilot_lifecycle_floors_fractional_contract_payouts_to_cents() -> None:
    assert _floor_cent(Decimal("3") * Decimal("0.333333")) == Decimal("0.99")
    assert _floor_cent(Decimal("3") * Decimal("0.500000")) == Decimal("1.50")


def test_nfl_pilot_lifecycle_never_rounds_mark_value_up() -> None:
    assert _floor_cent(Decimal("4") * Decimal("0.412500")) == Decimal("1.65")


def test_official_fractional_resolution_rejects_conflicts() -> None:
    now = datetime(2026, 9, 12, tzinfo=UTC)
    fractional = SimpleNamespace(
        yes_payout=Decimal("0.333333"),
        no_payout=Decimal("0.666667"),
        source="official_provider",
        settled_at=now,
        retrieved_at=now,
    )
    assert _official_resolution([cast(MarketResolutionRecord, fractional)]).yes_payout == Decimal(
        "0.333333"
    )
    conflicting = SimpleNamespace(
        yes_payout=Decimal("0.500000"),
        no_payout=Decimal("0.500000"),
        source="official_provider",
        settled_at=now,
        retrieved_at=now,
    )
    with pytest.raises(ValueError, match="conflicting"):
        _official_resolution(
            [
                cast(MarketResolutionRecord, fractional),
                cast(MarketResolutionRecord, conflicting),
            ]
        )
