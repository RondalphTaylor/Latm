# Decision 0006: Paper Portfolio and Raw-Edge Position Sizing

**Status:** Accepted
**Date:** 2026-08-11

## Context

Phase 6 must turn qualifying Phase 5 research outputs into reproducible capital-allocation advice without implying risk approval or introducing execution. A sizing calculation needs one authoritative bankroll denominator, exact source identity, conservative rounding, and protection against consuming an expired or superseded opportunity. Prediction-market providers also expose different contract and price-unit conventions, so sizing cannot safely infer an executable quantity yet.

## Decision

- Create active USD paper portfolios only. The default starting bankroll is `$1,000.00`, configurable for future portfolios without rewriting history.
- Make portfolio creation idempotent by a client key and store one immutable sequence-zero balance snapshot.
- Define `current_bankroll = starting_bankroll + realized_pnl`, `cash_balance = current_bankroll - committed_capital`, and `available_bankroll = cash_balance - reserved_capital`.
- Initialize reserved capital, committed capital, and realized P&L to zero. Phase 6 never changes or reserves a balance.
- Implement provider-neutral `raw_edge_bands` V1 using available bankroll: 2% at raw edge 0.08 to below 0.12, 5% at 0.12 to below 0.18, and 8% at 0.18 or above. Do not propose below 0.08.
- Floor proposed capital to whole cents, then calculate stored actual exposure from the floored capital. Keep the configured maximum strictly below 10%.
- Accept only current, unexpired `TRADE_CANDIDATE` opportunities. Revalidate source currentness immediately before insert and also verify that the forecast event fingerprint and outcome-team orientation still match current normalized data.
- Store immutable `position_size_proposals` in `awaiting_risk` state. Record the exact portfolio snapshot, opportunity and source fingerprints, probabilities, raw edge, policy values, strategy version, reason, and audit snapshot.
- Make exact semantic reruns idempotent. A changed effective policy or source input appends a distinct historical proposal.
- Record confidence as `not_available`; do not manufacture a confidence estimate from raw edge.
- Store capital allocation only. Do not infer provider-specific contract quantity, create a proposed trade, approve risk, access an account, reserve funds, or execute.

## Consequences

The system can now compare advisory allocations across strategy versions and reproduce every amount from an exact paper balance and opportunity snapshot. Because proposals do not reserve funds, multiple proposals may each reference the same available bankroll. This is intentional: portfolio-level aggregation, duplicate-position controls, liquidity, correlation, approval, and reservation belong to the Phase 7 risk boundary and Phase 8 paper execution.

Flooring can reduce actual exposure below the target, and sub-cent allocations are skipped. The service rechecks currentness before persistence, but future risk evaluation must still revalidate every mutable market, forecast, opportunity, and portfolio input before approval.

## Validation

Unit tests cover policy ordering and caps, exact edge boundaries, cent flooring, actual exposure, sub-cent rejection, stable strategy identity, paper-only invariants, idempotent portfolio definitions, service source revalidation, no-balance-mutation behavior, database constraints, and API errors. A PostgreSQL transaction test proves portfolio idempotence, exact proposal-rerun idempotence, append-on-policy-change history, stale-opportunity rejection after a newer price, and an unchanged paper balance. Migration `0007_portfolio_sizing` applies cleanly and Alembic reports no schema drift.
