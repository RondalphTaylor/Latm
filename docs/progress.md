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

## Next phase

Phase 5 should compare current independent base probabilities against persisted prediction-market prices and record auditable YES/NO opportunity candidates. It must not place trades or bypass future risk controls.
