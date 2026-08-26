# Decision 0019: Immutable MLB dataset-quality audits

**Status:** Accepted  
**Date:** 2026-08-26

## Decision

Evaluate the approved one-example-per-event MLB dataset with a deterministic, research-only V1
quality policy before relying on it for fitting. The audit recomputes chronological split
assignment, pregame timing and holdout provenance, exact feature-policy identity, missingness,
duplicate identities, outcome timing, and the existing no-probability/no-trading flags. It also
reports descriptive outcome, date, team, selected-feature, zero-variance, and conservative
minimum-side source-support summaries.

Persist each exact report append-only with the approved readiness snapshot, complete canonical
source manifest, semantic fingerprints, and one foreign-key lineage row per labeled example.
Exact semantic retries replay the existing audit. A report passes only when it has no structural
errors; warnings remain visible.

Quality status and sample readiness remain separate. A structurally clean dataset can still be too
small to fit, and an audit never fits a model, publishes a probability, or grants opportunity or
trading authority.

## Consequences

Dataset defects and descriptive changes can now be compared against immutable source selections
instead of mutable summaries. The audit can run while collection continues and does not call MLB,
Baseball Savant, market, model-fit, or execution providers. V1 intentionally audits canonical
labeled examples; end-to-end prospective collection conversion rates remain a separate
observability concern because prospective collection runs are not immutable batch records.
