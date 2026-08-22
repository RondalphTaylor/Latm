# Decision 0011: Append-only official MLB lineup snapshots

## Context

Probable pitchers and batting orders change before first pitch and do not become available at the
same time. MLB may publish probable pitchers while lineups are still unavailable, and its lineup
surface states that posted orders remain subject to change. A mutable “current lineup” field would
erase when information became available and could let live or postgame data leak into backtests.

## Decision

- Read only the official MLB versioned game feed for one explicit, already-normalized MLB event.
- Validate and retain a bounded source subset: official update time, schedule and status, team IDs,
  probable-pitcher identities/handedness, and batting-order player/position/side data.
- Append observations to `mlb_lineup_snapshots`; use a stable event-plus-source fingerprint for exact
  replay and retain source changes as separate rows.
- Represent each side as `unavailable`, `partial`, or `posted`. `posted` requires exactly nine unique
  order slots and does not mean final or confirmed.
- Label each observation `pregame`, `live`, or `postgame`. Mark it complete for potential pregame
  modeling only when source update and retrieval precede first pitch and both lineups and pitchers
  are present.
- Lock and revalidate the normalized event parent immediately before persistence. Schedule or team
  drift fails closed and requires refreshing event ingestion first.
- Keep all MLB forecasting, opportunity, risk, and execution paths disabled.

## Consequences

The platform can reconstruct which official lineup information it actually observed and when,
without inventing completeness or overwriting earlier states. Manual one-event ingestion is the
smallest reliable slice; recurring scheduling and bulk refresh are deferred. The new data is research
input only until a separately versioned MLB model and leakage-safe as-of selection are implemented.
