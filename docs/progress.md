# Project Progress

## Phase 0: Project Foundation

**Status:** Complete
**Completed:** 2026-07-22

Phase 0 established the repository foundation without implementing any later-phase data ingestion, forecasting, research, risk, execution, or trading behavior.

Completed foundation:

- typed FastAPI backend with liveness and PostgreSQL-readiness endpoints
- paper-only typed application settings with a safe default
- async SQLAlchemy and PostgreSQL connectivity
- Alembic with an initial `system_metadata` migration
- pytest, Ruff, and strict mypy validation
- minimal Next.js and TypeScript paper-mode status page
- ESLint, strict TypeScript checking, and production build validation
- Docker Compose development stack for backend, frontend, and PostgreSQL
- example environment configuration and Git secret exclusions
- GitHub Actions validation for pull requests and pushes to `main`
- documented local development and validation commands

Local validation completed successfully for tests, linting, formatting, type checking, frontend production build, production dependency audit, Docker image builds, container health checks, PostgreSQL connectivity, migration state, API health, and the rendered paper-mode status page.

The GitHub-hosted workflow is configured but will run for the first time only after the repository is pushed and a qualifying push or pull request event occurs.

## Phase 1: Prediction-Market Ingestion

**Status:** Complete
**Completed:** 2026-08-01

Phase 1 introduced the first read-only prediction-market integration without adding execution or trading behavior.

Completed ingestion capabilities:

- provider-independent typed models for markets, binary outcomes, and price snapshots
- a read-only prediction-market provider protocol
- a Kalshi public REST adapter using event discovery and nested market retrieval
- cursor pagination, bounded retries with exponential backoff, timeouts, response validation, and safe provider errors
- current dollar-denominated Kalshi price fields, with provider payloads retained for auditability
- structured-metadata-first NBA filtering with team-name and abbreviation fallbacks
- PostgreSQL provider, market, outcome, and append-oriented price-snapshot models
- stable provider-derived internal UUIDs and idempotent identity upserts
- typed `GET /markets`, `GET /markets/{id}`, and read-only-data `POST /markets/ingest` endpoints
- unit tests for normalization, optional/malformed data, price bounds, pagination, retries, failures, NBA filtering, persistence statements, and API behavior

The adapter requires no Kalshi credentials and has no order, account, portfolio, or authenticated trading methods. `TRADING_MODE=paper` remains the only accepted execution setting.

Live validation on 2026-08-01 exercised the complete public Kalshi-to-PostgreSQL path. One open-event ingestion fetched 74,946 normalized markets, classified 2,559 as NBA-related, and persisted 2,559 markets, 5,118 binary outcomes, and 2,559 price snapshots. The scale test exposed and led to fixes for nested markets without titles and PostgreSQL driver parameter limits; both cases now have regression coverage.

## Phase 2: NBA Data Ingestion

**Status:** Complete
**Completed:** 2026-08-01

Phase 2 introduced a provider-independent NBA data layer backed by the authenticated BALLDONTLIE REST API.

Completed ingestion capabilities:

- typed provider-neutral `Team` and `SportsEvent` models with explicit NBA league and event-status values
- a read-only sports-data provider protocol and BALLDONTLIE adapter for teams, scheduled games, live games, completed results, postponements, and cancellations
- cursor pagination, configured free-tier pacing, bounded retries, timeouts, response validation, and credential-safe provider errors
- normalized provider identities, schedule times, score state, season metadata, status details, and raw source payloads for auditability
- PostgreSQL team and sports-event models with stable provider-derived UUIDs, foreign-key integrity, score constraints, and duplicate-preventing provider identity constraints
- idempotent team and event upserts that persist referenced teams before games
- typed team and event ingestion and query endpoints with date, status, team, and provider filters
- a 31-day inclusive ingestion bound to keep each request and provider call volume controlled
- automated coverage for normalization, all event statuses, pagination, rate limits, authentication and network failures, persistence statements, ingestion summaries, configuration, and API behavior

Migration `0003_nba_teams_events` was applied to PostgreSQL and Alembic reported no schema drift. The complete backend suite passed with 54 tests, along with Ruff and strict mypy validation. Authenticated live-provider ingestion was not run because no `BALLDONTLIE_API_KEY` was configured; mocked provider tests exercise the complete adapter behavior without exposing or requiring a credential.

`TRADING_MODE=paper` remains the only accepted execution setting. Phase 2 adds sports-data reads and local persistence only; it introduces no forecasting, matching, order, account, or trading behavior.

## Phase 3: Market-to-Event Matching

**Status:** Complete
**Completed:** 2026-08-01

