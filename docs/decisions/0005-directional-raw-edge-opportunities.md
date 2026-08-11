# Decision 0005: Directional Raw-Edge Opportunities

**Status:** Accepted
**Date:** 2026-08-11

## Context

Phase 5 must compare independent NBA game-win forecasts with prediction-market prices without allowing market information to leak into the base model or implying that an apparent edge authorizes a trade. The normalized market snapshot contains multiple price fields, event matching does not establish what a contract's YES side means, and the local database can contain stale or superseded evidence. A favorable calculation based on an inferred, mixed, or older price would not be reproducible or safely executable.

## Decision

- Implement deterministic `raw_edge` V1 as a provider-neutral local service with no external calls.
- Evaluate YES and NO as separate immutable records using `model_team_win_probability - direct_side_ask_probability`, rounded to six decimal places.
- Use only `yes_ask` for YES and `no_ask` for NO. Do not substitute bids, last prices, midpoints, complements, or fields from another snapshot.
- Resolve direction only for binary event-winner contracts. Require an explicit winner verb and exactly one normalized YES and NO outcome. Match labels exactly against the two matched teams' normalized abbreviation, city, name, or full name; allow one generic label only when the other side maps uniquely. Reject propositions, ambiguous labels, conflicts, and both-generic contracts.
- Rank the newest match, price, and exact-current-model operational forecast before checking eligibility. Never fall back to an older eligible snapshot when the newest one fails.
- Require an active or open market, a latest matched and eligible event link, an upcoming scheduled non-postponed event, a fresh and internally consistent book, a fresh forecast whose semantic event fingerprint still matches, and source timestamps no later than evaluation time. The event fingerprint covers schedule, teams, and status but excludes observation-only refresh time.
- Default market-price freshness to 900 seconds and operational-forecast freshness to 86,400 seconds. Default classification thresholds to 0.03 for `WATCH` and 0.08 for `TRADE_CANDIDATE`; values below the watch threshold are `IGNORE`.
- Record the complete effective policy and formula in a fingerprinted strategy version. Store exact source IDs, source snapshot, outcome mapping, signed edge, thresholds, ages, validity deadline, status, and semantic input fingerprint.
- Make identical semantic runs idempotent with stable UUIDs and a uniqueness constraint. Append records when prices, forecasts, matches, orientation, or policy change.
- Make the default list current-only. Suppress expired records and records superseded by a newer price, match, or same-model forecast even when the newer source produces no replacement. Keep explicit immutable history, with latest rows partitioned by market, direction, strategy version, and model version before status filtering.
- Treat `TRADE_CANDIDATE` strictly as research output. Do not create proposed trades, size positions, approve risk, access an account, or execute an order.

## Consequences

The engine's market probability represents a concrete immediate entry ask rather than a theoretical midpoint. This is deliberately conservative and can omit a usable side when a direct ask is absent or at the 0/1 boundary. Exact outcome mapping rejects many futures and nonstandard contracts; broader contract semantics should be introduced as separately versioned resolvers rather than guesses.

The strategy records raw apparent edge only. It does not account for fees, slippage, liquidity, model calibration, uncertainty, exposure, or correlation. Those belong to later portfolio, risk, and execution phases. A large raw edge can therefore remain economically unattractive and has no trading authority.

## Validation

Unit tests cover exact threshold boundaries, signed edge arithmetic, independent YES/NO asks, outcome orientation and rejection cases, future and stale inputs, book consistency, source-change invalidation, policy fingerprints, stable record IDs, query ranking, API audit fields, and error behavior. A PostgreSQL transaction test proves two-sided persistence, exact-rerun idempotence, append-on-price-change history, and suppression by a newer ineligible match. Migration `0006_opportunities` applies cleanly and Alembic reports no schema drift.
