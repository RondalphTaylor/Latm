from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, call

import pytest


def _load_repair_migration() -> ModuleType:
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0012_repair_phase8_trade_constraints.py"
    )
    spec = importlib.util.spec_from_file_location("phase8_trade_repair", migration_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase8_repair_replaces_all_finalized_trade_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_repair_migration()
    operation_proxy = MagicMock()
    monkeypatch.setattr(migration, "op", operation_proxy)

    migration.upgrade()

    assert operation_proxy.drop_constraint.call_args_list == [
        call(name, "trades", type_="check", if_exists=True)
        for name in (
            "ck_trades_terminal_state",
            "ck_trades_mark_basis",
            "ck_trades_fill_accounting",
        )
    ]
    created = {
        constraint_call.args[0]: constraint_call.args[2]
        for constraint_call in operation_proxy.create_check_constraint.call_args_list
    }
    assert set(created) == {
        "ck_trades_terminal_state",
        "ck_trades_mark_basis",
        "ck_trades_fill_accounting",
    }
    assert "slippage_amount_per_contract IS NOT NULL" in created["ck_trades_terminal_state"]
    assert "effective_unit_cost IS NOT NULL" in created["ck_trades_terminal_state"]
    assert "directional_ask_fallback" in created["ck_trades_mark_basis"]
    assert (
        "gross_cost = reference_gross_cost + slippage_cost" in created["ck_trades_fill_accounting"]
    )


def test_phase8_repair_downgrade_preserves_original_invariants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_repair_migration()
    operation_proxy = MagicMock()
    monkeypatch.setattr(migration, "op", operation_proxy)

    migration.downgrade()

    operation_proxy.assert_not_called()