Phase 3 introduced deterministic, provider-neutral matching between locally persisted prediction markets and NBA events.

Completed matching capabilities:

- matcher version `deterministic-team-time-v1` for supported single-game NBA contracts
- boundary-aware Unicode text normalization and generated aliases for all 30 NBA teams
- canonical full names, unique nicknames, official uppercase abbreviations, and a small version-controlled curated alias registry
- explicit rejection of cross-sport signals and conservative handling of shared cities, generic nicknames, missing teams, and multi-team markets
- unordered team-pair candidate generation with occurrence-time preference and lower-confidence close-time fallback
- inspectible team and temporal score components, with a configurable `0.90` threshold, `0.10` runner-up margin, and 36-hour window
- explicit `matched`, `ambiguous`, and `unmatched` states; ambiguous and unmatched decisions never select an event or become eligible
- append-oriented `market_event_matches` audit history with stable UUIDs and SHA-256 semantic input fingerprints
- idempotent repeated evaluations while changed text, schedules, candidate sets, policy, or matcher versions append a new attempt
- database checks for confidence and policy bounds, fingerprints, status/event consistency, and matching eligibility
- bounded local-only matching runs plus latest/history list, detail, and latest-per-market APIs
- regression tests for the known cross-sport false-positive risk in the broad Phase 1 NBA discovery flag

Migration `0004_market_event_matches` was applied to PostgreSQL and Alembic reported no schema drift. The complete backend suite passed with 120 tests, including a PostgreSQL-backed transaction test proving unchanged reruns remain idempotent, changed semantic inputs preserve history, and latest-result queries return the new decision. Ruff and strict mypy validation also passed.

The current local database still has no BALLDONTLIE teams or events because no API key is configured, so there was no live offseason market/game pair to match. The PostgreSQL fixture exercised the complete normalized market-to-event path and rolled back all fixture data afterward.

The recorded `automatic_trading_eligible` value is only the event-matching prerequisite. It cannot place a trade, bypass the future risk engine, or override `TRADING_MODE=paper`.

## Phase 4: Base Forecasting Model

**Status:** Complete
**Completed:** 2026-08-01

Phase 4 introduced the first independent, reproducible NBA game-win probability model.

Completed forecasting capabilities:

- deterministic `nba_elo` V1 with equal 1500 initialization, K-factor 20, logistic scale 400, and a 100-point home-court adjustment
- timezone-aware chronological replay of locally persisted final NBA games, with strict exclusion of the target and later or simultaneous results
- exact complementary probabilities stored to six decimal places and zero-sum team-rating updates stored to four decimal places
- explicit `operational` and `historical_replay` purposes so simulated historical forecasts cannot be confused with forecasts generated before a future event
- latest-eligible Phase 3 match gating for operational targets; historical model evaluation remains event-centric and does not require a market
- immutable `model_versions` registry rows containing the complete effective configuration, formula, configuration fingerprint, and description
- append-only `base_forecasts` with pregame ratings, prior-game counts, cold-start indicators, replay counts, target/source timestamps, training fingerprints, and semantic input fingerprints
- stable forecast/model UUIDs and idempotent identical reruns; corrected prior results append a new auditable snapshot
- bounded local-only generation plus list, detail, event-history, and model-registry APIs
- explicit exclusion and audit counts for incomplete or tied final records, with no market prices, provider calls, AI, opportunities, risk, or execution in the model path

Migration `0005_base_forecasts` was applied to PostgreSQL and Alembic reported no schema drift. The complete backend suite passed with 141 tests, including PostgreSQL-backed tests proving idempotence, append-on-history-change, latest selection, and distinct historical replay. Ruff and strict mypy validation also passed.

The local database still has no BALLDONTLIE events because no API key is configured, so an operational run safely returns zero targets. Fixture-backed PostgreSQL validation exercised the complete data-to-forecast path. Historical replay is deliberately labeled as simulated chronological evaluation: the current event schema stores the latest result but not when that result first became available in historical real time.

The base forecast is independent research output. A high probability is not a trade recommendation or approval, and `TRADING_MODE=paper` remains the only execution setting.

## Phase 5: Opportunity Detection

**Status:** Complete
**Completed:** 2026-08-11

Phase 5 introduced the first deterministic market-versus-model comparison pipeline without adding position sizing, risk approval, or execution.

Completed opportunity capabilities:

