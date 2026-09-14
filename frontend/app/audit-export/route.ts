import { NextRequest } from "next/server";

import { getAppConfig } from "@/lib/config";

const isUuid = (value: string): boolean =>
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);

export async function GET(request: NextRequest): Promise<Response> {
  const scenarioId = request.nextUrl.searchParams.get("scenario");
  const format = request.nextUrl.searchParams.get("format");
  const recommendation = request.nextUrl.searchParams.get("recommendation");
  if (scenarioId === null || !isUuid(scenarioId) || (format !== "csv" && format !== "json")) {
    return new Response("Invalid audit export request", { status: 400 });
  }
  if (recommendation !== null && recommendation !== "hold" && recommendation !== "reduce" && recommendation !== "close") {
    return new Response("Invalid audit recommendation", { status: 400 });
  }

  const query = new URLSearchParams({ scenario_id: scenarioId, format, limit: "100", offset: "0" });
  if (recommendation !== null) {
    query.set("recommendation", recommendation);
  }
  const upstream = await fetch(
    `${getAppConfig().backendApiUrl}/nfl-pilot-monitor/audit/export?${query.toString()}`,
    { cache: "no-store", signal: AbortSignal.timeout(5000) },
  );
  if (!upstream.ok) {
    return new Response("Audit export is unavailable", { status: upstream.status });
  }
  return new Response(await upstream.arrayBuffer(), {
    headers: {
      "Content-Disposition": upstream.headers.get("content-disposition") ?? "attachment",
      "Content-Type": upstream.headers.get("content-type") ?? "application/octet-stream",
    },
  });
}
