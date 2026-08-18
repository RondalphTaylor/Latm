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

## Next phase

Phase 9 should monitor open positions, refresh mark and edge state, and add explicitly audited hold, reduce, close, and settlement transitions with realized-P&L accounting. It must preserve the paper-only default and route every position-changing decision through deterministic risk controls.
