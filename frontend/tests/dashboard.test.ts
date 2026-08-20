import assert from "node:assert/strict";
import test from "node:test";

import { fetchDashboardData } from "@/lib/api/client";
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
    const payload = url.endsWith("/health/ready") ? { status: "ready" } : [];
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
  assert.equal(calls.length, 7);
  assert.ok(calls.every((call) => call.init?.method === undefined));
  assert.ok(calls.every((call) => call.init?.cache === "no-store"));
  assert.ok(calls.every((call) => !call.url.includes("paper-execution")));
  assert.ok(calls.every((call) => !call.url.includes("position-monitoring/run")));
});

test("one malformed resource degrades only that dashboard section", async () => {
  const fetcher = (async (input: string | URL | Request) => {
    const url = String(input);
    let payload: unknown = [];
    if (url.endsWith("/health/ready")) payload = { status: "ready" };
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
