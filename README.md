# LATM Prediction Market Platform

An auditable prediction-market research platform focused initially on NBA markets. The current MVP ingests read-only Kalshi market data and authenticated BALLDONTLIE NBA data, deterministically links supported single-game contracts to normalized events, generates versioned event-level Elo base forecasts from local game history, records research-only YES/NO raw-edge opportunities, produces versioned advisory capital allocations against an isolated paper bankroll, records deterministic paper-only risk decisions, and simulates provider-free paper entries with immutable trades, open positions, and portfolio snapshots.

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

The committed example contains local-development values only. Keep real credentials in `.env`; Git ignores that file. `DATABASE_URL` is required by the backend, while a missing `TRADING_MODE` defaults safely to `paper`. Any other trading-mode value is rejected. `PAPER_SLIPPAGE_BPS` and `PAPER_FEE_BPS` configure the versioned Phase 8 simulation assumptions and default to `25.00` and `10.00`. If a default host port is already occupied, change `POSTGRES_PORT`, `BACKEND_PORT`, or `FRONTEND_PORT` in `.env`; when changing `POSTGRES_PORT`, update the port in the host-side `DATABASE_URL` as well.

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

Identical semantic inputs do not create duplicate attempts; changed market text, schedules, candidates, policy, or matcher version append a new historical result. Explicit cross-sport signals, missing teams, multi-team contracts, distant dates, and uncertain candidates remain `unmatched` or `ambiguous`. Only a sufficiently confident `matched` result records the matching prerequisite for automatic paper trading. The matcher itself cannot execute, and every paper entry must still pass sizing, risk, and final execution revalidation.

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

## Paper portfolio and position sizing

Create or idempotently retrieve the default paper portfolio, then size current Phase 5 candidates:

```powershell
$portfolio = Invoke-RestMethod -Method Post -ContentType "application/json" -Body '{}' "http://localhost:8000/portfolios"
Invoke-RestMethod -Method Post "http://localhost:8000/position-sizing/run?portfolio_id=$($portfolio.id)"
```

Inspect balances, immutable snapshots, and advisory proposal history:

```powershell
Invoke-RestMethod "http://localhost:8000/portfolios"
Invoke-RestMethod "http://localhost:8000/portfolios/<portfolio-uuid>/snapshots"
Invoke-RestMethod "http://localhost:8000/position-size-proposals?portfolio_id=<portfolio-uuid>"
Invoke-RestMethod "http://localhost:8000/position-size-proposals/<proposal-uuid>"
```

Rules V1 allocates 2% of available bankroll at an 8% raw edge, 5% at 12%, and 8% at 18% or more. Capital is floored to cents and every effective policy is fingerprinted into its strategy version. The default paper bankroll is `$1,000.00`; settings are configurable through `PAPER_STARTING_BANKROLL` and `POSITION_SIZING_*` variables.

Phase 6 proposals are provider-neutral capital amounts in `awaiting_risk` state. They do not represent provider contract quantity, reserve funds, change balances, approve risk, create a trade, or execute an order. Only current, unexpired `TRADE_CANDIDATE` opportunities may be sized, and source currentness plus event and outcome orientation are revalidated before persistence.

## Risk decisions

Revalidate one proposal or a bounded proposal set against the deterministic Phase 7 policy:

```powershell
Invoke-RestMethod -Method Post "http://localhost:8000/risk-decisions/run?proposal_id=<proposal-uuid>"
Invoke-RestMethod -Method Post "http://localhost:8000/risk-decisions/run?portfolio_id=<portfolio-uuid>"
```

Inspect the latest decision view, unexpired authorization records, or immutable history:

```powershell
Invoke-RestMethod "http://localhost:8000/risk-decisions?latest_only=true"
Invoke-RestMethod "http://localhost:8000/risk-decisions?unexpired_only=true"
Invoke-RestMethod "http://localhost:8000/risk-decisions/<risk-decision-uuid>"
Invoke-RestMethod "http://localhost:8000/position-size-proposals/<proposal-uuid>/risk-decisions"
```

The MVP policy rejects any failed hard check. It returns `AUTO_APPROVE` only when exposure is strictly below 10%; exactly 10% through exactly 40% requires human approval because calibrated confidence is unavailable; above 40% also requires human approval. Decisions revalidate paper mode, the active portfolio and sizing strategy, the latest portfolio snapshot, accounting and aggregate authorized capital, current opportunity semantics, open market/event state, match confidence, price and forecast freshness, raw edge, and duplicate intent.

Non-rejected decisions expire within a fixed five-minute authorization window and may expire sooner with their source evidence. `unexpired_only` means only that the stored authorization time has not elapsed; the Phase 8 boundary still revalidates every mutable source before simulated execution. Phase 7 itself does not implement a human-approval action, reserve capital, create an order, mutate balances, call a provider, or execute a trade. Adjusted edge and calibrated confidence remain unavailable at risk time, and liquidity remains explicitly unevaluated.

## Paper execution and positions

Consume one explicit, still-current automatic authorization as a paper entry attempt:

```powershell
$execution = Invoke-RestMethod -Method Post "http://localhost:8000/paper-execution/run?risk_decision_id=<risk-decision-uuid>"
```

Inspect terminal execution history and entry-only open positions:

```powershell
Invoke-RestMethod "http://localhost:8000/trades?portfolio_id=<portfolio-uuid>"
Invoke-RestMethod "http://localhost:8000/trades/<trade-uuid>"
Invoke-RestMethod "http://localhost:8000/positions?portfolio_id=<portfolio-uuid>"
Invoke-RestMethod "http://localhost:8000/positions/<position-uuid>"
```

`paper_immediate_fill` V1 is paper-only and provider-free: it has no authenticated market-account client and cannot submit a live order. A risk decision is single-use. The service locks the portfolio, market and event source parents, and risk decision in a fixed order; it then captures database wall-clock time and reproduces the complete active risk evaluation against the latest proposal, snapshot, opportunity, match, direct directional ask, forecast, market, event, policy, and available balance. Only a latest, unexpired `AUTO_APPROVE` whose input fingerprint reproduces exactly may continue. A repeated request returns the same terminal trade rather than spending twice.

The fill price adds fixed absolute binary-price slippage, not relative percent slippage:

```text
execution_price = ceil_0.000001(directional_ask + PAPER_SLIPPAGE_BPS / 10000)
```

The engine chooses the largest whole-contract quantity whose gross cost plus the configured flat estimated fee fits inside the authorized capital. Gross cost and nonzero fees round up to cents; the resulting post-cost adjusted edge must still qualify. Initial value uses the same snapshot's directional bid when available, otherwise the directional ask is retained as an explicit fallback mark. A fill atomically creates one immutable trade, one `OPEN` position, and one linked portfolio snapshot; a rejected attempt records its checks but creates neither a position nor a balance transition.

Entry snapshots extend the ledger with open-position value, unrealized P&L, total portfolio value, and the previous-snapshot link. The all-in cost basis, including entry fees, moves from available cash to committed capital. Realized P&L and current bankroll do not change on entry. Phase 8 permits only one open position per portfolio and market, so increases and opposing entries are rejected until position-management semantics exist.

Phase 8 intentionally excludes human approval actions, exits, reductions, settlement, recurring repricing, order-book depth, liquidity sizing, partial fills, execution latency, provider-specific fees, and every live-trading path. Those positions become inputs to Phase 9 monitoring and exit work.

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

See `AGENTS.md`, `ARCHITECTURE.md`, and `ROADMAP.md` for project constraints and phased scope. Paper entry execution is implemented without any live provider path or human-approval action. The next roadmap target is Phase 9 position monitoring and exits.