- provider-neutral raw-edge V1 using `model_probability - direct_side_ask_probability`
- independent YES and NO evaluation from direct executable asks, with no bid, last-price, midpoint, complement, or cross-snapshot substitution
- conservative binary event-winner outcome orientation against the two matched event teams, with explicit rejection of propositions and ambiguous semantics
- newest-snapshot-first selection for match decisions, prices, and exact-current-version operational Elo forecasts, preventing fallback to older favorable evidence
- active-market, eligible-match, upcoming-event, timestamp, freshness, semantic event-change, probability-bound, and internally consistent book gates; observation-only refreshes do not invalidate forecasts
- configurable 3-point `WATCH` and 8-point `TRADE_CANDIDATE` thresholds, 15-minute price freshness, and 24-hour forecast freshness
- fingerprinted effective policy versions and six-decimal signed edge calculations
- append-only `opportunities` records with exact source IDs and snapshots, mapping and input fingerprints, threshold configuration, ages, validity deadlines, and research classifications
- stable semantic UUIDs and idempotent exact reruns; changed prices, forecasts, matches, orientations, or policies preserve history
- bounded local-only run, current/latest/history list, detail, and per-market history APIs with audited status and skip counts; current results suppress expired or superseded records even without a replacement

Migration `0006_opportunities` was applied to PostgreSQL and Alembic reported no schema drift. The complete backend suite passed with 176 tests, including PostgreSQL transaction tests proving separate YES/NO persistence, exact-rerun idempotence, append-on-price-change history, suppression by a newer ineligible match, and current-list invalidation. Ruff, strict mypy, and dependency validation also passed.

The current local database has no event matches or operational forecasts, and its existing market prices are stale, so a live local opportunity run safely produces no records. Fixture-backed PostgreSQL validation exercised the complete market-to-opportunity path.

`TRADE_CANDIDATE` is a research label only. It cannot size a position, create or approve a trade, access an account, bypass a risk engine, or execute an order. `TRADING_MODE=paper` remains the only execution setting.

## Phase 6: Portfolio and Position Sizing

**Status:** Complete
**Completed:** 2026-08-11

Phase 6 introduced isolated paper-bankroll accounting and deterministic capital-allocation advice without adding approval or execution.

Completed portfolio and sizing capabilities:

- active USD paper portfolios with configurable starting bankroll, stable identities, idempotent creation keys, and no accepted live-mode input
- immutable sequence-zero accounting snapshots with explicit starting, current, cash, reserved, committed, available, and realized-P&L values
- canonical balance equations enforced in typed domain models and PostgreSQL constraints
- provider-neutral `raw_edge_bands` V1 allocating 2%, 5%, or 8% of available bankroll at exact 8%, 12%, and 18% raw-edge boundaries
- cent-flooring of proposed capital and actual-exposure calculation from the floored amount
- strict strategy-policy validation requiring the sizing cap to remain below the future 10% risk-escalation boundary
- consumption of only current, unexpired Phase 5 `TRADE_CANDIDATE` records, with explicit-time currentness, event-fingerprint, and outcome-orientation revalidation
- append-only `position_size_proposals` with exact source and portfolio snapshot identity, policy values, fingerprints, reasons, and audit payloads
- stable semantic proposal IDs and exact-rerun idempotence; changed effective policies append comparable history
- typed create/list/detail/snapshot/run/proposal APIs and a Phase 6 status-page update
- automated unit, repository, API, and PostgreSQL transaction coverage for boundaries, rounding, invariants, history, currentness, and no balance mutation

Migration `0007_portfolio_sizing` was applied to PostgreSQL and Alembic reported no schema drift. The complete backend suite passed with 202 tests, and all four PostgreSQL transaction suites passed against the migrated database. Phase 6 fixture validation proved portfolio and proposal idempotence, append-on-policy-change history, stale-opportunity rejection after a newer price, and unchanged balances. Ruff, strict mypy, frontend lint/type checking, the production build, and the production dependency audit also passed.

Every proposal remains `awaiting_risk` with confidence explicitly unavailable. It has no provider-specific quantity and cannot reserve capital, approve a trade, access an account, or execute. `TRADING_MODE=paper` remains the only execution setting.

## Phase 7: Risk Engine

**Status:** Complete
**Completed:** 2026-08-15

Phase 7 introduced deterministic, paper-only risk authorization over immutable Phase 6 position-size proposals without adding approval actions or execution.

Completed risk capabilities:

- versioned `mvp_risk` V1 with ordered, structured hard checks and complete failure evidence
- exact exposure escalation: below 10% may auto-approve, exactly 10% through 40% requires human approval while confidence is unavailable, and above 40% requires human approval
- revalidation of paper mode, active strategy and portfolio, latest accounting snapshot, aggregate unexpired authorizations, current opportunity semantics, market and event state, eligible match confidence, latest price and forecast freshness, raw edge, and duplicate economic intent
- append-only `risk_decisions` linked to the exact proposal and observed source records, with stable semantic IDs, effective-policy fingerprints, full check results, audit snapshots, and explicit limitations
- fixed five-minute authorization windows bounded by source validity, with rejected decisions carrying no authorization expiry
- portfolio-row locking around aggregate authorization, duplicate-intent evaluation, and decision persistence
- typed run, list, detail, unexpired-view, and per-proposal history APIs with no approval or execution endpoint
- structural support for future larger proposals while retaining the active Phase 6 sizing policy's strict below-10% cap
- configuration through `RISK_*` settings and a Phase 7 status-page update

