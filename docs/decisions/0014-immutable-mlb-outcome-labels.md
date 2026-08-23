# Decision 0014: Immutable official MLB outcome labels

**Status:** Accepted  
**Date:** 2026-08-22

## Decision

Label one exact complete MLB feature vector only from the normalized official event after it has a
decisive `final` score. Lock the event parent, capture database time after the lock, and atomically
freeze scores, source provenance, vector identity, chronological split boundaries, and semantic
fingerprints in an append-only record. Corrections append facts; they never rewrite history.

Key inventory by the exact split-policy fingerprint and report operational-pregame and retrospective
examples separately. Also report duplicate-event examples because canonical one-vector-per-event
selection has not yet been implemented.

## Consequences

Scheduled, live, postponed, scoreless, tied, mismatched, and incomplete inputs cannot be labeled.
Retrospective examples may support research but cannot prove live pregame performance. Inventory is
descriptive only: it defines no minimum sample threshold, fits no coefficients, emits no probability,
and grants no MLB trading eligibility.
