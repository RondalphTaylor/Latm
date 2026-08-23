# Decision 0013: Leakage-safe MLB feature vectors before model fitting

**Status:** Accepted  
**Date:** 2026-08-22

## Decision

Persist a fixed, append-only eight-feature candidate vector derived from one exact official lineup
and Baseball Savant / Statcast snapshot. Pool lineup values by their recorded sample denominators,
require nine-batter coverage per metric, retain missing values as null, and orient all differences so
positive favors the home team. Bind every vector to its event, lineup, and quantitative source with
database constraints and semantic fingerprints.

Define dataset membership with explicit scheduled-start boundaries for train, validation, test, and
prospective holdout. Never randomly shuffle time-ordered games. Label examples only from normalized
official final MLB scores after first pitch.

## Consequences

Retrospective snapshots can support historical research but are structurally ineligible for an
operational pregame model. The current single local example is insufficient to fit or evaluate a
model, so this slice stores no coefficients and emits no win probability. All MLB opportunity and
trading paths remain disabled until a later, independently validated forecasting phase.
