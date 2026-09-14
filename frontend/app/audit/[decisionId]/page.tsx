import Link from "next/link";
import { notFound } from "next/navigation";

import { fetchNflPilotRecommendationAuditDetail } from "@/lib/api/client";
import { getAppConfig } from "@/lib/config";
import { formatSignedPercent, formatTimestamp, humanize } from "@/lib/format";

interface AuditDetailPageProps {
  readonly params: Promise<{ readonly decisionId: string }>;
  readonly searchParams: Promise<Record<string, string | string[] | undefined>>;
}

const isUuid = (value: string): boolean =>
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);

const isRecommendation = (value: string): value is "hold" | "reduce" | "close" =>
  value === "hold" || value === "reduce" || value === "close";

export default async function AuditDetailPage({ params, searchParams }: AuditDetailPageProps) {
  const { decisionId } = await params;
  const query = await searchParams;
  const scenarioId = typeof query.scenario === "string" ? query.scenario : null;
  if (!isUuid(decisionId) || scenarioId === null || !isUuid(scenarioId)) {
    notFound();
  }

  const detail = await fetchNflPilotRecommendationAuditDetail(getAppConfig(), scenarioId, decisionId);
  if (detail.ok && detail.data === null) {
    notFound();
  }

  const backParams = new URLSearchParams({ scenario: scenarioId });
  if (typeof query.recommendation === "string" && isRecommendation(query.recommendation)) {
    backParams.set("recommendation", query.recommendation);
  }
  if (typeof query.offset === "string" && /^\d+$/.test(query.offset)) {
    backParams.set("offset", query.offset);
  }
  const backHref = `/?${backParams.toString()}#pilot-audit`;
  return (
    <main className="audit-detail-page">
      <p className="eyebrow">NFL pilot · paper only</p>
      <h1>Recommendation decision detail</h1>
      <p>Immutable evidence lineage for one monitoring recommendation. This page cannot create a disposition or submit an order.</p>
      <Link href={backHref}>← Back to recommendation audit</Link>
      {!detail.ok ? (
        <p className="audit-detail-error">Audit detail is unavailable: {detail.error}</p>
      ) : detail.data === null ? null : (
        <dl className="audit-detail-list">
          <dt>Decision</dt><dd>{detail.data.decision_id}</dd>
          <dt>Scenario</dt><dd>{scenarioId}</dd>
          <dt>Position</dt><dd>{detail.data.position_id}</dd>
          <dt>Recommendation</dt><dd>{humanize(detail.data.recommendation)}</dd>
          <dt>Reason</dt><dd>{humanize(detail.data.reason)}</dd>
          <dt>Evaluated</dt><dd>{formatTimestamp(detail.data.evaluated_at)}</dd>
          <dt>Remaining edge</dt><dd>{formatSignedPercent(detail.data.remaining_edge)}</dd>
          <dt>Attention</dt><dd>{detail.data.requires_attention ? "Required" : "Routine"}</dd>
          <dt>Quote lineage</dt><dd>{detail.data.quote_status === null ? "No recorded quote" : `${humanize(detail.data.quote_status)} · ${detail.data.quote_age_seconds ?? "unknown"}s old · ${detail.data.quote_retrieved_at === null ? "no retrieval timestamp" : formatTimestamp(detail.data.quote_retrieved_at)}`}</dd>
          <dt>Forecast lineage</dt><dd>{detail.data.forecast_id === null ? "No recorded forecast" : `${detail.data.forecast_id} · ${detail.data.forecast_valid_at_decision ? "valid at evaluation" : "not valid at evaluation"} · valid until ${detail.data.forecast_valid_until === null ? "unavailable" : formatTimestamp(detail.data.forecast_valid_until)}`}</dd>
          <dt>Paper disposition</dt><dd>{detail.data.disposition_action === null ? "No recorded disposition" : `${humanize(detail.data.disposition_action)} · ${detail.data.disposition_recorded_at === null ? "recorded time unavailable" : formatTimestamp(detail.data.disposition_recorded_at)}`}</dd>
        </dl>
      )}
    </main>
  );
}
