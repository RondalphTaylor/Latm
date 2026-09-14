import assert from "node:assert/strict";
import test from "node:test";
import { renderToStaticMarkup } from "react-dom/server";

import { Dashboard } from "@/components/dashboard";
import type { DashboardData, LoadState } from "@/lib/api/client";
import type { PortfolioResponse } from "@/lib/api/contracts";
import { buildDashboardViewModel } from "@/lib/dashboard/view-model";

const ok = <T,>(data: T): LoadState<T> => ({ data, ok: true, error: null });

function dashboardData(portfolios: readonly PortfolioResponse[] = []): DashboardData {
  return {
    loadedAt: "2026-08-20T12:00:00Z",
    health: ok({ status: "ready" }),
    markets: ok([]),
    events: ok([]),
    forecasts: ok([]),
    opportunities: ok([]),
    portfolios: ok(portfolios),
    positions: ok([]),
    trades: ok([]),
    positionEvents: ok([]),
    forecastPerformance: ok(null),
    tradingPerformance: ok(null),
    mlbReadiness: ok({
      policy_name: "mlb_dataset_readiness",
      policy_version: "v1",
      policy_fingerprint: "a".repeat(64),
      split_policy_fingerprint: "b".repeat(64),
      validation_start: "2026-06-01T00:00:00Z",
      test_start: "2026-07-01T00:00:00Z",
      prospective_holdout_start: "2026-08-23T00:00:00Z",
      minimum_split_counts: { train: 500, validation: 150, test: 150, prospective_holdout: 200 },
      eligible_split_counts: { train: 0, validation: 0, test: 14, prospective_holdout: 0 },
      shortfall_by_split: { train: 500, validation: 150, test: 136, prospective_holdout: 200 },
      exploratory_fit_data_ready: false,
      prospective_evaluation_data_ready: false,
      retrospective_allowed_for_exploratory_splits: true,
      prospective_holdout_requires_operational_pregame: true,
      model_fitting_enabled: false,
      probability_generation_enabled: false,
      automatic_trading_enabled: false,
      blockers: ["train_shortfall:500"],
    }),
    mlbBackfillCheckpoint: ok(null),
    mlbBackfillBatches: ok([]),
    nflAttention: ok([]),
    nflAlerts: ok([]),
    nflDispositions: ok([]),
    nflPilotPositions: ok([]),
    nflPilotLedger: ok(null),
    nflRecommendationAudit: ok([]),
    pilotAuditScenarioId: null,
    pilotAuditRecommendation: null,
  };
}

test("dashboard renders all read-only monitoring sections and a permanent paper boundary", () => {
  const data = dashboardData();
  const html = renderToStaticMarkup(
    <Dashboard data={data} mode="paper" viewModel={buildDashboardViewModel(data)} />,
  );

  for (const heading of [
    "Paper positions",
    "Forecasts",
    "Current opportunities",
    "NBA market records",
    "MLB dataset readiness",
    "Recent paper activity",
    "Paper disposition history",
    "Paper pilot position detail",
    "Paper pilot ledger",
    "Recommendation audit",
    "Performance &amp; calibration",
  ]) {
    assert.ok(html.includes(heading));
  }
  assert.ok(html.includes("paper / simulated"));
  assert.ok(html.includes("Live orders</dt><dd>Not implemented"));
  assert.ok(!html.includes("<button"));
  assert.ok(!html.includes("<form"));
  assert.ok(html.includes("14<span> / 150"));
  assert.ok(html.includes("Model fitting: disabled"));
});

test("dashboard renders immutable NFL pilot disposition facts without controls", () => {
  const original = dashboardData();
  const data: DashboardData = {
    ...original,
    nflDispositions: ok([
      {
        id: "disposition-1",
        decision_id: "decision-1",
        position_id: "position-12345678",
        action: "reduce",
        quantity: 2,
        execution_price: "0.410000",
        gross_proceeds: "0.82",
        allocated_cost_basis: "0.90",
        realized_pnl_increment: "-0.08",
        recorded_at: "2026-09-13T20:00:00Z",
        execution_mode: "paper",
        live_trading_enabled: false,
      },
    ]),
    nflPilotPositions: ok([
      {
        id: "position-12345678",
        entry_id: "entry-1",
        scenario_id: "scenario-1",
        market_id: "market-1",
        direction: "yes",
        quantity: 4,
        remaining_quantity: 2,
        disposed_quantity: 2,
        total_cost_basis: "1.80",
        remaining_cost_basis: "0.90",
        status: "open",
        mark_price: "0.410000",
        market_value: "0.82",
        unrealized_pnl: "-0.08",
        realized_pnl: "-0.08",
        updated_at: "2026-09-13T20:00:00Z",
        execution_mode: "paper",
        live_trading_enabled: false,
      },
    ]),
    nflPilotLedger: ok({
      open_positions: 1,
      settled_positions: 0,
      committed_capital: "0.90",
      realized_pnl: "-0.08",
      current_bankroll: "99.92",
      available_bankroll: "99.02",
    }),
    nflRecommendationAudit: ok([
      {
        decision_id: "decision-1",
        position_id: "position-12345678",
        recommendation: "reduce",
        reason: "remaining_edge_below_3_percent",
        requires_attention: true,
        remaining_edge: "0.020000",
        evaluated_at: "2026-09-13T19:59:00Z",
        quote_status: "fresh",
        quote_age_seconds: 30,
        quote_retrieved_at: "2026-09-13T19:58:30Z",
        forecast_id: "forecast-1",
        forecast_valid_until: "2026-09-13T20:15:00Z",
        forecast_valid_at_decision: true,
        disposition_action: "reduce",
        disposition_recorded_at: "2026-09-13T20:00:00Z",
      },
    ]),
    pilotAuditScenarioId: "scenario-1",
    pilotAuditRecommendation: "reduce",
  };
  const html = renderToStaticMarkup(
    <Dashboard data={data} mode="paper" viewModel={buildDashboardViewModel(data)} />,
  );

  assert.ok(html.includes("Latest immutable simulated NFL exits"));
  assert.ok(html.includes("position"));
  assert.ok(html.includes("−$0.08"));
  assert.ok(html.includes("1 linked exit"));
  assert.ok(html.includes("$99.02"));
  assert.ok(html.includes("30s old"));
  assert.ok(html.includes("Decision:"));
  assert.ok(html.includes("recommendation=reduce"));
  assert.ok(!html.includes("<button"));
  assert.ok(!html.includes("<form"));
});

