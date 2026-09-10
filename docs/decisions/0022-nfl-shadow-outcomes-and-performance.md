# Decision 0022: NFL shadow outcomes and prospective performance

## Purpose

Evaluate forecasts that were actually recorded before kickoff, without overwriting
the forecasts or treating sports scores as exchange settlement instructions.
This is a local research workflow; no provider, order, portfolio, or settlement
API is called by labeling or performance reporting.

## Frozen outcome facts

`POST /nfl-shadow-labels/run?snapshot_id=<uuid>` labels one existing immutable
shadow snapshot from a locally persisted, validated final BALLDONTLIE NFL result.
The sports event is locked before capturing database evaluation time. Require
the same source identity, teams, season/week, and kickoff as the original target,
complete nonnegative integer scores, and consistent raw/normalized final metadata.
The snapshot must precede kickoff, and the result observation cannot be in the
future or precede kickoff. Pending or unavailable results produce no label.

The ordinary-game home payout is 1 for a home win, 0.5 for a tie, and 0 for an away
win. YES payout follows the original captured selected team. Store twelve-decimal
`(expected_home_payout - actual_home_payout)^2` and the paired constant-0.5 error.
These are payout errors, not Bernoulli win-probability Brier scores.

Migration `0023_nfl_shadow_evaluations` adds append-only label facts with source
foreign keys, timing/payout/score constraints, immutable triggers, and explicit
research-only flags. Full final-result evidence is retained in the detail audit.
The semantic identity includes exact final scores and snapshot/evaluation policy;
polling timestamps alone do not create new labels. Corrected scores append a
different semantic fact. A correction reverting to an earlier score can replay
that earlier immutable label while retaining all intermediate history.

## Canonical performance

`GET /nfl-shadow-performance` selects the earliest snapshot by capture time and
stable ID for each `(event, model version, seed fingerprint)` from **all** snapshots
before inspecting eligibility or labels. Multiple contracts or later captures
cannot increase that game's weight, and an unscored/invalid earliest snapshot
cannot silently fall back to a more favorable later snapshot.

Current result semantics must match a label exactly. A correction invalidates old
scores from the current report until a matching label exists; old labels remain
readable in audit history. A schedule/team/week conflict makes the canonical
snapshot ineligible rather than changing its original target. Report pending
results, pending labels, ineligible reasons, and labeled counts separately.

Metrics are grouped by model and seed, never pooled across versions. Each labeled
game contributes one home payout error, a constant-0.5 benchmark error, and one
observation to fixed ten-bin calibration. Ties remain explicit. Empty samples have
null metrics in the pure aggregate and no metric groups in the API, not zero error.
These are descriptive prospective research measures,
not proof of market edge, profitability, calibration adequacy, or trading readiness.
Do not compare unpaired model means as evidence of superiority.

## Reads and operational use

- `GET /nfl-shadow-labels?limit=25&offset=0` returns compact label history.
- `GET /nfl-shadow-labels/<uuid>` returns a full frozen label audit.
- `GET /nfl-shadow-performance` returns current canonical coverage and metrics.

Refresh source results through the existing bounded NFL events ingestion before
labeling completed games. Labeling and performance never refresh providers or
create missing forecasts. The performance read has a hard source-row cap and fails
closed rather than presenting a truncated aggregate.

Fractional **exchange** settlement, prospective promotion criteria, model updates,
and NFL paper execution remain separate tasks. No bankroll moves in this slice.

## Initial verification (2026-09-10)

Release 0.11.25 passed 812 backend tests using an isolated migrated PostgreSQL
database, plus Ruff and mypy. The local paper-mode API at migration 0023 reported
15 snapshots for 15 canonical upcoming games: all pending results, zero labels,
zero ineligible snapshots, and no metric groups. A labeling request for an
unfinished game returned HTTP 409 `pending_result`; label history remained empty.
No finished game received a backdated forecast, and no trade was executed.
