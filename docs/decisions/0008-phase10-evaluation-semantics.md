# Decision: Canonical Forecast Facts and Ledger-Derived Performance

## Context

Phase 10 must compare forecast versions and paper strategies without double-counting complementary probabilities, stale result corrections, partial exits, or duplicated accounting aggregates. Forecasts are append-only, sports events retain only their latest normalized result, and the portfolio ledger already contains immutable equity snapshots plus position-event history.

## Decision

Forecast evaluation stores one immutable scalar home-win score for the newest forecast per event, model version, and purpose. Operational and historical-replay samples remain separate. Binary Brier score uses `(p-y)^2`, exact `0.5` predictions abstain from accuracy, and calibration uses fixed-width bins with explicit empty bins. Result semantics—including event date—participate in the fingerprint, so corrections append history and reversions recover the earlier semantic fact.

Model comparison is paired only over the shared event and outcome-fingerprint intersection. Unpaired averages are descriptive coverage, not evidence that one model is better.

Trading aggregates are calculated on demand from the portfolio-locked authoritative snapshot, position, trade, and event lineage. Total P&L uses marked equity minus starting bankroll. Completed positions are the counting unit for win rate and terminal return. Maximum drawdown is sampled from snapshot equity in sequence order. Aggregate results are not persisted into a second financial source of truth.

## Alternatives considered

- Scoring both home and away probabilities was rejected because the outcomes are complementary and would double-count each game.
- Evaluating every regenerated forecast was rejected because repeated snapshots would overweight events.
- Comparing unpaired model averages was rejected because coverage differences confound the comparison.
- Using market resolution as NBA forecast truth was rejected because it represents contract settlement and covers only matched markets.
- Persisting trading summaries was rejected because they would duplicate and potentially drift from the immutable ledger.
- Calculating drawdown from current bankroll was rejected because it omits unrealized marked equity.

## Consequences

Evaluation is reproducible, correction-aware, and cannot mutate trading state. Historical replay remains explicitly retrospective because first-observed result time is unavailable. Drawdown may miss intraperiod movement between snapshots. Open-position profitability depends on stored marks and excludes hypothetical future exit costs. Confidence segmentation remains unavailable until an upstream calibrated confidence signal exists.