Migration `0008_risk_engine` was applied to PostgreSQL and Alembic reported no schema drift. The complete backend suite passed with 239 non-database tests and all four PostgreSQL transaction suites (243 tests total). Phase 7 fixture validation proved risk-decision retry idempotence, duplicate-intent rejection, append-on-source-change history, stale authorization rejection after a newer price, and unchanged portfolio balances. Ruff, strict mypy, frontend lint/type checking, the production build, and production dependency validation also passed.

An `AUTO_APPROVE` decision is short-lived risk authorization evidence only. It does not reserve capital, mutate a balance, create an order, or execute. Adjusted edge and calibrated confidence remain unavailable and liquidity remains unevaluated. Phase 8 now excludes consumed authorizations from aggregate risk and treats an existing open position in the same portfolio and market as duplicate intent. There is no human-approval action.

## Phase 8: Paper Trading Engine

**Status:** Complete
**Completed:** 2026-08-17

Phase 8 introduced provider-free, paper-only entry execution without adding any authenticated market-account or live-order path.

Completed execution capabilities:

- versioned `paper_immediate_fill` V1 with configurable `PAPER_SLIPPAGE_BPS` and `PAPER_FEE_BPS`, plus a fingerprint that records every pricing and rounding assumption
- single-use consumption of an explicit, latest, unexpired `AUTO_APPROVE`; repeated requests return the same immutable terminal trade instead of creating another financial effect
- fixed-order portfolio, market/event parent, and risk-decision locking with post-lock database wall-clock capture before exact reproduction of the active risk decision and every mutable proposal, portfolio, opportunity, match, price, forecast, market, event, and policy input
- direct YES or NO ask execution with additive absolute binary-price-point slippage, upward six-decimal price rounding, and rejection when simulated price reaches one dollar
- largest-affordable whole-contract sizing against the authorized all-in capital cap, with gross cost and nonzero flat estimated fees rounded upward to cents
- post-slippage and post-fee adjusted-edge revalidation before a fill can proceed
- bid-first initial marking with an explicit directional-ask fallback, cent-floor market value, fee-inclusive cost basis, and reproducible unrealized P&L
- atomic creation of one filled trade, one entry-only `OPEN` position, and one next portfolio snapshot; rejected terminal attempts preserve their checks without creating a position or changing balances
- immutable snapshots extended with open-position value, unrealized P&L, total portfolio value, and previous-snapshot identity while retaining the canonical cash, committed, reserved, and available-capital equations
- one-open-position-per-portfolio-and-market enforcement, preventing accidental increases or opposing entries before position-management semantics exist
- typed execution, trade list/detail, and position list/detail APIs
- database migration `0009_paper_execution` for `trades`, `positions`, and the extended accounting ledger, plus unit, service, and API coverage

The Kalshi adapter remains public and read-only, and the execution engine does not call it or any other provider. Phase 8 implements immediate full fills only. It does not add human approval actions, persistent orders or reservations, liquidity or order-book simulation, partial fills, execution latency, provider-specific fee formulas, position increases, opposing holdings, exits, settlement, recurring marking, realized-P&L transitions, or live trading.

## Phase 9: Position Monitoring and Exits

**Status:** Complete
**Completed:** 2026-08-18

Phase 9 added deterministic, provider-free HOLD, REDUCE, CLOSE, and SETTLE decisions over locked paper-position projections. Immutable position events preserve every decision and source fingerprint; quantity, cumulative original basis, proceeds, fees, realized P&L, current projections, and next portfolio snapshots transition atomically. Settlement requires an append-only typed official standard-binary market resolution and never uses an NBA score as contract authority. Exact retries cannot dispose exposure twice, and live/provider-order paths remain absent.

## Phase 10: Evaluation Engine

**Status:** Complete
**Completed:** 2026-08-18

Phase 10 added immutable, versioned forecast-outcome evaluation facts and read-only ledger-derived paper performance.

Completed evaluation capabilities:

