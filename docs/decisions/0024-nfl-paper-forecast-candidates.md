# Decision 0024: NFL operational forecast interface, paper candidates only

## Boundary

Release 0.11.27 implements the forecast portion of the future NFL operational
pipeline without promoting the model or enabling entries. The HTTP namespace is
`/nfl-operational-forecasts`, but every record is explicitly `paper_candidate`,
`promotion_state=blocked`, `operational_eligible=false`, `trading_enabled=false`.
The API is not an authorized signal feed. The existing promotion review and NFL
research-only match constraint are unchanged.

Keep NFL expected payout separate from NBA Bernoulli win probabilities. Do not
insert these observations into `base_forecasts`, relabel a tie-adjusted payout as
a win probability, or let existing NBA opportunity/size/risk code consume it.
No order, account, position or settlement call is introduced.

## Quantitative inputs

Reuse the exact pinned historical model `nfl-shadow-frozen-preseason2026-v1` and
seed fingerprint from decision 0021. Build a fresh prediction from the current
source-observed target and that fixed seed. Preserve the full prediction, seed and
source lineage in the candidate audit. Fresh generation means fresh source and
contract validation; it does not update the ratings with 2026 scores or injuries.
This release does not invent a tie probability or new model parameters.

The existing shadow capture supplies lineage and performs the established locked
market, latest match, NFL rule-template, candidate-event, team, raw-provider,
lifecycle and source-freshness checks. Its transaction-internal path is reused so
candidate generation retains the same parent locks. A replayed shadow's old target
observation cannot masquerade as a new forecast: rebuild from the current locked
target using a new database timestamp. A final clock check fails on backwards time,
kickoff/close crossing or source expiry during construction. Require a known market
close time, not a guessed close inferred from kickoff.

## Validity and retries

The candidate deadline is the earliest of generation plus 15 minutes, kickoff,
market close, event observation plus 24 hours and market observation plus 24 hours.
All timestamps must be aware, observations cannot be future-dated, and the deadline
must be strictly after generation and the final validation clock. These are initial
engineering freshness limits, not a measured liquidity or model-quality guarantee.
Downstream code will still need to revalidate sources at use time; a deadline alone
does not certify that a schedule, rule or market has not changed.

`POST /nfl-operational-forecasts/run?match_id=<uuid>&idempotency_key=<key>` requires
an explicit 1–100 character key using letters, digits, `.`, `_`, `:`, `-`, beginning
with a letter or digit. Concurrent attempts using the same key serialize. Reusing
it for another match is a conflict. A retry returns the original immutable record,
even after expiry: it cannot renew timestamps or silently regenerate a new result.
An intentional new capture uses a new key and repeats all current-source checks.
Every candidate remains unpromoted regardless of its key or deadline.

Migration 0025 adds `nfl_payout_forecasts`, separate from both shadow observations
and operational NBA forecasts. Parent foreign keys, payout/timing/safety checks,
lineage validation, and UPDATE/DELETE rejection protect the record. The full
transaction, including any newly created source shadow, rolls back on failure.
Populated downgrade is refused rather than erasing forecast audit history.

## Reads and next integration

- `GET /nfl-operational-forecasts?limit=25&offset=0` returns bounded compact history.
- `GET /nfl-operational-forecasts/<uuid>` includes the exact frozen audit.

Reads do not refresh data, renew expiry or assert present-day eligibility. They
deliberately retain expired candidates and include explicit warnings.

The next implementation is a payout-aware NFL paper opportunity contract using
executable directional prices, followed by sizing/risk integration and isolated
entry-to-settlement tests. Those components must not assume model promotion merely
because this forecast interface exists. A reviewed pilot still requires decision
0023's cohort and approval evidence. No scheduler is added in this slice.

## Verification: 2026-09-10

All 924 backend tests passed against isolated PostgreSQL, plus Ruff and mypy.
Migration 0025 was applied to the healthy local paper-mode app. A Miami–Las Vegas
candidate (`ec83ba32-e543-4103-ada5-0881026fceb7`) was captured at
2026-09-10T15:05:32.416918Z with expiry 2026-09-10T15:20:32.416918Z. Its home/YES
expected payout was 0.405336 and away/NO 0.594664. These are model outputs, not a
trade recommendation or a claim of current validity.

The same request key replayed the same ID and expiry. Rebuilding from the stored
2,127 historical games reproduced both the complete prediction and candidate
fingerprint exactly. The original shadow remained unchanged; no trading eligibility
was granted or trade created. Test fixtures stayed isolated, and the disposable
test database was removed after verification.
