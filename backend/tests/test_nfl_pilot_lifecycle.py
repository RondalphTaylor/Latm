from decimal import Decimal

from app.services.nfl_pilot.lifecycle import _floor_cent


def test_nfl_pilot_lifecycle_floors_fractional_contract_payouts_to_cents() -> None:
    assert _floor_cent(Decimal("3") * Decimal("0.333333")) == Decimal("0.99")
    assert _floor_cent(Decimal("3") * Decimal("0.500000")) == Decimal("1.50")


def test_nfl_pilot_lifecycle_never_rounds_mark_value_up() -> None:
    assert _floor_cent(Decimal("4") * Decimal("0.412500")) == Decimal("1.65")