- exact twelve-decimal scalar binary-home Brier scoring with `0.5` accuracy abstention
- strict separation of real-time operational forecasts from retrospective historical replay
- canonical one-forecast-per-event/model/purpose selection with result-correction history and semantic reversion
- configurable fixed-width calibration tables including empty bins, ECE, and MCE
- paired model comparison only over the exact shared event/outcome intersection
- authoritative marked-equity, realized, and unrealized P&L and bankroll returns
- completed-position win/loss/breakeven rates, raw and adjusted entry edges, terminal returns, and aggregate return on cost
- immutable opening-lineage grouping across model, opportunity, sizing, risk, execution, and market type
- sequence-sampled maximum drawdown with peak/trough snapshot provenance and explicit valuation warnings
- migration `0011_evaluation_engine`, typed evaluation APIs, unit/API/service/model/PostgreSQL coverage, and paper-only OpenAPI validation

Final Phase 10 validation passed with all 399 backend tests against PostgreSQL, Ruff formatting and linting, strict mypy, Alembic head and schema-drift checks, frontend lint and type checking, the production build, Compose rendering, and a zero-vulnerability production dependency audit. Migration `0011` also normalizes early local Phase 9 schemas so an authoritative standard-binary settlement payout of exactly `1.000000` remains valid without weakening any exit-price constraint.

The local database currently has no normalized NBA event/forecast sample, so real calibration remains empty until historical or operational data is ingested. Historical replay cannot prove when prior results first became available because sports events retain latest state rather than an observation timeline. Drawdown is snapshot-sampled, and open-position equity excludes hypothetical future exit costs.

## Phase 11: Basic Dashboard

**Status:** Complete
**Completed:** 2026-08-20

Phase 11 replaced the static status splash with a responsive, server-rendered paper research desk. A typed server-only adapter reads the existing bounded FastAPI endpoints, selects the active portfolio deterministically, joins market and sports-event display context, and isolates resource failures so one unavailable read cannot blank the page. Decimal accounting values remain strings until display and stored position marks retain their basis and timestamp.

The dashboard exposes portfolio balances, active and terminal position projections, combined entry/monitoring activity, operational forecasts, current opportunities, NBA market quotes, ledger-derived trading performance, and operational calibration. Empty datasets and unavailable metrics are explicit. A persistent `PAPER / SIMULATED` banner, GET-only adapter tests, and the absence of buttons/forms preserve the no-live execution boundary.

Final Phase 11 validation passed all 399 PostgreSQL-backed backend tests and 7 frontend adapter/rendering tests, along with Ruff, strict mypy, frontend lint and type checking, the production build, Compose rendering, Alembic head/drift checks, and a zero-vulnerability production dependency audit. Browser validation against the running local stack confirmed real market rows, API readiness, empty-state semantics, no console errors, the persistent paper boundary, and no body overflow at a 390-by-844 mobile viewport.

Implemented limitations: refresh is manual, list responses are bounded without global totals, and the first active portfolio is shown without an interactive selector. The local database currently has market records but no portfolio or operational forecast sample, so runtime validation exercised real markets plus the intended empty states for portfolio, positions, opportunities, performance, and calibration.

On 2026-08-23 the same read-only surface added MLB research observability. Three bounded server-only
reads expose approved train/validation/test/prospective-holdout counts, the optional durable
historical checkpoint, and its latest immutable batch. A not-yet-created checkpoint is an explicit
empty state rather than an error. Cursor dates/offsets, batch reasons, and disabled
model/probability/trading flags remain visible, but the dashboard has no collection or backfill
mutation control. Independent failures still degrade only their own section.

## Offseason MLB ingestion foundation

**Status:** Complete
**Completed:** 2026-08-21

The first user-approved MLB pilot slice adds a credential-free read-only adapter for the official MLB Stats API. It validates and normalizes active MLB teams and bounded schedules, including scheduled/live/final lifecycle state, inning information, scores, venue, game type, and series metadata. MLB records reuse stable provider-derived identities and the existing transactional team/event persistence while remaining distinguishable through `league=mlb` and `provider=mlb`.

Team and event ingestion can select `provider=mlb` per request without replacing the BALLDONTLIE NBA default. Read APIs now accept explicit `league=nba|mlb` filters. The provider uses timeouts, conservative pacing, bounded retries, raw validated snapshots, and safe failures. It has no credential, market-account access, or order method.

Validation passed all 406 backend tests (7 database-integration tests skipped by default), Ruff, strict mypy, all 7 frontend tests, frontend lint/type checking, and the production build. A live read-only smoke against the official source persisted all 30 active MLB teams and 15 games for August 21, 2026, then returned them through the league-filtered API without changing the configured NBA default.

