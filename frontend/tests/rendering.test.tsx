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
    "Recent paper activity",
    "Performance &amp; calibration",
  ]) {
    assert.ok(html.includes(heading));
  }
  assert.ok(html.includes("paper / simulated"));
  assert.ok(html.includes("Live orders</dt><dd>Not implemented"));
  assert.ok(!html.includes("<button"));
  assert.ok(!html.includes("<form"));
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
