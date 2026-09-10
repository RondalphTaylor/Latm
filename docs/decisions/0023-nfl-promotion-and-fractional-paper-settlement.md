# Decision 0023: NFL promotion gates and fractional paper settlement

## Authority and scope

Policy `nfl-promotion-review-v1`, defined 2026-09-10, separates engineering
verification from evidence that a strategy merits deployment. These are initial,
conservative engineering thresholds, not statistically established guarantees.
This release defines a review policy; it does not implement an automatic promoter.
Unknown or unavailable evidence is a blocked gate, never an implicit pass.
Passing a gate requires a preserved report and explicit operator review. No gate
changes configuration, matches, forecasts, risk authorizations, or trading mode.

## Gate A: engineering paper tests (available now)

Run fixtures in an isolated test database, never seed invented provider results or
positions into the ordinary research or paper ledger. Require all of:

- Domain, adapter, migration, accounting, replay and mode-safety tests pass.
- Standard YES/NO and fractional payouts, both held sides, partial reductions,
  missing/conflicting outcomes and cent rounding are verified.
- Each settlement references an explicit official exchange resolution. A sports
  tie or shadow label cannot settle a contract.
- Repeated requests cannot credit twice; source conflicts cause no financial
  effects; realized P&L, remaining basis and portfolio snapshots reconcile.
- Real-money execution and the NFL operational eligibility guard stay disabled.

This gate does not require waiting for a season or a forecast-quality sample.
It establishes software behavior, not strategy profitability. General NFL paper
entry still needs a separately reviewed operational forecast/edge/risk integration;
do not bypass the current research-only match constraint to manufacture entries.

## Gate B: shadow model to a reviewed NFL paper pilot

Freeze a model version, seed fingerprint, policy version and cohort before scoring.
For the initial model, use all regular-season games scheduled in NFL weeks 1–8 of
2026 with kickoff at or after 2026-09-10T14:13:59.838774Z. Games already started
before the first real capture are outside the cohort, not backfilled predictions.
Later schedule changes and canceled/unavailable games remain in the coverage
inventory with reasons. Do not replace missing or invalid early captures with
later favorable ones, select a winning contract after results, or pool model seeds.
Preserve the schedule inventory used to establish the denominator before outcomes;
until that inventory is auditable, coverage is unverified and this gate is blocked.

Require all of:

1. At least 100 distinct, final, correctly labeled games spanning all eight cohort
   weeks, using the earliest snapshot per event/model/seed. Do not stop early when
   metrics first look favorable; review only after the full cohort is resolved or
   outstanding exceptions have been explicitly reviewed.
2. Pregame snapshot coverage at least 95% of the cohort's scheduled games; every
   missed, changed, canceled or unlabeled event has a recorded reason. No unresolved
   leakage, identity, source-correction or ledger-integrity defect is acceptable.
3. Mean home expected-payout squared error strictly below the paired constant-0.5
   benchmark on the same games. Report the sample and paired difference, not just
   the model mean. This is not a claim of statistical significance or market edge.
4. Absolute mean payout bias no more than 0.05. Fixed ten-bin expected calibration
   error no more than 0.10: sum over bins of `(bin_count / N) * abs(mean_prediction
   - mean_outcome)`. Empty bins contribute zero weight. Bins below ten observations
   must be flagged as sparse, not described as validated calibration.
5. Freeze all exceptions and results in a versioned review artifact. Any retuning
   creates a new model/seed and requires a new prospective cohort, not a re-score
   of this cohort presented as fresh validation.
6. Complete the operational NFL payout-forecast, executable-price, sizing and risk
   integration, plus replay-safe paper entry-to-exit/settlement tests. Keep model
   expected payout distinct from Bernoulli win probability. Rule/template drift,
   unrecognized contracts, stale prices and unavailable source results fail closed.

Historical baseline results are supporting research only and do not count toward
the prospective sample. The existing performance API reports labeled observations;
it does not yet establish cohort completeness, uncertainty or promotion readiness.

## Gate C: paper pilot review, not live authorization

After Gate B and explicit pilot approval, pre-register a fixed eight-week paper
cohort in an isolated paper portfolio, with at least 100 completed positions before
review. Do not extend or shorten the window based on profit. Require reconciled
immutable ledgers, zero unresolved safety defects, positive realized net P&L after
modeled costs, snapshot maximum drawdown at most 10%, and nonnegative net P&L when
entry/exit fee and slippage assumptions are doubled in a separate reproducible
stress replay. Report exposure, turnover, failed/rejected attempts, fill assumptions,
and unresolved positions. These provisional criteria are deliberately conservative
and must not be retroactively weakened to obtain a pass.

Even a passing paper review does not authorize live trading. Provider-specific
fees/depth/fill realism, account separation, legal/platform eligibility, kill
switches and explicit operator approval remain separate prerequisites. This release
adds no live adapter or automatic capital increase.

## Fractional settlement contract

The existing binary-contract resolution model now distinguishes YES, NO and SCALAR
settlement results; SCALAR is not a tradable outcome side. Standard YES/NO continues
to require exact 1/0 payouts. Fractional settlement requires an explicit official
scalar result, strictly interior YES payout, complementary NO payout, at most six
decimal places, and an aware settlement time no later than retrieval. Missing,
non-final, inconsistent, unsupported or out-of-range observations produce no
normalized resolution. No sports score is used as a substitute.

Migration 0024 extends resolution constraints and protects resolution history from
UPDATE/DELETE. A downgrade refuses to discard fractional facts. Conflicting official
assertions remain a manual-review blocker; this release does not reverse a completed
ledger settlement after an exchange correction.

The existing paper accounting policy is retained: for remaining integer quantity
`q` and explicit held-side payout `p`, credit `floor_to_cent(q * p)`, realize that
credit minus the remaining all-in basis, and clear remaining exposure atomically.
Prior reduction proceeds and realized P&L remain untouched. For example, three
contracts at 0.333333 credit 0.99; three at 0.50 credit 1.50. Rounding is per held
paper position, not account-level exchange netting. Exit fees/slippage are zero at
settlement under the existing simulator; the rounding remainder is not represented
as a provider fee. This is a conservative simulation, not exact exchange accounting.

Kalshi documents scalar results and a determined/dispute period before finalization
in [Market Lifecycle](https://docs.kalshi.com/getting_started/market_lifecycle).
Its [Get Market schema](https://docs.kalshi.com/api-reference/market/get-market)
supplies settlement value and timestamp. [Market Settlement](https://docs.kalshi.com/getting_started/market_settlement)
describes cent rounding, netting and possible sub-cent scalar settlement fees.
Documentation checked 2026-09-10; actual provider fees and account-level netting
remain unmodeled. None of these reads requires an order or account API call.

## Release verification

Release 0.11.26 passed 875 backend tests against isolated PostgreSQL, plus Ruff and
mypy. Real database lifecycle tests cover entry, partial reduction, settlement and
replay with payouts 1, 0.5, 0.333333, 0.000001 and 0.999999. Those tests exposed and
fixed the legacy proceeds constraint: it compared the unrounded product against
cent-rounded cash. Migration 0024 now enforces the same cent-floor formula as the
engine, preserving all other decision and P&L constraints.

The local app is healthy in paper mode at migration 0024. No synthetic fixtures
were inserted into production and no operational trade was run. The 15 existing
NFL snapshots still await results; model promotion is not approved. The disposable
test database was removed after validation.
