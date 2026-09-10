# Decision 0025: NFL direct-ask paper opportunity comparisons

## Scope

Release 0.11.28 compares an immutable NFL expected-payout forecast with a locally
persisted market quote. It writes a separate `nfl_paper_opportunities` audit record,
not an NBA `opportunities` row, position, sizing proposal or risk authorization.
Promotion remains blocked and every comparison has `operational_eligible=false`
and `trading_enabled=false`. No provider or execution call occurs inside comparison.

## Calculation and interpretation

For each side independently:

`raw_edge = expected_side_payout - direct_side_ask`, rounded to six decimals.

YES uses only `yes_ask`; NO uses only `no_ask` from the same latest quote snapshot.
Never substitute a bid, last price, midpoint, another snapshot or an inferred
complement. A missing side ask does not prevent comparison of the other valid side.
An entry ask must be strictly between zero and one. A displayed ask indicates a
price, not available quantity, a completed fill or account-level execution access.

The initial versioned policy uses the existing research bands: edge below 0.03 is
`ignore`, from 0.03 to below 0.08 is `watch`, and at least 0.08 is `paper_candidate`.
The last status is a research classification, not permission to trade. Policy inputs
are fingerprinted and retained in the audit. These thresholds are engineering
defaults, not empirical evidence that any contract is mispriced.

Edges are pre-cost: `costs_included=false`, `depth_verified=false`. Fees, slippage,
fill size, position sizing and risk remain later work. Expected payout is neither
a Bernoulli win probability nor an official exchange settlement instruction.

## Source gates

Require an unexpired, correctly fingerprinted, pinned-model forecast and select
the newest forecast in its market/model/seed lineage before validating eligibility.
An explicit older forecast cannot bypass a newer snapshot by retaining more
favorable numbers. Revalidate the current market, latest match, contract policy,
target identity, teams, kickoff, close and source freshness under parent locks.
The original forecast is not regenerated or extended by an opportunity request.
If source semantics changed, a new validated forecast is required.

Select the latest quote by retrieval time then ID before checking it. Future,
stale, missing or malformed data cannot fall back to an older favorable quote.
The quote age limit is 900 seconds. A quote exactly at its expiry is unusable.
Present same-side bids above asks, combined YES/NO bids above one, or combined
YES/NO asks below one fail the conservative book-consistency check. This check is
not an arbitrage strategy. Missing quotes and unusable sides have status
`ineligible`, explicit reasons and null raw edges; they are never filled in.

Comparable results expire no later than the forecast or quote freshness deadline.
When neither side is comparable, the result has no actionable validity window.
The final clock check still enforces forecast expiry even when the quote is invalid.
Schedule/contract/forecast failures reject the request without a comparison; quote
unavailability is retained as a two-sided audit result where source gates permit.

## Atomicity and history

`POST /nfl-paper-opportunities/run?forecast_id=<uuid>&idempotency_key=<key>`
uses the same bounded request-key syntax as forecast capture. A key identifies one
forecast request, and concurrent uses serialize before source locks. Reusing the
key for another forecast is a conflict. A retry returns the original result,
including its original quote and expiry, even if the market has since changed.
An intentional new comparison uses a new key and repeats all source checks.

The migration adds immutable rows, foreign-key lineage, edge/payout and safety
constraints. Any source revalidation work and comparison insertion share one
transaction; failure rolls back partial writes. Populated downgrade is refused.
Audit evidence includes the exact quote, forecast lineage, policy and two-sided
comparison so the result can be reproduced without calling a provider.

- `GET /nfl-paper-opportunities?limit=25&offset=0` lists bounded compact history.
- `GET /nfl-paper-opportunities/<uuid>` includes frozen audit evidence.

These are history reads, not a current-only executable feed; warnings remain visible
for expired or superseded results. Paper mode is required for run requests. No
scheduler, promotion bypass, real-money path or automatic trade is introduced.

## Next boundary

Add cost-aware paper sizing/risk integration and isolated execution tests. Before
any reviewed NFL pilot, preserve promotion cohort evidence and explicit approval;
neither a large raw edge nor a passing comparison test substitutes for those gates.
