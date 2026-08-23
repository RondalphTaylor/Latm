# Decision 0017: Deterministic MLB logistic fitting

**Status:** Accepted  
**Date:** 2026-08-23

## Decision

Implement the MLB candidate as dependency-free L2-regularized binary logistic regression over the
exact eight-feature order. Learn population means and scales only from fitting rows. Fit strengths
`0.01`, `0.1`, `1`, and `10` with deterministic Newton updates, select by validation mean Brier
score, then refit the selected strength on train plus validation and evaluate the untouched test
split. Never admit prospective-holdout examples into fitting.

Fingerprint the fitting policy, ordered canonical examples, and complete standardized artifact.
Expose the design and a readiness-gated preview, but do not persist a model or publish a probability
until the approved 500/150/150 exploratory sample gates pass.

## Consequences

The numerical training behavior is testable and reproducible without adding a large machine-learning
dependency. Validation selection and test evaluation remain chronologically separated. A successful
synthetic fit is not evidence that the real model works, and a fitted preview is not operational or
trading authority. Immutable persistence, prospective prediction capture, calibration, and any MLB
opportunity path remain separate later decisions.
