# Decision 0021: Prospective NFL shadow payout snapshots

## Scope

Create immutable pregame research observations for one explicitly selected NFL
market match. This closes the gap between a retrospective backtest and an estimate
actually recorded before a future game. It does not promote the model, enable NFL
opportunities, settle a contract, or permit paper/live execution.

## Frozen model

Use `nfl-shadow-frozen-preseason2026-v1`, derived without tuning from the exact
September 10 baseline seed fingerprint
`9c70fcc1ee9089a3851794764e915eeca2fa3b1c7cfb533a0ba76a0cab320b0b`.
The pin includes historical source observation times and the complete baseline
configuration. Reconstruct the final 2025 ratings, apply the existing one-third
offseason regression, then calculate complementary six-decimal expected home and
away payouts. Orient YES/NO using the revalidated contract's selected team.

"Preseason" describes the use of seasons through 2025, **not** when this model was
created. These source records were collected in September 2026. Each snapshot's
actual database capture time must precede kickoff; no earlier forecast is claimed.
Current-season scores and injuries never update this version, so its estimates
will become stale as the season progresses. Cold starts are rejected.

The original source pin is deliberate: refreshed observation times or corrected
seed results cannot silently change a frozen model. A changed seed requires a new
reviewed model release. This is separate from current target/market refreshes,
which are required for safe pregame capture.

## Eligibility and persistence

Run one match per request. Revalidate its current market, target event, latest match,
NFL rule policy, selected team, and current deterministic matching result. Reject
superseded, ambiguous, unsupported, non-scheduled, post-kickoff, postseason, or
non-2026 targets. Require current event and market observations no older than
24 hours; future observations are invalid. The 24-hour bound is an initial shadow
research safety limit, not a measured market-data quality guarantee.

Lock source parents, obtain authoritative database time after lock acquisition,
and recheck the pregame boundary before insertion. Do not accept client-supplied
capture times. Immutable match records may replay after a source refresh, so age
alone is not enough to invalidate an otherwise freshly revalidated match.

Migration `0022_nfl_shadow_forecasts` introduces a separate append-only table with
source foreign keys, payout bounds/complements, pregame timing constraints, and
research-only safety flags. The audit payload freezes the exact seed inputs,
prediction, target, and matching evidence. Semantic replay returns the existing
snapshot; it does not rewrite creation time. GET list responses are compact;
individual GET responses include full replay evidence.

## Interfaces

- `POST /nfl-shadow-forecasts/run?match_id=<uuid>` creates or replays one snapshot.
- `GET /nfl-shadow-forecasts?limit=25&offset=0` lists immutable historical snapshots.
- `GET /nfl-shadow-forecasts/<uuid>` returns exact audit inputs.

Lists are audit history, not a current forecast feed. A later schedule or contract
change can invalidate an old snapshot for analysis without deleting it. These
records cannot be consumed by the operational NBA forecast or trading pipeline.

Match insertion acquires ordered market-parent locks as well, serializing changes
to the latest match with shadow capture. The final clock check also rejects a
market closing during construction or a backwards database-clock transition.

## Remaining boundaries

Coverage verification, prospective outcome labeling/evaluation, model promotion
criteria, current-season state updates, fractional exchange settlement, and NFL
paper execution remain separate steps. Historical scores are not official exchange
settlement evidence. No automation or execution permission is introduced here.

## Live smoke test: September 10, 2026

The refreshed schedule contained 16 games (15 scheduled, one final). NFL market
ingestion saved 62 contracts; the bounded week-one matching run examined 34,
matched 32, and conservatively rejected two unrecognized matchup designators.
No rejected contract was forced through.

One Miami–Las Vegas shadow snapshot was created at `2026-09-10T14:13:59.838774Z`
for kickoff `2026-09-13T20:25:00Z`, ID
`90a16393-0f39-45d5-8469-8f911c759b59`. Its home/YES payout estimate was
`0.405336`, away/NO `0.594664`; this is a research proxy, not a recommendation.
A repeated request returned `created=false`, the same ID, and the original capture
time. Rebuilding from its stored 2,127 seed inputs and target reproduced the entire
typed prediction exactly. List and detailed audit reads succeeded. Paper mode
remained enabled, and neither an operational forecast nor a trade was created.

Final verification: 760 backend tests passed against an isolated migrated
PostgreSQL database. Ruff lint/format checks passed including migration 0022;
strict mypy passed across 240 application/test files. The test database was removed
after verification, without changing production research data.