The Elo model, forecast evaluation, opportunity, sizing, risk, execution, and position paths remain explicitly NBA-only. Probable-pitcher/lineup and Statcast quantitative snapshots were delivered in subsequent bounded slices; an MLB model and all MLB trading eligibility remain future independently validated work.

## Offseason MLB market classification and matching

**Status:** Complete
**Completed:** 2026-08-21

The second MLB pilot slice uses current official Kalshi series and event metadata rather than ticker parsing. Only binary `KXMLBGAME` events declared as `Pro Baseball` / `Game` become typed `mlb` / `single_game_winner` markets. The classification method, version, and semantic fingerprint are persisted and exposed through league-aware market filters. Props, spreads, futures, other baseball leagues, and incomplete metadata fail closed.

Matcher V2 adds a separate MLB alias policy, exact league/provider repository filters, first-pitch comparison, append-only league provenance, and explicit handling for qualified Chicago, Los Angeles, and New York labels. Matched MLB rows are valid research links, but the domain and PostgreSQL safety constraint require `automatic_trading_eligible=false`; NBA is still the only league that can satisfy the matching prerequisite consumed by later phases.

Validation passed all 424 backend tests against PostgreSQL, including an end-to-end MLB database case, plus Ruff, strict mypy, migration upgrade/downgrade, and Alembic drift checks. A live read-only smoke ingested 96 open official MLB game-winner contracts and refreshed 55 official games for August 21–24, 2026. All 96 contracts matched exactly after the schedule refresh and zero were trading-eligible.

## Offseason MLB probable-pitcher and lineup snapshots

**Status:** Complete
**Completed:** 2026-08-22

The third MLB pilot slice reads a bounded typed subset of MLB's official versioned game feed for one explicit local event. It appends probable-pitcher identities and handedness plus unavailable, partial, or posted batting orders with player, order, position, and batting-side metadata. Exact semantic retries replay the same stable record; a changed official source update or content appends history.

Persistence revalidates event, home team, away team, and scheduled start under the event-parent lock. Both Pydantic and PostgreSQL constrain a posted order to nine players and bind `complete_for_pregame_model` to two posted orders, two probable pitchers, and source/retrieval timestamps before first pitch. Live and postgame observations remain visible for audit but cannot qualify. “Posted” deliberately does not mean confirmed because MLB lineups remain subject to change.

Validation passed all 439 backend tests against PostgreSQL, including provider, API, replay, identity-reconciliation, and database-invariant cases, plus Ruff, strict mypy, migration upgrade/downgrade, and Alembic drift checks. The feature adds no MLB forecast, opportunity, sizing, risk, execution, settlement, provider account, or order path.

## Offseason MLB Baseball Savant / Statcast quantitative snapshots

**Status:** Complete
**Completed:** 2026-08-22

The fourth MLB pilot slice adds a credential-free, read-only Baseball Savant Statcast Search CSV adapter and deterministic V1 quantitative contract. One explicit complete lineup drives two bounded requests for its two probable pitchers and 18 posted batters over the exact 30 calendar days ending the day before the target event. Typed pitch rows, response hashes, retrieval time, player metrics, explicit sample counts, and source/policy/input fingerprints are retained in an append-only snapshot tied to the exact event and lineup.

Pitcher profiles expose release velocity/spin and contact allowed; batter profiles expose contact quality. Hard-hit, barrel, expected-wOBA-on-contact, and observed-wOBA measures use exact Decimal aggregation. Missing values remain unavailable. The official live smoke revealed three rows with a wOBA value but no denominator; V1 preserves and counts those incomplete rows while excluding them from observed-wOBA aggregation instead of silently treating them as zero or discarding the otherwise valid response.

Domain, service, and PostgreSQL constraints require an exact complete lineup lineage, a source window ending before the target game, deterministic replay, and consistent operational eligibility. Retrieval strictly before first pitch is `operational_pregame`; later retrieval is retained as `retrospective` and cannot qualify for a future operational model. Public responses expose bounded profiles, manifests, and row counts while keeping the potentially large pitch-row payload internal.

The live official-source smoke for game 823509 retained 6,536 pitch rows, populated both pitcher and all 18 batter profiles, counted three incomplete wOBA rows, and replayed to the same stable record. Because collection occurred after first pitch, it was correctly labeled retrospective and ineligible. This slice adds no MLB probability, calibration, opportunity, sizing, risk, execution, settlement, account, or order path.

Final validation passed all 464 backend tests against PostgreSQL, Ruff formatting and linting, strict mypy, migration `0015_mlb_statcast_features` upgrade/downgrade, Alembic head/drift checks, all 7 frontend tests, frontend lint/type checking and production build, Compose rendering, and a zero-vulnerability production dependency audit.

## Offseason MLB leakage-safe model feature contract

