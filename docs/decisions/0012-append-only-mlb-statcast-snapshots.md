# Decision 0012: Append-only MLB Statcast quantitative snapshots

## Context

An MLB model needs quantitative pitcher and batter evidence, but a current aggregate without exact
source timing and lineup lineage would be unsafe for operational use and historical evaluation.
Baseball Savant pitch data also contains legitimate missing and occasionally incomplete metric
fields. Treating those values as zero, or rejecting every otherwise valid response, would distort the
features.

## Decision

- Read the public official Baseball Savant Statcast Search CSV surface through a dedicated read-only
  adapter with timeout, retry, pacing, byte, and row limits.
- Require one explicit, complete pregame MLB lineup snapshot and bind its exact event, two probable
  pitchers, and two posted nine-player batting orders to the quantitative result.
- Query pitchers and batters separately over an exact 30-calendar-day window ending the day before
  the target event date. Do not include same-day or target-game data.
- Retain a typed, bounded subset of every source pitch plus response hashes. Aggregate explicit
  sample counts, pitcher velocity/spin, contact metrics, hard-hit and barrel rates, expected wOBA on
  contact, and observed-wOBA components using Decimal arithmetic.
- Preserve incomplete official wOBA values in source rows, count them, and exclude them from observed
  wOBA unless both numerator and denominator are present. Missing data is never converted to zero.
- Append to `mlb_statcast_feature_snapshots` with stable semantic replay, deterministic source,
  policy, and input fingerprints, and a composite lineup/event foreign key.
- Label retrieval strictly before first pitch `operational_pregame`; retain later retrieval as
  `retrospective` and ineligible for an operational model.
- Expose bounded profile and manifest reads while keeping the potentially large pitch rows internal.
- Do not generate a win probability or enable any MLB opportunity, sizing, risk, execution, or
  settlement path.

## Consequences

The platform now has reproducible quantitative inputs tied to what lineup was known and when, while
retaining source anomalies for audit without contaminating aggregates. Storage is intentionally
larger because exact pitch provenance is preserved. A separately versioned MLB model, feature
selection policy, leakage review, backtest, and calibration remain mandatory before any probability
or trading eligibility can be considered.
