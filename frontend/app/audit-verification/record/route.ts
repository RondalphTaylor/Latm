import { NextRequest } from "next/server";

import { getAppConfig } from "@/lib/config";

const isUuid = (value: string): boolean =>
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);

const isFingerprint = (value: string): boolean => /^[0-9a-f]{64}$/i.test(value);

export async function POST(request: NextRequest): Promise<Response> {
  const form = await request.formData();
  const scenarioId = form.get("scenario");
  const fingerprint = form.get("fingerprint");
  if (typeof scenarioId !== "string" || typeof fingerprint !== "string" || !isUuid(scenarioId) || !isFingerprint(fingerprint)) {
    return new Response("Invalid audit verification request", { status: 400 });
  }
  const query = new URLSearchParams({ scenario_id: scenarioId, fingerprint, limit: "100", offset: "0" });
  const upstream = await fetch(
    `${getAppConfig().backendApiUrl}/nfl-pilot-monitor/audit/verify/journal?${query.toString()}`,
    { method: "POST", cache: "no-store", signal: AbortSignal.timeout(5000) },
  );
  if (!upstream.ok) {
    return new Response("Verification journal is unavailable", { status: upstream.status });
  }
  const result = await upstream.json() as { id: string };
  return Response.redirect(
    new URL(`/audit-verification?scenario=${encodeURIComponent(scenarioId)}&fingerprint=${encodeURIComponent(fingerprint)}&recorded=${encodeURIComponent(result.id)}`, request.url),
    303,
  );
}
