# Decision 0015: Bounded MLB collection and canonical selection

**Status:** Accepted  
**Date:** 2026-08-22

## Decision

Compose the existing read-only official MLB schedule, lineup, Baseball Savant, and deterministic
feature services behind one research-only collection endpoint. Bound a call to seven calendar days
and 25 returned events. Advance only scheduled events strictly before first pitch, stop on incomplete
lineups, and return one explicit result per event. Keep each existing append transaction independent
so retries preserve and reuse partial progress.

Select a modeling view from immutable labels with a database window function that returns at most
one example per event. Prefer operational pregame evidence over retrospective evidence, then use the
newest feature build, official result observation, label time, and stable ID. Exclude retrospective
examples unless a caller explicitly requests research fallback.

## Consequences

The application has no internal scheduler; an external timer must invoke collection near expected
lineup publication. Provider or lineage failures remain isolated to one event after schedule refresh,
and the response never implies a probability or trading action. Canonical selection removes
duplicate-event leakage but does not approve split dates or sample thresholds, fit a model, or make
retrospective performance representative of live operation. MLB probability generation and every
trading path remain disabled.