**Status:** Complete
**Completed:** 2026-08-22

The fifth MLB pilot slice deterministically reduces one exact Statcast snapshot to eight auditable
matchup differences. Four lineup metrics use their stored samples as weights; four starting-pitcher
allowed metrics use the opposite orientation so every positive value favors the home team. The
record retains both teams' source metrics, all coverage denominators, ordered selected values,
explicit missing features, source lineage, policy identity, and stable semantic replay.

Operational eligibility requires all eight values plus source retrieval and vector creation strictly
before first pitch. There is no imputation. The pure dataset contract uses explicit chronological
train, validation, test, and prospective-holdout boundaries with random shuffle disabled and labels
only exact official final MLB results. The local official-source smoke produced a complete eight-
feature retrospective vector for game 823509 and correctly kept both probability generation and
automatic trading false; replay returned the same record.

Final validation passed all 479 backend tests with PostgreSQL integrations enabled, Ruff formatting
and linting, strict mypy, migration `0016_mlb_game_features` downgrade/upgrade and Alembic drift
checks, all 7 frontend tests, frontend lint/type checking, and the production build.

## Offseason MLB official outcome labels and dataset inventory

**Status:** Complete
**Completed:** 2026-08-22

The sixth MLB pilot slice adds immutable official final-result labels for one exact feature vector
under caller-supplied, fingerprinted chronological split boundaries. Event-parent locking prevents a
result update from crossing the labeling transaction. Each row freezes scores, winner, source time
and payload, vector and feature-policy identity, split assignment, and outcome/example fingerprints.
Semantic replay returns the original stable record while a corrected official result can append new
evidence.

Read APIs expose label history and an inventory keyed by split-policy fingerprint. Counts separate
operational pregame from retrospective examples, report duplicate-event rows, and keep canonical
dataset selection, fitting, probability generation, and trading disabled. The official local smoke
attempted to label game 823509 while its normalized status remained scheduled and scoreless; the
service correctly returned `409` and persisted no label instead of inventing an outcome.

Final validation passed all 482 backend tests with PostgreSQL integrations enabled, including the
successful final-result/replay/inventory path and database safety rejection. Ruff formatting and
linting, strict mypy, migration `0017_mlb_dataset_examples` downgrade/upgrade and Alembic drift
checks, all 7 frontend tests, frontend lint/type checking, and the production build also passed.

## Offseason MLB bounded collection and canonical dataset

**Status:** Complete
**Completed:** 2026-08-22

The seventh MLB pilot slice adds a bounded research collector that refreshes one explicit official
schedule window and advances only upcoming scheduled events through lineup observation, Statcast
snapshotting, and the fixed eight-feature vector. Calls cover at most seven days and 25 returned
events. Every event returns an explicit skip, incomplete, success, or safe-failure reason; completed,
postponed, and first-pitch-reached games never enter the prospective feature path. Existing
append-only service transactions retain replayable partial progress without creating a batch-level
all-or-nothing illusion.

Canonical dataset reads now choose at most one immutable labeled example per event. Operational
pregame evidence is preferred, followed deterministically by the newest vector, official outcome
observation, label time, and stable identifier. Retrospective fallback requires an explicit flag and
remains research-only. Raw inventory, canonical selection, fitting, probability generation, and
trading eligibility remain separate concepts.

The live official-source smoke refreshed all 15 games for August 23, 2026 and appended 15 official
lineup observations. None had two posted batting orders yet, so all 15 stopped at
`lineup_incomplete`; zero Statcast snapshots or model vectors were fabricated. The current canonical
operational labeled dataset therefore remains empty. Minimum sample thresholds, concrete production
split dates, model fitting, and probability output are still blocked pending sufficient prospective
data and explicit approval.

## Offseason MLB approved readiness and retrospective backfill

**Status:** Complete
**Completed:** 2026-08-22

The eighth MLB pilot slice codifies the user-approved V1 data policy: chronological boundaries at
June 1, July 1, and August 23, 2026; minimum counts of 500 train, 150 validation, 150 test, and 200
prospective-holdout games; retrospective research permitted in the first three intervals; and an
operational-pregame-only holdout. A deterministic fingerprinted evaluator exposes eligible counts,
per-split shortfalls, exploratory-fit readiness, and prospective-evaluation readiness while keeping
model fitting, probability generation, and trading disabled.

Bounded historical backfill now admits an official completed game's two posted lineups and starters
as a complete research payload without mislabeling it pregame. Statcast retrieval after first pitch
is still forced to `retrospective`, the vector remains operationally ineligible, and only an exact
official final result can produce a label. Calls are limited to seven calendar days and ten returned
events, preserving independently replayable append-only progress.

