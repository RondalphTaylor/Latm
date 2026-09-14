import Link from "next/link";
import { notFound } from "next/navigation";

import { verifyNflPilotRecommendationAuditExport } from "@/lib/api/client";
import { getAppConfig } from "@/lib/config";

interface AuditVerificationPageProps {
  readonly searchParams: Promise<Record<string, string | string[] | undefined>>;
}

const isUuid = (value: string): boolean =>
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);

const isFingerprint = (value: string): boolean => /^[0-9a-f]{64}$/i.test(value);

export default async function AuditVerificationPage({ searchParams }: AuditVerificationPageProps) {
  const query = await searchParams;
  const scenarioId = typeof query.scenario === "string" ? query.scenario : null;
  if (scenarioId === null || !isUuid(scenarioId)) {
    notFound();
  }
  const fingerprint = typeof query.fingerprint === "string" && isFingerprint(query.fingerprint)
    ? query.fingerprint
    : null;
  const verification = fingerprint === null
    ? null
    : await verifyNflPilotRecommendationAuditExport(getAppConfig(), scenarioId, fingerprint);

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
        </section>
      )}
    </main>
  );
}
