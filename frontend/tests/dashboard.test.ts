import assert from "node:assert/strict";
import test from "node:test";

import {
  fetchDashboardData,
  fetchNflPilotRecommendationAuditDetail,
  fetchNflPilotAuditVerificationHistory,
  verifyNflPilotRecommendationAuditExport,
} from "@/lib/api/client";
import { getAppConfig } from "@/lib/config";
import {
  decimalSign,
  formatMoney,
  formatProbability,
  formatSignedMoney,
} from "@/lib/format";

test("formatters distinguish missing, zero, positive, and negative values", () => {
  assert.equal(formatMoney(null), "Unavailable");
  assert.equal(formatMoney("0.00"), "$0.00");
  assert.equal(formatSignedMoney("12.34"), "+$12.34");
  assert.equal(formatSignedMoney("-12.34"), "−$12.34");
  assert.equal(formatProbability("0.625000"), "62.5%");
  assert.equal(decimalSign("0.00"), "flat");
  assert.equal(decimalSign("0.01"), "positive");
  assert.equal(decimalSign("-0.01"), "negative");
});

test("configuration defaults to paper and validates the server-side backend URL", () => {
  const tradingMode = process.env.TRADING_MODE;
  const backendApiUrl = process.env.BACKEND_API_URL;
  try {
    delete process.env.TRADING_MODE;
    delete process.env.BACKEND_API_URL;
    assert.deepEqual(getAppConfig(), {
      tradingMode: "paper",
      backendApiUrl: "http://localhost:8000",
    });

    process.env.TRADING_MODE = "live";
    assert.throws(() => getAppConfig(), /Unsupported TRADING_MODE/);

    process.env.TRADING_MODE = "paper";
    process.env.BACKEND_API_URL = "file:///tmp/backend";
    assert.throws(() => getAppConfig(), /must use http or https/);
  } finally {
    if (tradingMode === undefined) delete process.env.TRADING_MODE;
    else process.env.TRADING_MODE = tradingMode;
    if (backendApiUrl === undefined) delete process.env.BACKEND_API_URL;
    else process.env.BACKEND_API_URL = backendApiUrl;
  }
});

test("dashboard adapter uses only bounded GET reads and skips portfolio routes when empty", async () => {
  const calls: Array<{ readonly url: string; readonly init?: RequestInit }> = [];
  const fetcher = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    if (url.endsWith("/mlb-research-backfill-workflow")) {
      return new Response(JSON.stringify({ detail: "not started" }), { status: 404 });
    }
    const payload = url.endsWith("/health/ready") || url.endsWith("/mlb-approved-dataset-readiness")
      ? { status: "ready" }
      : [];
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as typeof fetch;

  const result = await fetchDashboardData(
    { tradingMode: "paper", backendApiUrl: "http://backend.test" },
    fetcher,
  );

  assert.equal(result.health.data?.status, "ready");
  assert.equal(result.portfolios.ok, true);
  assert.deepEqual(result.positions.data, []);
  assert.equal(result.mlbBackfillCheckpoint.ok, true);
  assert.equal(result.mlbBackfillCheckpoint.data, null);
  assert.equal(calls.length, 14);
  assert.ok(calls.every((call) => call.init?.method === undefined));
  assert.ok(calls.every((call) => call.init?.cache === "no-store"));
  assert.ok(calls.every((call) => !call.url.includes("paper-execution")));
  assert.ok(calls.every((call) => !call.url.includes("position-monitoring/run")));
  assert.ok(calls.some((call) => call.url.includes("/nfl-pilot-dispositions?")));
  assert.ok(calls.some((call) => call.url.includes("/nfl-pilot-positions?")));
});

test("one malformed resource degrades only that dashboard section", async () => {
  const fetcher = (async (input: string | URL | Request) => {
    const url = String(input);
    let payload: unknown = [];
    if (url.endsWith("/health/ready")) payload = { status: "ready" };
    if (url.endsWith("/mlb-approved-dataset-readiness")) payload = { status: "ready" };
    if (url.endsWith("/mlb-research-backfill-workflow")) {
      return new Response(JSON.stringify({ detail: "not started" }), { status: 404 });
    }
    if (url.includes("/markets?")) payload = { not: "a list" };
    return new Response(JSON.stringify(payload), { status: 200 });
  }) as typeof fetch;

  const result = await fetchDashboardData(
    { tradingMode: "paper", backendApiUrl: "http://backend.test" },
    fetcher,
  );

  assert.equal(result.markets.ok, false);
  assert.match(result.markets.error ?? "", /unexpected payload/);
  assert.equal(result.forecasts.ok, true);
  assert.deepEqual(result.forecasts.data, []);
});

