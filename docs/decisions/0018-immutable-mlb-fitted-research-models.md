# Decision 0018: Immutable MLB fitted research models

**Status:** Accepted  
**Date:** 2026-08-24

## Decision

Persist a deterministic MLB logistic artifact only when the approved canonical dataset satisfies
the existing 500 train, 150 validation, and 150 untouched-test thresholds. Materialization has no
request body or runtime controls and reuses the frozen fitting policy, chronological split policy,
and one-vector-per-event canonical selection.

Store the complete fitted artifact append-only, including standardization, coefficients,
regularization selection, validation/test metrics, policy/data/model fingerprints, readiness
snapshot, and the exact ordered source manifest. Protect every source example with a normalized
foreign-key lineage row. Stable semantic identities make exact retries replay the existing model;
conflicting effective versions fail closed.

Keep the artifact research-only. Persistence does not register an operational forecast model,
publish a probability, enter an opportunity path, or grant trading authority. Prospective-holdout
examples remain excluded from fitting.

## Consequences

The platform can preserve the first approved exploratory model without losing its exact training
lineage or relying on a mutable "latest" record. Current live data still fails the readiness gate,
so the materialization endpoint returns an exact `409` shortfall until historical collection
finishes. Prospective prediction capture and model evaluation remain separate later decisions.
