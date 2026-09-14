import Link from "next/link";
import { notFound } from "next/navigation";

import { fetchNflPilotAuditVerificationDetail } from "@/lib/api/client";
import { getAppConfig } from "@/lib/config";
import { formatTimestamp } from "@/lib/format";

interface AuditVerificationDetailPageProps {
  readonly params: Promise<{ readonly verificationId: string }>;
  readonly searchParams: Promise<Record<string, string | string[] | undefined>>;
}

const isUuid = (value: string): boolean =>
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);

const isFingerprint = (value: string): boolean => /^[0-9a-f]{64}$/i.test(value);

function historyHref(
  scenarioId: string, fingerprint: string | null, offset: number, outcome: "match" | "mismatch" | null,
): string {
  const query = new URLSearchParams({ scenario: scenarioId });
  if (fingerprint !== null) query.set("fingerprint", fingerprint);
  if (offset > 0) query.set("history_offset", String(offset));
  if (outcome !== null) query.set("history_outcome", outcome);
  return `/audit-verification?${query.toString()}`;
}

export default async function AuditVerificationDetailPage({
  params,
  searchParams,
}: AuditVerificationDetailPageProps) {
  const { verificationId } = await params;
  const query = await searchParams;
  const scenarioId = typeof query.scenario === "string" ? query.scenario : null;
  if (!isUuid(verificationId) || scenarioId === null || !isUuid(scenarioId)) notFound();
  const fingerprint = typeof query.fingerprint === "string" && isFingerprint(query.fingerprint)
    ? query.fingerprint
    : null;
  const requestedOffset = typeof query.history_offset === "string" && /^\d+$/.test(query.history_offset)
    ? Number(query.history_offset)
    : 0;
  const historyOffset = Number.isSafeInteger(requestedOffset) && requestedOffset <= 10_000
    ? requestedOffset
    : 0;
  const historyOutcome = query.history_outcome === "match" || query.history_outcome === "mismatch"
    ? query.history_outcome
    : null;
  const detail = await fetchNflPilotAuditVerificationDetail(
    getAppConfig(), scenarioId, verificationId,
  );
  if (detail.ok && detail.data === null) notFound();

  return (
    <main className="audit-detail-page">
      <p className="eyebrow">NFL pilot · paper only</p>
      <h1>Verification record detail</h1>
      <p>Immutable, user-requested evidence that an audit-export fingerprint was checked. This page cannot record, edit, or remove a verification.</p>
      <Link href={historyHref(scenarioId, fingerprint, historyOffset, historyOutcome)}>← Back to verification history</Link>
      {!detail.ok ? (
        <p className="audit-detail-error">Verification detail is unavailable: {detail.error}</p>
      ) : detail.data === null ? null : (
        <dl className="audit-detail-list">
          <dt>Verification</dt><dd>{detail.data.id}</dd>
          <dt>Scenario</dt><dd>{detail.data.scenario_id}</dd>
          <dt>Recorded</dt><dd>{formatTimestamp(detail.data.verified_at)}</dd>
          <dt>Result</dt><dd>{detail.data.matches ? "Match" : "No match"}</dd>
          <dt>Rows compared</dt><dd>{detail.data.row_count}</dd>
          <dt>Provided fingerprint</dt><dd>{detail.data.provided_fingerprint}</dd>
          <dt>Recorded current fingerprint</dt><dd>{detail.data.current_fingerprint}</dd>
          <dt>Scenario policy version</dt><dd>{detail.data.scenario_policy_version}</dd>
          <dt>Scenario policy fingerprint</dt><dd>{detail.data.scenario_policy_fingerprint}</dd>
          <dt>Retention policy</dt><dd>{detail.data.retention_policy_version}</dd>
        </dl>
      )}
    </main>
  );
}
