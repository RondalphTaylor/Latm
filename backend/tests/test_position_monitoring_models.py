from __future__ import annotations

from typing import cast

from sqlalchemy import Table

from app.models.execution import PaperPositionRecord, PositionEventRecord


def test_position_projection_supports_auditable_phase9_lifecycle() -> None:
    table = cast(Table, PaperPositionRecord.__table__)
    constraints = {constraint.name for constraint in table.constraints}

    assert {
        "ck_positions_status",
        "ck_positions_quantity",
        "ck_positions_version",
        "ck_positions_accounting",
        "ck_positions_lifecycle",
        "ck_positions_fingerprint",
    } <= constraints
    assert {
        "initial_quantity",
        "disposed_quantity",
        "version",
        "original_gross_cost_basis",
        "original_entry_fees",
        "original_total_cost_basis",
        "latest_base_forecast_id",
        "market_resolution_id",
        "projection_fingerprint",
        "closed_at",
        "settled_at",
    } <= set(table.columns.keys())
    open_index = next(
        index for index in table.indexes if index.name == "uq_positions_open_portfolio_market"
    )
    assert open_index.unique is True
    assert str(open_index.dialect_options["postgresql"]["where"]) == "status = 'open'"


def test_position_events_are_append_only_semantic_audit_records() -> None:
    table = cast(Table, PositionEventRecord.__table__)
    constraints = {constraint.name for constraint in table.constraints}

    assert {
        "uq_position_events_semantic_input",
        "ck_position_events_paper_only",
        "ck_position_events_decision",
        "ck_position_events_versions",
        "ck_position_events_quantities",
        "ck_position_events_cost_basis",
        "ck_position_events_decision_shape",
        "ck_position_events_proceeds",
        "ck_position_events_terminal_state",
        "ck_position_events_fingerprints",
    } <= constraints
    foreign_key_targets = {foreign_key.target_fullname for foreign_key in table.foreign_keys}
    assert {
        "positions.id",
        "trades.id",
        "portfolios.id",
        "markets.id",
        "teams.id",
        "market_prices.id",
        "base_forecasts.id",
        "market_resolutions.id",
        "portfolio_snapshots.id",
    } <= foreign_key_targets
    assert table.c.market_price_id.nullable is True
    assert table.c.base_forecast_id.nullable is True
    assert table.c.market_resolution_id.nullable is True
    assert table.c.portfolio_snapshot_before_id.nullable is False
