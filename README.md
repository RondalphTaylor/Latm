# LATM Prediction Market Platform

An auditable prediction-market research platform focused initially on NBA markets. The current MVP ingests read-only Kalshi market data and authenticated BALLDONTLIE NBA data, deterministically links supported single-game contracts to normalized events, generates versioned event-level Elo base forecasts from local game history, and records research-only YES/NO raw-edge opportunities from fresh local snapshots.

> **Trading safety:** the only supported execution mode is `paper`. The Kalshi adapter accesses public production market data without credentials, while the BALLDONTLIE key authorizes sports-data reads only. Neither adapter contains order placement, financial-account access, or live-trading implementation.

## Prerequisites

The Docker workflow requires:

- Docker Desktop with Docker Compose v2
- Git

For running checks directly on the host, install Python 3.13 and Node.js 22 with npm.

## Environment setup

From the repository root in PowerShell:

```powershell
Copy-Item .env.example .env
```

The committed example contains local-development values only. Keep real credentials in `.env`; Git ignores that file. `DATABASE_URL` is required by the backend, while a missing `TRADING_MODE` defaults safely to `paper`. Any other trading-mode value is rejected. If a default host port is already occupied, change `POSTGRES_PORT`, `BACKEND_PORT`, or `FRONTEND_PORT` in `.env`; when changing `POSTGRES_PORT`, update the port in the host-side `DATABASE_URL` as well.

## Start the development stack

```powershell
docker compose -f infra/compose.yaml up --build -d
docker compose -f infra/compose.yaml ps
```