The first live official backfill for August 21, 2026 built and labeled one complete test example.
Its 7,245 retained pitch observations occupy about 259 KiB in PostgreSQL's compressed JSONB storage.
Readiness changed from a test shortfall of 150 to 149; train, validation, and operational holdout
shortfalls remain 500, 150, and 200. No probability or trading capability was enabled.

## Offseason MLB deterministic logistic fitting contract

**Status:** Complete
**Completed:** 2026-08-23

The ninth MLB pilot slice implements a dependency-free deterministic L2 logistic fitter for the
fixed eight-feature candidate. Population means and scales are learned only from each fitting
prefix. Four ascending regularization strengths are fit with Newton updates and selected strictly
by validation mean Brier score; the chosen strength is refit on train plus validation and evaluated
once on the untouched test split. Prospective-holdout rows are rejected from fitting.

The artifact retains standardized coefficients, intercept, means, scales, candidate convergence,
validation and test Brier/log-loss/accuracy metrics, ordered-data and policy fingerprints, and an
effective model version. It is explicitly unpersisted and research-only. The live preview returns
`409` with exact split shortfalls until the approved exploratory counts pass; with 14 official test
examples collected, current shortfalls are 500 train, 150 validation, and 136 test. Operational
probability output and all MLB trading paths remain disabled.

## Offseason MLB resumable historical backfill workflow

**Status:** Complete
**Completed:** 2026-08-23

The tenth MLB pilot slice turns the approved retrospective policy into a durable one-batch workflow.
A fingerprinted checkpoint stores separate train, validation, and test date/page cursors; immutable
batch facts retain the exact split, schedule window, input/result fingerprints, readiness before and
after, per-event outcomes, and safety flags. Selection prioritizes test, validation, then train
shortfalls and walks the 2026 regular season newest to oldest with a hard ten-game batch cap.

Spring Training and every other non-regular MLB game type now fail closed as
`unsupported_game_type`. Cursor movement and a successful batch fact commit atomically under a row
lock. Exact retries replay, concurrent or unexpected state changes fail closed, and official-source
failure returns a retryable error without consuming the cursor. The workflow can terminate as
`complete` when 500/150/150 are reached or `exhausted` when its approved date bounds are consumed;
neither outcome fits a model or enables probability generation or trading.

Validation passed all 495 backend tests (12 database suites skipped by default), the dedicated live
PostgreSQL repository integration test, Ruff, strict mypy, Alembic upgrade/downgrade/upgrade, and an
Alembic drift check. The recurring desktop task invokes exactly one batch per run and reports the
updated checkpoint/readiness; it never calls the arbitrary-window endpoint directly.

The first live automated batch exposed a repository-boundary defect that passed raw UUID and
datetime values from the per-event dataclasses directly to PostgreSQL JSONB. Release `0.11.13`
normalizes those immutable audit facts through the typed JSON serializer before persistence. A
UUID-bearing unit regression and the PostgreSQL checkpoint integration test now cover the exact
failure. All 496 backend tests, Ruff, and strict mypy pass. A manual production-like run then
persisted batch sequence 1, advanced the test cursor from offset 0 to 10, and retained eight labeled
outcomes plus two explicit incomplete-feature reasons without enabling any model or trading path.

## Previous-phase schema repair

**Status:** Complete
**Completed:** 2026-08-21

Migration `0012_phase8_trade_repair` repairs early development databases that carried the final Phase 8 revision identifier before all finalized paper-trade checks were present. It transactionally replaces the incomplete terminal-state check and restores the missing mark-basis and fill-accounting constraints. Existing rows must pass the finalized rules during upgrade; invalid historical accounting therefore fails closed instead of being grandfathered.

The repair is safe on clean databases because it recreates the same constraints already defined by migration `0009`. Its downgrade intentionally retains those Phase 8 invariants: removing a repair revision must not weaken the schema that revision `0009` promises.

Final repair validation passed all 415 backend tests against PostgreSQL, Ruff, strict mypy, all 7 frontend tests, frontend lint/type checking, and the production build. Both the reproduced legacy database and a temporary database migrated from an empty schema reached `0012` with no Alembic drift; the temporary audit database was removed after verification.

## Next phase

Run the checkpointed retrospective workflow until the 500/150/150 exploratory thresholds are met while
collecting and labeling operational games toward the 200-game prospective holdout. Then persist one
immutable fitted research model and begin prospective probability capture. Do not expose an
operational MLB probability until both retrospective out-of-sample and prospective discrimination
and calibration are reported. MLB trading remains disabled. Phase 12 research/evidence work remains
the next broader roadmap milestone.
