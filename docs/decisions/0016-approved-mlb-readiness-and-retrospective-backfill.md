# Decision 0016: Approved MLB readiness and retrospective backfill

**Status:** Accepted  
**Date:** 2026-08-22

## Decision

Freeze the user-approved MLB research policy as V1. Use June 1, July 1, and August 23, 2026 UTC as
the validation, test, and prospective-holdout boundaries. Require 500 train, 150 validation, 150
test, and 200 prospective-holdout games. Retrospective examples may satisfy the first three
exploratory intervals; only operational pregame examples may satisfy the prospective holdout.

Permit bounded historical research backfill from an official completed game when its stored lineup
contains two posted nine-player batting orders and two starters. Do not set or reinterpret
`complete_for_pregame_model`. Statcast retrieval at or after first pitch must remain
`retrospective`, and every resulting vector and label remains research-only. Reuse the exact official
result, fingerprint, idempotency, and append-only lineage contracts.

## Consequences

The platform can build a sufficiently large exploratory dataset without pretending those lineups
were observed prospectively. The readiness evaluator counts retrospective rows in train,
validation, and test but excludes them from the prospective holdout. A ready dataset is not trading
authority: fitting, probability publication, opportunity generation, and all MLB trading paths stay
disabled until separately implemented and evaluated.
