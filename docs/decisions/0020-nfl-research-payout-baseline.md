# Decision 0020: NFL historical research payout baseline

## Scope

Implement a local, provider-independent research calculation, not an operational
forecast or a promotion to paper trading. Historical collection uses the existing
read-only `balldontlie_nfl` adapter and normalized event storage. No additional
provider, credentials, dependencies, scheduler, or database migration is introduced.

The [provider's Games documentation](https://nfl.balldontlie.io/#games) specifies
that the default query includes regular season and postseason, excluding preseason.
Local selection additionally excludes postseason and validates source metadata.
It rejects explicit conflicting preseason/season-type flags, dates outside
September–January, and week numbers above 17 for 2018–2020 or 18 thereafter.

## Model and evaluation policy

The experimental baseline starts every team at 1500, uses Elo K=20 and logistic
scale 400, and regresses ratings one third toward 1500 between seasons. Home
advantage is deliberately zero: the normalized data does not reliably identify
neutral venues, and no NFL home-field parameter has been estimated. These are
fixed starting assumptions, not fitted or validated parameters.

The target is expected home payout on the ordinary game-result convention:
home win=1, tie=0.5, away win=0. This is **not** a home-win probability or a
three-outcome distribution. It cannot resolve exceptional exchange settlements.
Mean squared payout error and payout calibration are appropriate descriptive
metrics; Bernoulli log loss and a claimed win-probability Brier score are not.
Compare paired games against 0.5 and an expanding prior home-score mean.

Use regular-season 2018–2022 as development, 2023–2024 as validation, and 2025
as test. There is no parameter search. Ratings update after each complete observed
season/week group, with all predictions in that group made before its results are
applied. Earlier test weeks may update the state for later test weeks: this is a
fixed-policy walk-forward evaluation, not a frozen-ratings test. Never tune against
test performance. The 2026 season is excluded from this retrospective workflow.

Reject duplicate identities, repeated teams within a week, malformed source
metadata, and inconsistent week chronology. Report missing or excluded source
records and per-season coverage without treating counts alone as completeness.
Partial samples may produce exploratory diagnostics but never promotion approval.

## Audit boundary and limitations

The read-only API returns the exact normalized inputs, source observation times,
model configuration/version, deterministic fingerprint, per-game predictions,
coverage, and split metrics. It does not create database forecast/model records.
Preserve the returned JSON to retain an evaluation across later source corrections;
the database event table is a mutable latest-source projection, not an immutable
research-run archive. Durable artifact persistence is a subsequent slice.

Week batching prevents within-week score leakage, but cannot prove historical
result availability. The provider snapshot does not preserve the original time at
which each final result became known, and source corrections are retrospective.
Missing games, delayed finishes, and schedule anomalies require source review.
This is a retrospective simulation, not evidence of executable performance.

The manual collector checks the localhost health/paper gate, ingests bounded
31-day windows, stops on errors, and returns a resume date. It does not maintain a
durable checkpoint; interrupted windows can be replayed through existing upserts.
No API keys or raw provider error bodies are emitted.

## Live collection blocker

During implementation the local API was healthy in paper mode, but historical
ingestion for September 2025 returned HTTP 502 with `sports-data provider
authentication failed`. No historical performance result is claimed. Restore
provider access before collecting and evaluating the intended seasons.

The implemented collector's live September 2018 smoke test likewise stopped at
HTTP 502, completing zero windows and retaining manual resume date `2018-09-01`.
The deployed read-only baseline returned `no_eligible_historical_games`, zero
selected records, no evaluation report, and trading eligibility false. No source
data was invented to unblock these checks.

## Implementation validation

The complete backend suite passed 721 tests against a freshly migrated isolated
PostgreSQL database, including real NFL ingestion-to-selection-to-evaluation,
NBA identity isolation, ties, weekly chronology, replay, and collector failure
handling. Ruff lint/format checks and strict mypy passed across 231 source files.
The disposable test database was removed after validation. Synthetic test fixtures
were not inserted into the production research database.
