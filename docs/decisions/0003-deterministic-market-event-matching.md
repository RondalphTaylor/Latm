# Decision 0003: Deterministic Market-to-Event Matching

**Status:** Accepted
**Date:** 2026-08-01

## Context

Phase 3 must connect prediction-market contracts to normalized NBA games without silently forcing uncertain links. The existing market `is_nba` value is deliberately broad and has known cross-sport false positives where leagues share city abbreviations. Current offseason data also contains many futures, awards, roster, and multi-team contracts rather than ordinary game contracts.

## Decision

- Match only from normalized market text and normalized team/event records; do not parse provider-specific ticker formats or arbitrary raw JSON in the generic matcher.
- Normalize Unicode, punctuation, case, and whitespace, then require boundary-aware aliases.
- Generate aliases from all current team names, nicknames, cities, and official abbreviations, supplemented by a small curated map. Short abbreviations require their original uppercase token. Shared cities and generic nickname words require stronger basketball context.
- Reject explicit non-NBA sport signals before interpreting shared team abbreviations.
- Require exactly two distinct NBA teams for the supported single-game shape. Treat the team pair as unordered.
- Use occurrence time as the primary event anchor. A close-time fallback remains lower confidence and cannot independently produce a confident match under the default policy.
- Score team evidence at 70% and temporal proximity at 30%. The initial policy records a minimum confidence of `0.90`, runner-up margin of `0.10`, and inclusive candidate window of 36 hours.
- Classify a unique qualifying candidate as `matched`, plausible but insufficient or tied candidates as `ambiguous`, and unsupported/no-candidate inputs as `unmatched`.
- Leave `sports_event_id` null for ambiguous and unmatched results. Only a matched result at or above its recorded threshold may set `automatic_trading_eligible=true`.
- Treat confidence as a deterministic heuristic matching score, not a calibrated probability.
- Persist append-oriented attempts with matcher version, effective policy, signals, candidate score breakdowns, source timestamps, and a SHA-256 semantic input fingerprint.
- Make unchanged reruns idempotent with a unique `(market_id, matcher_version, input_fingerprint)` constraint. A changed semantic input appends history instead of overwriting it.
- Keep fuzzy matching, machine learning, LLM matching, manual overrides, forecasting, opportunity detection, and every form of execution out of Phase 3.

## Consequences

Downstream forecasting can rely on a provider-neutral event link while retaining explicit ambiguity and an inspectible audit trail. The conservative policy will leave some valid contracts unmatched until normalized evidence improves; that is preferable to connecting a market to the wrong event. A matching-eligible result remains only one future risk prerequisite and cannot create or approve a trade.

Any alias or scoring-policy change that can affect decisions must increment the matcher version. Thresholds may be configured at runtime, but their effective values are included in the semantic fingerprint and persisted with every attempt.

## Validation

The matcher is covered across all 30 canonical teams, curated aliases, uppercase-token and city-collision rules, exact and boundary time cases, back-to-back games, tied candidates, cross-sport regressions, semantic fingerprints, repository queries, API behavior, and safety invariants. A PostgreSQL transaction test proves idempotent reruns, append-only changed decisions, and latest-result selection without leaving fixture data behind.
