# Decision 0007: Deterministic Paper-Only Risk Authorization

**Status:** Accepted
**Date:** 2026-08-15

## Context

Phase 7 must decide whether a Phase 6 capital-allocation proposal is still permissible without creating an order or treating research evidence as durable execution authority. Proposals do not reserve capital, and their price, forecast, match, opportunity, event, market, sizing policy, and portfolio snapshot can all become stale. The MVP also has no calibrated confidence, adjusted edge, executable liquidity model, or existing positions.

## Decision

- Implement a pure, deterministic `mvp_risk` V1 engine whose effective policy version fingerprints every threshold and comparison boundary.
- Evaluate all ordered hard checks and record each result. Any hard failure returns `REJECT` with no authorization expiry.
- Return `AUTO_APPROVE` only below 10% exposure when every hard check passes. Exactly 10% through exactly 40% returns `REQUIRE_HUMAN_APPROVAL` because confidence is unavailable. Above 40% always returns `REQUIRE_HUMAN_APPROVAL`.
- Revalidate paper-only runtime, proposal, and portfolio state; active sizing strategy; latest portfolio snapshot; canonical accounting; individual and aggregate bankroll; exact current opportunity and source consistency; event and outcome semantics; open market and pregame state; match currentness and confidence; price and forecast currentness/freshness; reproducible minimum raw edge; and duplicate economic intent.
- Lock the portfolio row while calculating aggregate authorization and duplicate-intent state and persisting a decision. Count other proposals' latest unexpired automatic authorizations against the current available bankroll.
- Define duplicate intent provider-neutrally as portfolio, market, direction, and outcome team. An unexpired automatic authorization or human escalation for another proposal blocks the same intent.
- Store append-only `risk_decisions` with exact proposal, observed portfolio snapshot, opportunity, match, price, forecast, policy, checks, limitations, timestamps, and fingerprints. Exact semantic reruns are idempotent.
- Use fixed five-minute UTC authorization windows. Expiry is the earliest window boundary or relevant opportunity, source-freshness, market-close, or event-start deadline.
- Preserve the active Phase 6 sizing cap below 10%. Relax only the reusable proposal representation and database constraint to at most 100% so future strategy proposals can reach the risk escalation rules without weakening current sizing defaults.
- Record adjusted edge and calibrated confidence as `not_available`, liquidity as `not_evaluated_phase7`, and executed-position exposure as unavailable before Phase 8.
- Do not implement human approval actions, provider-specific quantity, reservations, orders, trades, positions, execution, or any provider call.

## Consequences

The platform can reproduce why a proposal was rejected, automatically authorized, or escalated and can compare policy versions without overwriting history. An unexpired decision is not automatically current authority: mutable evidence may change after evaluation, so Phase 8 must revalidate all sources, portfolio state, duplicate intent, and bankroll atomically before simulated execution.

Because Phase 7 has no calibrated confidence, every otherwise-valid proposal at or above 10% requires a person. Because it has no execution model, liquidity, fills, fees, slippage, positions, correlation, drawdown, and settlement remain future controls rather than silently assumed checks.

## Validation

Tests cover exact 10% and 40% boundaries, ordered hard failures, stale and superseded sources, accounting and aggregate-bankroll limits, duplicate intent, fixed authorization windows, stable policy and record identity, service idempotence, API history, database constraints, and zero balance mutation. PostgreSQL transaction coverage proves append-only authorization history, retry idempotence, duplicate rejection, invalidation by a newer price, and unchanged portfolio accounting. Migration `0008_risk_engine` applies cleanly and Alembic reports no schema drift.