test("MLB workflow observability renders checkpoint and latest immutable batch", () => {
  const original = dashboardData();
  const checkpoint = {
    id: "checkpoint-1",
    policy_name: "mlb_historical_backfill",
    policy_version: "v1",
    policy_fingerprint: "c".repeat(64),
    split_policy_fingerprint: "b".repeat(64),
    status: "active" as const,
    regular_season_start: "2026-03-25",
    validation_start_date: "2026-06-01",
    test_start_date: "2026-07-01",
    prospective_holdout_start_date: "2026-08-23",
    train_cursor_date: "2026-05-31",
    train_cursor_offset: 0,
    validation_cursor_date: "2026-06-30",
    validation_cursor_offset: 0,
    test_cursor_date: "2026-08-21",
    test_cursor_offset: 0,
    batch_limit: 10,
    version: 1,
    batches_completed: 1,
    events_examined: 10,
    examples_created: 3,
    last_run_at: "2026-08-23T14:30:00Z",
    finished_at: null,
    state_fingerprint: "d".repeat(64),
    research_only: true as const,
    probability_generated: false as const,
    automatic_trading_eligible: false as const,
    created_at: "2026-08-23T14:30:00Z",
    updated_at: "2026-08-23T14:30:00Z",
  };
  const batch = {
    id: "batch-1",
    checkpoint_id: "checkpoint-1",
    sequence: 1,
    split: "test" as const,
    window_date: "2026-08-22",
    offset: 0,
    batch_limit: 10,
    cursor_date_after: "2026-08-21",
    cursor_offset_after: 0,
    run_at: "2026-08-23T14:30:00Z",
    events_refreshed: 15,
    examined: 10,
    retrospective_vectors_built: 3,
    examples_labeled: 3,
    examples_created: 3,
    result_counts: { retrospective_example_ready: 3, lineup_incomplete: 7 },
    input_fingerprint: "e".repeat(64),
    result_fingerprint: "f".repeat(64),
    research_only: true as const,
    probability_generated: false as const,
    automatic_trading_eligible: false as const,
    created_at: "2026-08-23T14:30:00Z",
  };
  const data: DashboardData = {
    ...original,
    mlbBackfillCheckpoint: ok(checkpoint),
    mlbBackfillBatches: ok([batch]),
  };
  const html = renderToStaticMarkup(
    <Dashboard data={data} mode="paper" viewModel={buildDashboardViewModel(data)} />,
  );

  assert.ok(html.includes("Batch 1"));
  assert.ok(html.includes("2026-08-22"));
  assert.ok(html.includes("retrospective example ready: 3"));
  assert.ok(html.includes("lineup incomplete: 7"));
});

test("authoritative portfolio decimal strings render without replacing a legitimate zero", () => {
  const portfolio: PortfolioResponse = {
    id: "portfolio-1",
    name: "Primary Paper Portfolio",
    execution_mode: "paper",
    currency: "USD",
    starting_bankroll: "1000.00",
    status: "active",
    is_active: true,
    latest_snapshot: {
      id: "snapshot-1",
      sequence: 3,
      currency: "USD",
      starting_bankroll: "1000.00",
      current_bankroll: "987.65",
      cash_balance: "987.65",
      reserved_capital: "0.00",
      committed_capital: "0.00",
      available_bankroll: "987.65",
      realized_pnl: "-12.35",
      open_position_value: "0.00",
      unrealized_pnl: "0.00",
      total_portfolio_value: "987.65",
      captured_at: "2026-08-20T11:00:00Z",
    },
  };
  const data = dashboardData([portfolio]);
  const html = renderToStaticMarkup(
    <Dashboard data={data} mode="paper" viewModel={buildDashboardViewModel(data)} />,
  );

  assert.ok(html.includes("$987.65"));
  assert.ok(html.includes("−$12.35"));
  assert.ok(html.includes("$0.00"));
});

test("a resource failure is explicit and does not erase healthy sections", () => {
  const original = dashboardData();
  const data: DashboardData = {
    ...original,
    markets: { data: [], ok: false, error: "/markets returned HTTP 503" },
  };
  const html = renderToStaticMarkup(
    <Dashboard data={data} mode="paper" viewModel={buildDashboardViewModel(data)} />,
  );

  assert.ok(html.includes("Partial data view"));
  assert.ok(html.includes("Markets are unavailable"));
  assert.ok(html.includes("No operational forecasts"));
  assert.ok(!html.includes("Markets are unavailable</h3><p>0"));
});