test("dashboard forwards only the selected recommendation audit filter", async () => {
  const calls: string[] = [];
  const fetcher = (async (input: string | URL | Request) => {
    const url = String(input);
    calls.push(url);
    const payload = url.endsWith("/health/ready") || url.endsWith("/mlb-approved-dataset-readiness")
      ? { status: "ready" }
      : [];
    return new Response(JSON.stringify(payload), { status: 200 });
  }) as typeof fetch;

  await fetchDashboardData(
    { tradingMode: "paper", backendApiUrl: "http://backend.test" },
    fetcher,
    {
      pilotAuditScenarioId: "c8eb0233-8d80-46e3-8ce1-05b0687cf1e1",
      pilotAuditRecommendation: "reduce",
    },
  );

  assert.ok(calls.some((url) => url.includes(
    "/nfl-pilot-monitor/audit?scenario_id=c8eb0233-8d80-46e3-8ce1-05b0687cf1e1&limit=9&offset=0&recommendation=reduce",
  )));
  assert.ok(calls.every((url) => !url.includes("paper-execution")));
});

test("decision-detail adapter makes one bounded read and treats a missing record as absent", async () => {
  const calls: string[] = [];
  const fetcher = (async (input: string | URL | Request) => {
    calls.push(String(input));
    return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
  }) as typeof fetch;

  const result = await fetchNflPilotRecommendationAuditDetail(
    { tradingMode: "paper", backendApiUrl: "http://backend.test" },
    "c8eb0233-8d80-46e3-8ce1-05b0687cf1e1",
    "b8eb0233-8d80-46e3-8ce1-05b0687cf1e1",
    fetcher,
  );

  assert.equal(result.ok, true);
  assert.equal(result.data, null);
  assert.deepEqual(calls, [
    "http://backend.test/nfl-pilot-monitor/audit/b8eb0233-8d80-46e3-8ce1-05b0687cf1e1?scenario_id=c8eb0233-8d80-46e3-8ce1-05b0687cf1e1",
  ]);
});

test("audit verification adapter uses a bounded GET without execution routes", async () => {
  const calls: string[] = [];
  const fetcher = (async (input: string | URL | Request) => {
    calls.push(String(input));
    return new Response(JSON.stringify({
      provided_fingerprint: "a".repeat(64), current_fingerprint: "a".repeat(64), matches: true,
      row_count: 1, scenario_policy_version: "v1", scenario_policy_fingerprint: "b".repeat(64),
      retention_policy_version: "append-only",
    }), { status: 200 });
  }) as typeof fetch;

  const result = await verifyNflPilotRecommendationAuditExport(
    { tradingMode: "paper", backendApiUrl: "http://backend.test" },
    "c8eb0233-8d80-46e3-8ce1-05b0687cf1e1",
    "a".repeat(64),
    fetcher,
  );

  assert.equal(result.data?.matches, true);
  assert.ok(calls[0]?.includes("/nfl-pilot-monitor/audit/verify?"));
  assert.ok(calls.every((url) => !url.includes("paper-execution")));
});

test("audit verification history adapter reads a bounded page of the immutable journal", async () => {
  const calls: string[] = [];
  const fetcher = (async (input: string | URL | Request) => {
    calls.push(String(input));
    return new Response(JSON.stringify([{
      id: "history-1",
      scenario_id: "c8eb0233-8d80-46e3-8ce1-05b0687cf1e1",
      provided_fingerprint: "a".repeat(64),
      current_fingerprint: "b".repeat(64),
      matches: false,
      row_count: 2,
      verified_at: "2026-09-14T15:00:00Z",
    }]), { status: 200 });
  }) as typeof fetch;

  const result = await fetchNflPilotAuditVerificationHistory(
    { tradingMode: "paper", backendApiUrl: "http://backend.test" },
    "c8eb0233-8d80-46e3-8ce1-05b0687cf1e1",
    8,
    fetcher,
  );

  assert.equal(result.data?.[0]?.matches, false);
  assert.ok(calls[0]?.includes("/nfl-pilot-monitor/audit/verification-history?"));
  assert.ok(calls[0]?.includes("limit=9&offset=8"));
  assert.ok(calls.every((url) => !url.includes("paper-execution")));
});
