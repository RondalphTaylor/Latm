# Decision 0004: Versioned Elo Base Forecasting

**Status:** Accepted
**Date:** 2026-08-01

## Context

Phase 4 needs an independent NBA game-win probability that is simple enough to inspect, reproduce, and evaluate before adding external evidence or AI adjustments. Forecast history must survive corrections and reruns, and a simulated historical forecast must not be presented as though the platform generated it contemporaneously. The local database currently holds normalized event snapshots but not historical result-observation timestamps.

## Decision

- Implement deterministic `nba_elo` V1 behind the common forecasting protocol.
- Initialize unseen teams at 1500, use K=20, logistic scale 400, and add 100 Elo points for the recorded home team.
- Calculate the standard Elo logistic home probability and update ratings with a zero-sum `K * (actual - expected)` delta.
- Use deterministic decimal arithmetic, six-decimal complementary probabilities, and four-decimal ratings.
- Replay only local provider-neutral NBA records; generation never calls a provider.
- Order history by scheduled tip and stable event ID, and apply only results with a scheduled start strictly before the target cutoff. Do not allow the target, simultaneous events, or future events to affect a forecast.
- Exclude postponed records. Fingerprint and count incomplete and equal-score final records, but do not update ratings from them.
- Label forecasts as either `operational` or `historical_replay`. Operational forecasts use generation time and require a future scheduled event referenced by the latest eligible Phase 3 match. Historical replay uses the completed target's scheduled tip and is explicitly a simulation.
- Register the full formula and effective configuration in immutable `model_versions` rows. Include a SHA-256 configuration fingerprint in the effective version identity.
- Store append-only `base_forecasts` containing probabilities, pregame ratings, prior-game and replay counts, cold-start features, cutoffs, source timestamps, and training/input fingerprints.
- Make identical semantic reruns idempotent with stable UUIDs and a unique event/model/purpose/input constraint. Append a new row when history, target inputs, or model configuration changes.
- Keep margin of victory, season resets, recency, rest, injuries, advanced statistics, uncertainty calibration, evidence adjustment, opportunity detection, risk, and execution outside V1.

## Consequences

The platform now has an interpretable baseline whose output can be reconstructed from persisted ratings and model configuration and whose training prefix is auditable by fingerprint. Market prices cannot leak into the probability model. Operational targeting remains conservative because only currently eligible matched events can consume the forecast path, while historical replay can evaluate the model across completed events independently of market coverage.

The baseline will be cold-started or biased when local historical coverage is sparse. Home court is always applied because neutral-site normalization is not yet reliable. Provider schedule corrections can change replay order and correctly append new snapshots. Historical replay is not proof of real-time information availability because the current sports-event schema does not record when each result was first observed; future as-of backtesting should add that source-history capability before using time-sensitive evidence.

## Validation

Unit tests cover the probability formula, complements, bounds, zero-sum updates, upset sensitivity, chronology, order stability, strict target/future/simultaneous exclusion, cold starts, bad-final audit counts, and semantic fingerprint reproducibility. Repository and API tests cover database invariants, latest-eligible operational selection, final-history queries, filters, response audit fields, and failure behavior. A PostgreSQL transaction test proves unchanged reruns are idempotent, corrected history appends a forecast, latest selection returns one snapshot, model registration remains singular, and historical replay is distinct.
