import Link from "next/link";
import { notFound } from "next/navigation";

import {
  fetchNflPilotAuditVerificationHistory,
  verifyNflPilotRecommendationAuditExport,
} from "@/lib/api/client";
import { getAppConfig } from "@/lib/config";
import { formatTimestamp } from "@/lib/format";

interface AuditVerificationPageProps {
  readonly searchParams: Promise<Record<string, string | string[] | undefined>>;
}

const isUuid = (value: string): boolean =>
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);

const isFingerprint = (value: string): boolean => /^[0-9a-f]{64}$/i.test(value);

const historyPageSize = 8;

function historyHref(scenarioId: string, fingerprint: string | null, offset: number): string {
  const params = new URLSearchParams({ scenario: scenarioId });
  if (fingerprint !== null) {
    params.set("fingerprint", fingerprint);
  }
  if (offset > 0) {
    params.set("history_offset", String(offset));
  }
  return `/audit-verification?${params.toString()}`;
}

function historyDetailHref(
  scenarioId: string,
  verificationId: string,
  fingerprint: string | null,
  offset: number,
): string {
  const params = new URLSearchParams({ scenario: scenarioId });
  if (fingerprint !== null) {
    params.set("fingerprint", fingerprint);
  }
  if (offset > 0) {
    params.set("history_offset", String(offset));
  }
  return `/audit-verification/${encodeURIComponent(verificationId)}?${params.toString()}`;
}

export default async function AuditVerificationPage({ searchParams }: AuditVerificationPageProps) {
  const query = await searchParams;
  const scenarioId = typeof query.scenario === "string" ? query.scenario : null;
  if (scenarioId === null || !isUuid(scenarioId)) {
    notFound();
  }
  const fingerprint = typeof query.fingerprint === "string" && isFingerprint(query.fingerprint)
    ? query.fingerprint
    : null;
  const requestedHistoryOffset = typeof query.history_offset === "string" && /^\d+$/.test(query.history_offset)
    ? Number(query.history_offset)
    : 0;
  const historyOffset = Number.isSafeInteger(requestedHistoryOffset) && requestedHistoryOffset <= 10_000
    ? requestedHistoryOffset
    : 0;
  const verification = fingerprint === null
    ? null
    : await verifyNflPilotRecommendationAuditExport(getAppConfig(), scenarioId, fingerprint);
  const history = await fetchNflPilotAuditVerificationHistory(getAppConfig(), scenarioId, historyOffset);
  const historyRows = history.data.slice(0, historyPageSize);
  const historyHasNext = history.data.length > historyPageSize;

  return (
    <main className="audit-detail-page">
      <p className="eyebrow">NFL pilot · paper only</p>
      <h1>Verify audit export</h1>
      <p>Paste the fingerprint from a downloaded export. This compares it with the current first 100 immutable audit rows for this scenario; it does not upload a file or change any data.</p>
      <Link href={`/?scenario=${encodeURIComponent(scenarioId)}#pilot-audit`}>← Back to recommendation audit</Link>
      <form className="audit-verification-form" method="get">
        <input name="scenario" type="hidden" value={scenarioId} />
        <label htmlFor="fingerprint">Export fingerprint</label>
        <input
          defaultValue={fingerprint ?? ""}
          id="fingerprint"
          name="fingerprint"
          pattern="[0-9a-fA-F]{64}"
          placeholder="64-character SHA-256 fingerprint"
          required
        />
        <button type="submit">Verify fingerprint</button>
      </form>
      {verification === null ? null : !verification.ok ? (
        <p className="audit-detail-error">Verification is unavailable: {verification.error}</p>
      ) : verification.data === null ? (
        <p className="audit-detail-error">The selected scenario is unavailable.</p>
      ) : (
        <section className={verification.data.matches ? "audit-verification-match" : "audit-verification-mismatch"}>
          <h2>{verification.data.matches ? "Match confirmed" : "No match"}</h2>
          <p>{verification.data.matches ? "The current audit slice is identical to the exported slice." : "The current audit slice differs from this export."}</p>
          <dl className="audit-detail-list">
            <dt>Provided fingerprint</dt><dd>{verification.data.provided_fingerprint}</dd>
            <dt>Current fingerprint</dt><dd>{verification.data.current_fingerprint}</dd>
            <dt>Rows compared</dt><dd>{verification.data.row_count}</dd>
            <dt>Scenario policy</dt><dd>{verification.data.scenario_policy_version}</dd>
            <dt>Retention policy</dt><dd>{verification.data.retention_policy_version}</dd>
          </dl>
          <form action="/audit-verification/record" method="post">
            <input name="scenario" type="hidden" value={scenarioId} />
            <input name="fingerprint" type="hidden" value={fingerprint ?? ""} />
            <button type="submit">Record this verification</button>
          </form>
        </section>
      )}
      <section className="audit-verification-history" aria-labelledby="verification-history-title">
        <h2 id="verification-history-title">Recorded verification history</h2>
        {!history.ok ? <p className="audit-detail-error">History is unavailable: {history.error}</p> : historyRows.length === 0 ? <p>No verification checks have been explicitly recorded yet.</p> : (
          <ul>
            {historyRows.map((item) => <li key={item.id}>
              <strong>{item.matches ? "Match" : "No match"}</strong> · {formatTimestamp(item.verified_at)} · {item.row_count} rows<br />
              <small>Provided {item.provided_fingerprint.slice(0, 12)}… · Current {item.current_fingerprint.slice(0, 12)}… · <Link href={historyDetailHref(scenarioId, item.id, fingerprint, historyOffset)}>View detail</Link></small>
            </li>)}
          </ul>
        )}
        {!history.ok ? null : (
          <nav className="audit-pagination" aria-label="Verification history pages">
            {historyOffset === 0 ? <span>Previous</span> : <Link href={historyHref(scenarioId, fingerprint, Math.max(0, historyOffset - historyPageSize))}>Previous</Link>}
            <span>{historyRows.length === 0 ? "No rows" : `Rows ${historyOffset + 1}–${historyOffset + historyRows.length}`}</span>
            {historyHasNext ? <Link href={historyHref(scenarioId, fingerprint, historyOffset + historyPageSize)}>Next</Link> : <span>Next</span>}
          </nav>
        )}
      </section>
    </main>
  );
}