The backend is available at [http://localhost:8000/health](http://localhost:8000/health), its database-readiness check at [http://localhost:8000/health/ready](http://localhost:8000/health/ready), and the frontend at [http://localhost:3000](http://localhost:3000).

The backend applies Alembic migrations before starting. To stop the stack while preserving PostgreSQL data:

```powershell
docker compose -f infra/compose.yaml down
```

## Prediction-market ingestion

Trigger a read-only ingestion of currently open NBA markets:

```powershell
Invoke-RestMethod -Method Post "http://localhost:8000/markets/ingest?nba_only=true&status=open"
```

Inspect persisted markets:

```powershell
Invoke-RestMethod "http://localhost:8000/markets?nba_only=true"
Invoke-RestMethod "http://localhost:8000/markets/<internal-market-uuid>"
```

`POST /markets/ingest` reads public provider data and writes normalized snapshots only to the local PostgreSQL database. It cannot place an order. Repeated observations update market and outcome identities while preserving timestamped price history.

## NBA data ingestion

Create a BALLDONTLIE API key and set `BALLDONTLIE_API_KEY` in `.env`. The default 12.1-second request interval respects the provider's documented free-tier limit of five requests per minute.

Ingest NBA teams and a bounded game-date range:

```powershell
Invoke-RestMethod -Method Post "http://localhost:8000/teams/ingest"
Invoke-RestMethod -Method Post "http://localhost:8000/events/ingest?start_date=2026-08-01&end_date=2026-08-01"
```

Inspect normalized teams and events:

```powershell
Invoke-RestMethod "http://localhost:8000/teams"
Invoke-RestMethod "http://localhost:8000/events?start_date=2026-08-01&end_date=2026-08-31"
Invoke-RestMethod "http://localhost:8000/events/<internal-event-uuid>"
```

Game ingestion accepts at most 31 inclusive calendar days per request. Repeated ingestion updates stable team and event identities instead of creating duplicates. A missing API key disables only the two ingestion endpoints with a `503`; persisted read APIs and health endpoints remain available.

## Market-to-event matching

Run the versioned matcher against a bounded local date range after market and NBA event data have been ingested:

```powershell
Invoke-RestMethod -Method Post "http://localhost:8000/matches/run?start_date=2026-08-01&end_date=2026-08-07"
```

Inspect the latest decision per market or the full append-oriented history:

```powershell
Invoke-RestMethod "http://localhost:8000/matches?latest_only=true"
Invoke-RestMethod "http://localhost:8000/matches?latest_only=false&status=ambiguous"
Invoke-RestMethod "http://localhost:8000/markets/<internal-market-uuid>/match"
Invoke-RestMethod "http://localhost:8000/matches/<internal-match-uuid>"
```

Matcher V1 uses boundary-aware canonical names, nicknames, official uppercase abbreviations, curated aliases, and occurrence-time proximity. A result is `matched` only at confidence `0.90` or higher with at least a `0.10` lead over another candidate inside the 36-hour window. These values are configurable, recorded with every result, and are heuristic matching scores—not calibrated probabilities.

Identical semantic inputs do not create duplicate attempts; changed market text, schedules, candidates, policy, or matcher version append a new historical result. Explicit cross-sport signals, missing teams, multi-team contracts, distant dates, and uncertain candidates remain `unmatched` or `ambiguous`. Only a sufficiently confident `matched` result records the matching prerequisite for potential future automatic trading. No execution exists, and every future trade must still pass the risk engine.

## Base forecasting

Generate forecasts from locally persisted NBA results and events:

```powershell
Invoke-RestMethod -Method Post "http://localhost:8000/forecasts/run?purpose=operational&start_date=2026-08-01&end_date=2026-08-07"
Invoke-RestMethod -Method Post "http://localhost:8000/forecasts/run?purpose=historical_replay&start_date=2026-07-01&end_date=2026-07-31"
```

Inspect current or historical snapshots and the immutable model registry:

```powershell
Invoke-RestMethod "http://localhost:8000/forecasts?latest_only=true"
Invoke-RestMethod "http://localhost:8000/forecasts/<forecast-uuid>"
Invoke-RestMethod "http://localhost:8000/events/<event-uuid>/forecasts"
Invoke-RestMethod "http://localhost:8000/forecasts/model-versions"
```

`nba_elo` V1 starts every unseen team at 1500, uses K=20, a 400-point logistic scale, and a 100-point home-court adjustment. It replays only local final games in strict scheduled-tip order. Operational forecasts are limited to future scheduled events referenced by the latest eligible Phase 3 match; historical replay forecasts do not require a market match and are explicitly labeled simulations. The model never reads market prices, calls an external provider, creates an opportunity, or places a trade.

Identical model, event, and training inputs reproduce the same probabilities and semantic fingerprints and do not create duplicates. Corrected or newly backfilled prior results append a new snapshot instead of overwriting history. The current historical replay uses scheduled game time because the normalized schema does not yet preserve when each historical result first became available; it is suitable for deterministic model evaluation, not a claim of contemporaneous data availability.

## Opportunity detection

Compare the newest eligible local market, match, event, and operational forecast snapshots:

```powershell
Invoke-RestMethod -Method Post "http://localhost:8000/opportunities/run?start_date=2026-08-01&end_date=2026-08-07"
```

Inspect current classifications, complete history, or one market:

```powershell
Invoke-RestMethod "http://localhost:8000/opportunities?latest_only=true"
Invoke-RestMethod "http://localhost:8000/opportunities?latest_only=false&current_only=false&status=watch&direction=yes"
Invoke-RestMethod "http://localhost:8000/opportunities/<opportunity-uuid>"
Invoke-RestMethod "http://localhost:8000/markets/<market-uuid>/opportunities"
```

Raw-edge V1 compares the independent team-win probability with that contract side's direct executable ask: `raw_edge = model_probability - side_ask_probability`. It evaluates YES and NO independently, records edges to six decimal places, and defaults to `IGNORE` below 3 percentage points, `WATCH` from 3 to below 8 points, and `TRADE_CANDIDATE` at 8 points or more. Thresholds and freshness limits are configurable through the `OPPORTUNITY_*` settings and are fingerprinted into every effective strategy version.

The engine never substitutes bids, last prices, midpoints, complements, older snapshots, or a different forecast-model version. It skips stale, future, internally inconsistent, boundary-priced, unmatched, postponed, started, closed, semantically changed, or ambiguously oriented inputs and reports skip counts. An observation-only sports refresh does not invalidate a forecast, while a schedule, team, or status change requires regeneration. Identical semantic inputs are idempotent; a changed price, forecast, match, orientation, or policy appends history.

`GET /opportunities` defaults to `current_only=true`: expired records or records superseded by a newer price, match, or same-model forecast are suppressed even when the newer source cannot produce a replacement. Use `current_only=false` for audit history. `TRADE_CANDIDATE` is only a research classification; it is not a proposal, approval, order, or execution instruction.

## Backend development

Backend packaging uses the standard PEP 621 `pyproject.toml` format with bounded dependency ranges and pip/venv. This keeps Phase 0's bootstrap toolchain small and works identically on the host, in Docker, and in CI without requiring Poetry or another package manager.

Start PostgreSQL, then install the backend in an isolated environment:

```powershell
docker compose -f infra/compose.yaml up -d db
Set-Location backend
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

Run backend validation from `backend/` with the virtual environment active:

```powershell
pytest
ruff check .
ruff format --check .
mypy app tests
```

Apply or inspect database migrations from `backend/`:

```powershell
alembic upgrade head
alembic current
```

## Frontend development

From `frontend/`:

```powershell
cmd /c npm ci
cmd /c npm run dev
```

Run frontend validation:

```powershell
cmd /c npm run lint
cmd /c npm run typecheck
cmd /c npm run build
```

## Continuous integration

`.github/workflows/ci.yml` runs on pull requests and pushes to `main`. It checks backend tests, linting, formatting, typing, and migrations; frontend linting, typing, and production build; and Docker Compose configuration. CI uses only a temporary PostgreSQL service and paper mode.

## Git publication workflow

After each completed and verified phase—or another coherent, independently reviewable change—stage only the files that belong to that change, create a focused local commit, and push the resulting commit to the configured GitHub remote. Do not leave completed work only in the local repository.

Use concise conventional commit messages where practical. Keep unrelated changes in separate commits, never commit secrets or generated caches, and do not push changes while relevant validation is failing. Direct pushes are appropriate for this repository's current single-owner workflow; use a feature branch and pull request when branch protection, collaboration, review requirements, or the risk of the change makes that safer. If remote authentication or authorization is unavailable, stop and request the required access instead of silently leaving the commit unpublished.

## Repository structure

```text
backend/              FastAPI application, SQLAlchemy, Alembic, and tests
frontend/             Minimal Next.js paper-mode and model status application
infra/compose.yaml    Backend, frontend, and PostgreSQL development stack
docs/                 Product, architecture, safety, and progress documentation
```

See `AGENTS.md`, `ARCHITECTURE.md`, and `ROADMAP.md` for project constraints and phased scope. Position sizing and all trading behavior remain intentionally unimplemented. The next roadmap target is Phase 6.
