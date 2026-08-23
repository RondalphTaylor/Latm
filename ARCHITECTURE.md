# System Architecture

## 1. Purpose

This document defines the high-level technical architecture for the prediction-market research and trading platform.

The initial system focuses on NBA prediction markets and paper trading.

The architecture should support future expansion to:

* additional sports
* additional prediction-market platforms
* additional data providers
* AI-assisted evidence analysis
* live trading
* mobile interfaces
* more advanced forecasting models

The system should remain modular without introducing unnecessary infrastructure during the MVP stage.

---

# 2. Architectural Goals

The architecture should optimize for:

* correctness
* auditability
* modularity
* experimentation
* testability
* safe trading behavior
* clear separation of responsibilities
* easy development with Codex
* future expansion without major rewrites

The architecture should not optimize prematurely for massive scale.

Initial deployment will support a single operator and relatively low trading volume.

---

# 3. High-Level Architecture

The system is divided into several logical layers.

```text
                     EXTERNAL SYSTEMS

          Prediction Markets      Sports Data
                 │                    │
                 │                    │
                 ▼                    ▼

              DATA INGESTION LAYER

                 │
                 ▼

            NORMALIZATION LAYER

                 │
                 ▼

              DATA STORAGE
               PostgreSQL

                 │
       ┌─────────┴─────────┐
       │                   │
       ▼                   ▼

FORECASTING ENGINE    RESEARCH ENGINE
       │                   │
       │                   ▼
       │             AI EVIDENCE ENGINE
       │                   │
       └─────────┬─────────┘
                 │
                 ▼

         FINAL FORECAST ENGINE

                 │
                 ▼

        OPPORTUNITY ENGINE

                 │
                 ▼

            RISK ENGINE

                 │
                 ▼

         EXECUTION ENGINE

           ┌─────┴─────┐
           │           │
           ▼           ▼

     PAPER TRADING   LIVE TRADING
                      FUTURE ONLY

                 │
                 ▼

        POSITION MANAGEMENT

                 │
                 ▼

           EVALUATION ENGINE

                 │
                 ▼

         API / WEBSOCKET LAYER

                 │
                 ▼

         TYPESCRIPT DASHBOARD
```

These represent logical components.

During early development, most backend components should exist within a single Python application rather than as separate networked microservices.

---

# 4. Recommended Technology Stack

## Backend

Primary language:

Python

Framework:

FastAPI

Responsibilities:

* REST API
* WebSocket connections
* market ingestion
* sports data ingestion
* forecasting
* paper trading
* risk management
* execution coordination
* evaluation

Python code should use explicit type annotations.

---

## Frontend

Framework:

Next.js

Language:

TypeScript

Responsibilities:

* dashboard
* active positions
* opportunities
* trade history
* forecast inspection
* performance analytics
* approval requests
* risk configuration

The initial frontend should be responsive enough to use from a mobile browser.

A native mobile application is not required for the MVP.

The implemented Phase 11 dashboard is a single Next.js Server Component route with anchored sections. A typed server-only adapter reads bounded FastAPI endpoints through `BACKEND_API_URL` with `cache: no-store`; the browser never calls FastAPI directly, so the MVP does not require CORS. Independent read failures remain isolated by section. Decimal accounting values stay as strings through the adapter and the UI renders authoritative portfolio, position, and evaluation fields without recomputing them.

The dashboard is observational only. It contains no execution, monitoring-run, ingestion, approval, credential, provider-account, or live-order controls, and it displays the paper/simulated boundary persistently at desktop and mobile widths.

---

## Database

Primary database:

PostgreSQL

Responsibilities:

* markets
* events
* prices
* forecasts
* evidence
* trades
* positions
* model versions
* strategy versions
* evaluation results

PostgreSQL should remain the initial source of truth.

Specialized databases should not be introduced until a demonstrated need exists.

---

## Cache and Task Coordination

Initial implementation:

Python asyncio and application-level background tasks where sufficient.

Potential future addition:

Redis

Redis may eventually support:

* caching
* distributed task coordination
* event queues
* rate limiting
* background jobs

Redis should not be required for the earliest MVP unless it solves a concrete problem.

---

## Infrastructure

Development:

Docker Compose

Initial containers may include:

* backend
* PostgreSQL
* frontend

Future deployment may use:

* AWS
* managed PostgreSQL
* container hosting
* object storage

Infrastructure should remain portable.

---

# 5. Proposed Repository Structure

```text
prediction-market-bot/
│
├── AGENTS.md
├── README.md
├── ARCHITECTURE.md
├── ROADMAP.md
│
├── docs/
│   ├── product-spec.md
│   ├── prediction-system.md
│   ├── paper-trading.md
│   ├── risk-policy.md
│   ├── data-sources.md
│   ├── codex-workflow.md
│   └── decisions/
│
├── backend/
│   ├── pyproject.toml
│   │
│   ├── app/
│   │   ├── main.py
│   │   │
│   │   ├── api/
│   │   │
│   │   ├── core/
│   │   │
│   │   ├── db/
│   │   │
│   │   ├── models/
│   │   │
│   │   ├── schemas/
│   │   │
│   │   ├── providers/
│   │   │   ├── prediction_markets/
│   │   │   ├── sports/
│   │   │   └── research/
│   │   │
│   │   ├── services/
│   │   │   ├── markets/
│   │   │   ├── events/
│   │   │   ├── forecasting/
│   │   │   ├── evidence/
│   │   │   ├── opportunities/
│   │   │   ├── risk/
│   │   │   ├── execution/
│   │   │   ├── positions/
│   │   │   └── evaluation/
│   │   │
│   │   └── workers/
│   │
│   └── tests/
│
├── frontend/
│   ├── package.json
│   ├── app/
│   ├── components/
│   ├── lib/
│   └── types/
│
├── infra/
│   ├── docker/
│   └── docker-compose.yml
│
└── scripts/
```

This structure may evolve.

Codex should not create empty directories purely to match this document.

Directories should be introduced when the corresponding functionality is implemented.

---

# 6. Core Domain Models

The system should define provider-independent internal models.

External API responses should be converted into these internal models before entering business logic.

Core models include:

* PredictionMarket
* MarketPrice
* OrderBook
* SportsEvent
* Team
* Player
* Forecast
* EvidenceItem
* Opportunity
* ProposedTrade
* Trade
* Position
* Portfolio
* RiskDecision

---

# 7. Prediction-Market Provider Architecture

Prediction-market platforms should be accessed through provider adapters.

Core business logic must not directly depend on a platform-specific API.

Conceptual interface:

```python
from typing import Protocol


class PredictionMarketProvider(Protocol):
    async def list_markets(self) -> list["PredictionMarket"]:
        ...

    async def get_market(
        self,
        market_id: str,
    ) -> "PredictionMarket":
        ...

    async def get_order_book(
        self,
        market_id: str,
    ) -> "OrderBook":
        ...

    async def place_order(
        self,
        order: "OrderRequest",
    ) -> "OrderResult":
        ...
```

The exact interface may evolve.

The important architectural rule is:

```text
Platform API
    ↓
Provider Adapter
    ↓
Normalized Internal Model
    ↓
Core Business Logic
```

Future platform integrations should implement the same provider abstraction.

---

# 8. Sports Data Provider Architecture

Sports data providers should follow a similar adapter pattern.

Conceptual interface:

```python
from datetime import date
from typing import Protocol


class SportsDataProvider(Protocol):
    async def get_games(
        self,
        game_date: date,
    ) -> list["SportsEvent"]:
        ...

    async def get_team(
        self,
        team_id: str,
    ) -> "Team":
        ...

    async def get_injuries(
        self,
        event_id: str,
    ) -> list["PlayerStatus"]:
        ...
```

Provider-specific field names must not leak into forecasting logic.

---

# 9. Market Normalization

Each prediction-market provider may represent markets differently.

The normalization layer should convert external data into a consistent internal format.

A normalized market should include information such as:

* internal ID
* provider
* provider market ID
* title
* description
* resolution criteria
* outcome options
* current prices
* volume
* liquidity
* start time
* close time
* resolution time
* raw provider metadata

Raw provider responses may be retained for debugging and audit purposes.

---

# 10. Sports Event Normalization

Sports events should be represented independently of the sports data provider.

A normalized game should contain:

* internal event ID
* external provider IDs
* home team
* away team
* scheduled start time
* venue
* game status
* final score when available

Forecasting code should operate against normalized events.

The sports domain now supports `nba` and `mlb`. BALLDONTLIE remains the NBA provider, while the
offseason pilot adds a public read-only official MLB Stats API adapter for active teams, bounded
schedules, lifecycle state, scores, venue, and series metadata. Both providers persist into the
same normalized tables with stable provider identities and explicit league values.

MLB probable pitchers and batting orders use a narrower official live-feed adapter contract and an
append-only `mlb_lineup_snapshots` table rather than mutating `sports_events`. One explicit request
observes one already-normalized MLB event, then revalidates game, home team, away team, and scheduled
start under an event-parent lock before insertion. The semantic fingerprint includes the official
source update and bounded typed payload, so exact retries replay while source changes append history.
Unavailable and partial orders are preserved. `posted` means exactly nine unique batting slots; it
does not claim a lineup is final. A snapshot is complete for future pregame-model use only when both
orders are posted, both probable pitchers exist, and source update plus retrieval precede first pitch.
Live and postgame records can be audited but cannot qualify as pregame inputs.

Quantitative MLB inputs use a separate public read-only Baseball Savant / Statcast Search CSV
adapter and append-only `mlb_statcast_feature_snapshots`. One explicit request binds one exact
complete lineup snapshot to two bounded multi-player source queries: its two probable pitchers and
18 posted batters. V1 uses the 30 calendar days ending one day before the target event date. It
retains a typed subset of every source pitch, response hashes, retrieval time, explicit complete and
incomplete sample counts, deterministic player aggregates, and source/policy/input fingerprints.
Incomplete official metric pairs remain source evidence but never enter an aggregate as zero.

The service locks and revalidates the normalized event followed by its lineup parent before an
append or semantic replay. Cross-event lineage is blocked by a composite foreign key. Retrieval
strictly before first pitch is labeled `operational_pregame`; later observations are
`retrospective` and structurally ineligible. Public reads expose bounded player profiles and source
counts rather than the potentially large internal pitch-row payload. This contract generates no
probability and has no dependency on prediction-market prices or any execution provider.

Derived MLB candidate inputs live in append-only `mlb_game_feature_vectors`, with a composite
foreign key to the exact event/lineup/Statcast source. V1 pools batter metrics by their explicit
sample denominators, requires all nine batters per lineup metric, retains starter metrics directly,
and orients all eight differences so positive favors the home team. Missing values are never
imputed. A vector can be operational only when the quantitative source and vector both predate
first pitch; retrospective vectors remain useful for research but cannot become operational model
inputs. The versioned dataset contract partitions by scheduled start time, never random shuffling,
and labels only exact official final results. This layer contains no fitted parameters, probability,
market price, opportunity, or execution dependency.

Official MLB outcome labels are separate append-only `mlb_labeled_feature_examples`. The service
locks the mutable normalized event parent, captures database time after the lock, requires a final
decisive official score, then freezes the event/source snapshot, exact vector, split boundaries, and
fingerprints in one transaction. Result corrections append a new semantic fact rather than mutating
old evidence. Dataset inventory is always keyed by one split-policy fingerprint and separates
operational from retrospective provenance. It reports duplicate-event examples without treating raw
history as a training set.

The bounded prospective collector is an orchestration layer over the existing official schedule,
lineup, Statcast, and game-feature services. It accepts at most seven calendar days, returns at most
25 events per call, and advances only scheduled games strictly before first pitch. Each underlying
append is independently transactional, so an interrupted batch retains auditable partial progress
and can be replayed safely. The application does not contain a scheduler; an external timer must
invoke collection near lineup publication.

Canonical dataset reads rank immutable labeled examples within each event. Operational pregame
evidence always outranks retrospective evidence, followed by newest feature build, official outcome
observation, label time, and stable ID. Retrospective fallback is explicit and research-only. The
selection is deterministic and paginated, but it fits no coefficients and emits no probability.

The approved MLB dataset-readiness V1 policy freezes chronological boundaries at June 1, July 1,
and August 23, 2026, with minimum counts of 500 train, 150 validation, 150 test, and 200 prospective
holdout games. Retrospective examples may satisfy only the first three exploratory intervals. The
prospective holdout counts only operational pregame examples. A pure evaluator fingerprints this
policy and reports every split shortfall without granting model, probability, or trading authority.

Bounded retrospective backfill may use a complete official postgame lineup payload for research.
This does not redefine `complete_for_pregame_model`: only two posted nine-player orders and two
starters are admitted, Statcast retrieval after first pitch remains structurally `retrospective`,
and the resulting vector and label stay ineligible for operational use. Each call handles at most
seven dates and ten returned events, using the same append-only lineage and official final-result
checks as explicit single-record ingestion.

This shared storage does not make the downstream pipeline sport-agnostic by implication. The
matcher now supports separately versioned NBA and MLB alias policies, while the Elo model, forecast
evaluation, opportunity, risk, and trading services retain their explicit NBA gates. A persisted MLB
match is always research-only and database-constrained to `automatic_trading_eligible=false`.
The lineup, Statcast, derived-vector, and labeled-example slices do not relax any downstream gate.
There is still no fitted MLB model and no MLB probability enters the opportunity or trading pipeline.

---

# 11. Market-to-Event Matching

Prediction markets must be matched to their underlying sports events.

Example:

```text
Prediction Market

"Will the Knicks beat Boston tonight?"

                ↓

Event Matching

                ↓

NBA Event

New York Knicks
vs
Boston Celtics
November 15
7:30 PM ET
```

Initial matching may use:

* team names
* aliases
* event dates
* start times
* market metadata

Matching should produce a confidence score.

Example:

```text
MATCHED
confidence = 0.99
```

or:

```text
AMBIGUOUS
confidence = 0.62
```

Ambiguous matches should not be automatically traded.

The system should store the matching result and confidence.

The deterministic matcher uses exact, boundary-aware league-specific aliases and event-time proximity. NBA and MLB alias dictionaries are separate. Ambiguous MLB city names such as Chicago, Los Angeles, and New York cannot independently identify a team; qualified official labels or stronger evidence are required. A `MATCHED` result requires the configured minimum confidence and sufficient separation from the runner-up; otherwise plausible results remain `AMBIGUOUS`. Matching scores are inspectible heuristics, not calibrated forecast probabilities.

Match attempts are append-oriented and keyed by a matcher version plus semantic input fingerprint. Unchanged reruns are idempotent, while changed league, market text, schedules, candidate events, policies, or matcher versions preserve a new audit record. Supported sports markets first require an exact persisted provider-metadata classification; the broad legacy `is_nba` flag is discovery input only. NBA matched rows may satisfy the matching prerequisite, while MLB matched rows are structurally ineligible for all downstream decision and execution paths.

---

# 12. Forecasting Architecture

Forecasting should occur in stages.

```text
Structured Sports Data
        │
        ▼

Base Forecast Model
        │
        ▼

Base Probability
        │
        ├───────────────┐
        │               │
        │               ▼
        │        External Research
        │               │
        │               ▼
        │        Evidence Processing
        │               │
        │               ▼
        │       AI Evidence Analysis
        │               │
        └───────┬───────┘
                │
                ▼

        Final Forecast
```

The base model and evidence-adjustment system should remain independently measurable.

---

# 13. Base Forecast Model

The base model should implement a common forecasting interface.

Conceptually:

```python
from typing import Protocol


class ForecastModel(Protocol):
    async def predict(
        self,
        event: "SportsEvent",
    ) -> "BaseForecast":
        ...
```

Every output should include:

* probability
* model name
* model version
* timestamp
* relevant feature values

Multiple models may eventually coexist.

Example:

```text
nba_elo_v1

nba_logistic_v1

nba_ml_v1
```

The system should allow their performance to be compared.

The first implementation is synchronous, deterministic `nba_elo` V1. It starts unseen teams at 1500 and calculates:

```text
p_home = 1 / (1 + 10 ^ (-(home_rating + 100 - away_rating) / 400))
delta = 20 * (actual_home_win - p_home)
```

Home receives `delta` and away loses the same amount. There is no margin-of-victory term, season reset, recency weighting, rest feature, injury input, advanced statistic, sportsbook probability, or prediction-market price in V1.

The service replays final normalized games from PostgreSQL in `(scheduled_start_time, event_id)` order. A result is applied only when its scheduled start is strictly before the forecast cutoff. Operational forecasts use one generation-time cutoff and require a future scheduled event referenced by a latest eligible market-to-event match. Historical replay uses the target tip as its cutoff and is labeled as a simulated chronological backtest because current source records do not preserve historical result-availability time.

Every effective parameter set receives a configuration fingerprint embedded in its model version. `model_versions` stores the full immutable configuration and formula. `base_forecasts` stores complementary probabilities, pregame ratings, replay counts, cold-start features, source timestamps, training-data fingerprint, and semantic input fingerprint. Identical semantic reruns are idempotent; changed history or target inputs append a snapshot instead of overwriting one.

---

# 14. Research Architecture

Research providers retrieve external information related to a market or event.

Potential sources include:

* official reports
* sports news
* injury reports
* social media
* betting information

The research layer should return documents or structured source records.

The research layer should not directly modify probabilities.

---

# 15. Evidence Architecture

The evidence system converts retrieved information into structured claims.

Conceptual evidence model:

```text
EvidenceItem

id
event_id
source
source_type
claim
reliability
freshness
relevance
independence_group
direction
estimated_impact
created_at
```

The independence group may be used to avoid counting repeated reports of the same original information multiple times.

---

# 16. AI Agent Architecture

AI agents should operate within the evidence and forecasting layers.

Potential logical agents:

## Research Agent

Determines what information should be investigated.

## Evidence Agent

Evaluates individual information items.

## Forecast Agent

Estimates how evidence may affect the base probability.

## Critic Agent

Attempts to identify:

* unsupported assumptions
* missing evidence
* contradictory evidence
* duplicated evidence
* overconfidence

AI agents must return structured outputs validated by schemas.

AI agents must not directly execute trades.

AI agents must not bypass deterministic risk controls.

---

# 17. Final Forecast Engine

The final forecast engine combines:

* base probability
* evidence adjustments
* uncertainty
* confidence

Output:

```text
FinalForecast

event_id
base_probability
final_probability
lower_bound
upper_bound
confidence
evidence_ids
base_model_version
ai_model_version
created_at
```

The exact probability-combination method may evolve.

The system should make the method versioned and reproducible.

---

# 18. Opportunity Engine

The opportunity engine compares internal forecasts with market prices.

The Phase 5 implementation is a deterministic, provider-neutral raw-edge engine. It consumes only locally persisted normalized data and the exact current `nba_elo` operational model identity. For each supported binary event-winner contract it resolves YES and NO to the matched event teams, then evaluates each side independently:

```text
raw_edge = model_team_win_probability - direct_side_ask_probability
```

Only direct `yes_ask` and `no_ask` values are supported. Bids, last prices, midpoints, cross-snapshot fields, and inferred complements are not substituted. The newest match, price, and forecast snapshots are selected before safety checks, so stale or ineligible current data cannot fall back to older favorable evidence.

Runs require an active market, a latest eligible match, an upcoming scheduled non-postponed event, a fresh internally consistent price book, a fresh operational forecast from the exact configured model version, and an unambiguous outcome-to-team mapping. Forecasts store a semantic event fingerprint over schedule, teams, and status; observation-only refresh timestamps are excluded. Every accepted side stores the exact source identifiers and snapshot, mapping and policy fingerprints, price and forecast ages, a conservative validity deadline, the signed six-decimal edge, and its classification.

Input:

```text
Final Forecast
+
Market Price
+
Order Book
```

Output:

```text
Opportunity
```

An opportunity may include:

* market probability
* model probability
* raw edge
* adjusted edge
* confidence
* liquidity
* suggested direction
* opportunity status

Phase 5 statuses are:

* IGNORE
* WATCH
* TRADE_CANDIDATE

Thresholds and freshness limits are typed configuration and are fingerprinted into the effective strategy version. Opportunity rows are append-only and semantically idempotent: an exact rerun creates no duplicate, while a changed source snapshot or policy appends history. The default list is current-only and suppresses expired rows or rows whose price, match, or same-model forecast is no longer newest; audit history remains available explicitly. Latest history is partitioned by market, direction, strategy version, and model version so version filters do not resurrect stale statuses or hide the requested model's latest row. `TRADE_CANDIDATE` conveys no trading authority. The opportunity engine has no provider call, order, portfolio, approval, risk, or execution path.

---

# 19. Risk Engine

The risk engine evaluates proposed trades before execution.

Input:

```text
Opportunity
+
Portfolio
+
Existing Positions
+
Risk Configuration
```

Output:

```text
RiskDecision
```

Possible decisions:

* REJECT
* AUTO_APPROVE
* REQUIRE_HUMAN_APPROVAL

Risk checks may include:

* proposed bankroll percentage
* confidence
* liquidity
* total portfolio exposure
* correlated exposure
* maximum daily risk
* drawdown limits
* trading mode

The risk engine is deterministic.

LLM output may be one input to confidence calculations, but an LLM must not override risk rules.

Phase 7 implements `mvp_risk` V1 as a pure rules engine over an exact Phase 6 proposal and authoritative current state. It evaluates all ordered hard checks and records every result. Any hard failure produces `REJECT`. A fully valid exposure strictly below 10% produces `AUTO_APPROVE`; exposure from exactly 10% through exactly 40% produces `REQUIRE_HUMAN_APPROVAL` because calibrated confidence is unavailable; exposure above 40% also requires human approval.

The service locks the proposal's paper portfolio while it loads the latest snapshot and calculates aggregate unexpired automatic authorizations and duplicate economic intent. `risk_decisions` rows are append-only, policy-versioned, source-linked, and semantically idempotent. Non-rejected records use fixed five-minute UTC authorization windows bounded by source freshness, opportunity validity, market close, and event start. Rejected records have no authorization expiry.

An `AUTO_APPROVE` result is risk authorization evidence only. It does not reserve capital or mutate portfolio accounting, and there is no human-approval action in Phase 7. Phase 8 consumes an automatic authorization at most once and atomically reproduces the active risk evaluation against the latest risk record, price, forecast, match, opportunity, proposal, portfolio snapshot, policy versions, open-position state, and available bankroll before a simulated entry. Adjusted edge and calibrated confidence are unavailable at risk time; liquidity remains explicitly unevaluated.

---

# 20. Position Sizing

Position sizing should be implemented separately from risk approval.

The position-sizing engine proposes a size.

The risk engine determines whether that proposal is allowed.

Phase 6 implements a deterministic provider-neutral `raw_edge_bands` V1. It accepts only current, unexpired Phase 5 `TRADE_CANDIDATE` rows and an immutable paper-portfolio snapshot. Before persistence, it revalidates opportunity currentness, the semantic event fingerprint, and YES/NO team orientation. The default bands allocate 2% of available bankroll at a raw edge from 0.08 to below 0.12, 5% from 0.12 to below 0.18, and 8% at 0.18 or above. Capital is floored to cents and the stored exposure is calculated from the actual floored capital.

The effective thresholds, fractions, formula, policy fingerprint, exact opportunity identity, source snapshot, and portfolio snapshot are stored with every immutable `position_size_proposals` row. Exact semantic reruns are idempotent; a changed policy creates a new historical proposal. Confidence is explicitly `not_available`. A proposal is advisory and remains `awaiting_risk`; it has no provider-specific quantity and cannot reserve funds, mutate a balance, approve risk, create a trade, or execute.

Conceptually:

```text
Opportunity
    │
    ▼
Position Sizer
    │
    ▼
Proposed Trade
    │
    ▼
Risk Engine
    │
    ▼
Execution
```

This separation allows sizing strategies to evolve independently.

---

# 21. Execution Architecture

Phase 8 implements only the `paper` execution mode. The entry service accepts an explicit risk-decision ID, requires a latest and unexpired `AUTO_APPROVE`, and returns one terminal `filled` or `rejected` trade. A unique risk-decision constraint and stable trade identity make the authorization single-use; an exact retry returns the existing result.

The persistence boundary locks the paper portfolio, market and event source parents, and risk decision in a fixed order before capturing database wall-clock time and loading the execution graph. It then reproduces the active Phase 7 risk decision from authoritative state. The risk fingerprint, active risk and sizing policy versions, exact latest portfolio snapshot, opportunity semantics, match, direct directional price, forecast, market and event state, available bankroll, prior execution, and existing open position must all pass again. Filled trades, their position, and their next portfolio snapshot commit in one transaction. Rejected attempts remain audit history and cannot change the ledger.

No execution provider or provider account is called. The Kalshi adapter remains public and read-only, and no authenticated order, live account, credential, or live-mode implementation exists. A future common paper/live execution interface must preserve this internal trade schema without weakening the explicit live-trading boundary.

---

# 22. Paper Trading Architecture

The versioned `paper_immediate_fill` V1 engine uses an exact provider-free simulation:

```text
execution_price = ceil_0.000001(direct_directional_ask + slippage_bps / 10000)

gross_cost = ceil_cent(execution_price * whole_contract_quantity)
fee = 0, or ceil_cent(gross_cost * fee_bps / 10000)
total_cost = gross_cost + fee
```

Here `slippage_bps` is an absolute binary-price-point adjustment: 25 bps adds `0.0025` to the ask. The engine selects the largest integer quantity whose all-in cost fits the authorized capital, decreasing the estimate when cent-rounded fees would exceed the cap. It rejects prices at or above one dollar, fewer than one affordable contract, or a post-slippage and post-fee adjusted edge below the active qualifying threshold.

The opening mark uses the direct directional bid when present and valid. If no bid exists, the direct ask is stored with `directional_ask_fallback` so the audit record does not imply an executable exit. Market value rounds down to cents, total cost basis includes entry fees, and initial unrealized P&L is market value minus total cost basis.

One filled authorization produces an immutable trade, one entry-only `OPEN` position, and one immutable accounting snapshot. `trades` also preserves rejected terminal attempts and all checks, source IDs, strategy versions, configured costs, rounding results, fingerprints, and audit assumptions. Phase 8 supports only immediate full fills and one open position per portfolio and market. Order-book depth, liquidity, partial fills, maximum prices, latency, position increases, opposing entries, and provider-specific fees remain later realism work.

---

# 23. Position Management

The position manager tracks open positions.

Responsibilities include:

* current position size
* average entry price
* realized P&L
* unrealized P&L
* current market value
* current forecast
* current edge

The position manager supports:

* hold
* reduce
* close
* settle

Phase 9 keeps the Phase 8 entry trade immutable and treats `positions` as a locked current projection. Every reevaluation appends an immutable `position_events` record containing exact source IDs, before/after quantity and remaining basis, decision checks, policy identity, proceeds, realized P&L, fingerprints, and portfolio-snapshot links. The projection has `open`, `closed`, and `settled` states. Exact semantic retries replay the prior event; they cannot reduce or close twice. Increasing and opposing positions remain unsupported.

Monitoring runs one position per transaction with the fixed lock prefix portfolio, market parent, sports-event parent, position, latest portfolio snapshot, then latest match/price/forecast/resolution rows. It captures database wall-clock time only after lock waits. A state transition and its event and snapshot commit atomically, and aggregate position projections must reconcile with the portfolio ledger before commit.

---

# 24. Exit Evaluation

Open positions should be periodically reevaluated.

Triggers may include:

* market price change
* forecast change
* new evidence
* loss of edge
* approaching resolution
* risk limit changes

The initial deterministic policy uses the latest direct held-side bid and latest operational forecast from the opening model lineage. Settlement takes precedence. Closed-but-unresolved markets, post-start events, stale or incomplete sources, and invalid semantics explicitly HOLD. Otherwise nonpositive remaining edge closes, positive edge below the configured threshold reduces exposure, and edge at or above the threshold holds. A one-contract reduction becomes a full close.

The system records exit reasons and exact paper economics. Early exits use:

```text
exit_price = floor_0.000001(directional_bid - exit_slippage_bps / 10000)
gross_proceeds = floor_cent(exit_price * disposed_quantity)
exit_fee = 0, or ceil_cent(gross_proceeds * exit_fee_bps / 10000)
realized_increment = gross_proceeds - exit_fee - allocated_entry_basis
```

Partial basis allocation is cumulative from the original quantity and original gross/fee components, leaving rounding residue for the final disposal.

Example:

```text
EDGE_DISAPPEARED

FORECAST_REVERSED

RISK_REDUCTION

MARKET_RESOLVED
```

Official settlement is normalized through the read-only provider adapter into append-only `market_resolutions`. It requires a terminal standard-binary provider status, typed YES/NO result, explicit consistent per-side payout, and official settlement time. Scores and unvalidated raw provider fields cannot settle a contract. Conflicting or incomplete observations remain pending. A valid settlement pays the held side without exit slippage or fees and uses the same atomic ledger transition as a close.

---

# 25. Portfolio Architecture

The portfolio layer maintains:

* bankroll
* available balance
* committed capital
* realized P&L
* unrealized P&L
* open positions
* exposure

The portfolio model should support both paper and future live accounts.

Paper and live portfolios must remain clearly separated.

Phase 6 exposes only active USD paper portfolios. Creation is idempotent by client key and produces one immutable sequence-zero snapshot. The canonical accounting equations are:

```text
current_bankroll = starting_bankroll + realized_pnl
cash_balance = current_bankroll - committed_capital
available_bankroll = cash_balance - reserved_capital
```

Phase 8 extends each snapshot with `open_position_value`, `unrealized_pnl`, `total_portfolio_value`, and a `previous_snapshot_id` chain. The complete equations are:

```text
current_bankroll = starting_bankroll + realized_pnl
cash_balance = current_bankroll - committed_capital
available_bankroll = cash_balance - reserved_capital
open_position_value = committed_capital + unrealized_pnl
total_portfolio_value = cash_balance + open_position_value
```

The initial snapshot sets current bankroll, cash, available bankroll, and total portfolio value equal to the configured starting bankroll, with reserved capital, committed capital, open-position value, realized P&L, and unrealized P&L at zero. Position sizing and risk evaluation remain read-only. An immediate entry needs no separately persisted reservation: the locked transaction moves its all-in cost, including fees, from available cash into committed capital, adds its initial marked value and unrealized P&L, and appends one `paper_entry_filled` snapshot. Starting bankroll, current bankroll, reserved capital, and realized P&L remain unchanged on entry.

Phase 9 appends `paper_position_marked`, `paper_position_reduced`, `paper_position_closed`, or `paper_position_settled` snapshots when accounting state changes. Disposal removes allocated remaining basis from committed capital, adds net proceeds to cash, and adds net proceeds minus allocated basis to realized P&L and current bankroll. Open-position value and unrealized P&L are rechecked against all current open projections under the portfolio lock.

---

# 26. Evaluation Architecture

The evaluation engine analyzes forecasting and trading performance.

Forecast evaluation may include:

* Brier score
* log loss
* calibration

Trading evaluation may include:

* total P&L
* return
* drawdown
* win rate
* average edge
* execution quality

Metrics should be segmentable by:

* sport
* market type
* model version
* strategy version
* confidence
* date range

This is required to determine whether changes improve or degrade the system.

Phase 10 persists immutable `forecast_evaluations`, one scalar home-team Bernoulli score per current canonical event/model/purpose forecast and frozen normalized final result. The versioned `binary_home_brier` policy stores exact twelve-decimal `(p-y)^2`, uses strict `p=0.5` accuracy abstention, and fingerprints result date, schedule, teams, score, forecast, model configuration, purpose, and policy. Result corrections append facts; current summaries match copied semantics back to the current normalized event so corrections and reversions never rewrite history. Operational and retrospective historical-replay samples cannot be combined.

Calibration uses a configured fixed-width reliability table with every bin present, including empty bins, plus ECE and MCE. Model comparison is paired on the exact shared event and outcome-fingerprint intersection; unpaired coverage remains visible and is not treated as evidence of superiority.

Paper trading performance is read-only derived state. The service takes the portfolio lock used by execution and monitoring, anchors to the latest immutable snapshot sequence, validates the complete snapshot chain, position projections, opening lineage, entry-edge economics, and monitoring-event continuity, then calculates marked-equity P&L, realized/unrealized returns, completed-position win rate, entry-edge means, terminal return, strategy-lineage groups, and snapshot-sampled drawdown. It does not duplicate financial truth in an aggregate table. Confidence segmentation is rejected until a real upstream confidence signal exists.

---

# 27. Data Storage

PostgreSQL is the system of record.

Potential core tables include:

```text
providers

markets

market_prices

order_book_snapshots

sports_events

teams

players

player_statuses

market_event_matches

base_forecasts

final_forecasts

evidence_items

opportunities

portfolios

portfolio_snapshots

position_size_proposals

proposed_trades

risk_decisions

trades

positions

model_versions

strategy_versions

forecast_evaluations
```

The exact schema should be defined incrementally.

Database tables should use stable internal IDs while preserving external provider IDs.

---

# 28. Event-Driven Processing

The platform should conceptually respond to events such as:

```text
MARKET_UPDATED

SPORTS_DATA_UPDATED

NEW_EVIDENCE_FOUND

FORECAST_UPDATED

OPPORTUNITY_DETECTED

TRADE_PROPOSED

TRADE_APPROVED

TRADE_EXECUTED

POSITION_UPDATED

MARKET_RESOLVED
```

The MVP does not require a dedicated distributed event-bus system.

Initially, these workflows may be coordinated using Python services and background tasks.

The architecture should avoid tightly coupling components so a message queue could be introduced later.

---

# 29. API Layer

FastAPI should expose APIs for the frontend.

Potential routes include:

```text
GET /markets

GET /markets/{id}

GET /events

GET /forecasts

GET /forecasts/{id}

GET /opportunities

GET /opportunities/{id}

GET /markets/{id}/opportunities

GET /portfolios

GET /portfolios/{id}

GET /portfolios/{id}/snapshots

GET /position-size-proposals

GET /position-size-proposals/{id}

GET /positions

GET /positions/{id}

GET /trades

GET /trades/{id}

GET /portfolio

POST /forecast-evaluations/run

GET /forecast-evaluations

GET /forecast-performance

GET /forecast-performance/compare

GET /portfolios/{portfolio_id}/performance
```

Future mutation routes may include:

```text
POST /approvals/{id}/approve

POST /approvals/{id}/reject
```

Current local mutation routes include bounded forecasting, matching, opportunity, position-sizing, and risk runs; idempotent paper-portfolio creation; and `POST /paper-execution/run?risk_decision_id=...`. The execution route can create only local paper trades, positions, and portfolio snapshots from a single-use automatic authorization. It has no provider call, account credential, approval action, or live-order capability.

API design should use typed request and response schemas.

The Phase 11 dashboard consumes only the current `GET` routes. It selects the active portfolio deterministically, then scopes position, trade, event, and performance reads to that portfolio. Research sections remain available without a portfolio. List caps are disclosed because the current bare-array APIs do not expose total counts or cursors.

---

# 30. Real-Time Updates

The dashboard should eventually receive real-time updates.

Potential technologies:

* WebSockets
* Server-Sent Events

Real-time updates may include:

* market price changes
* opportunity detection
* trade execution
* P&L changes
* approval requests

Polling is acceptable during early development.

---

# 31. Configuration

Configuration should use environment variables and typed application settings.

Example:

```text
TRADING_MODE=paper

DATABASE_URL=

PREDICTION_MARKET_PROVIDER=

SPORTS_DATA_PROVIDER=

MAX_AUTO_EXPOSURE=

HIGH_CONFIDENCE_THRESHOLD=
```

Secrets must not be committed to source control.

A `.env.example` file should document required environment variables.

---

# 32. Model and Strategy Versioning

Every forecast should reference a model version.

Every trading decision should reference a strategy version.

Example:

```text
base_model_version:
nba_elo_v1

forecast_strategy_version:
evidence_adjustment_v1

position_sizing_version:
rules_v1

risk_policy_version:
risk_v1
```

This allows historical performance to remain interpretable after the system changes.

---

# 33. Logging and Observability

The backend should use structured logging.

Important logged events include:

* provider failures
* market ingestion
* event matching
* forecast generation
* evidence processing
* opportunity detection
* risk decisions
* trade execution
* position changes

Logs must not expose secrets.

Important business decisions should be stored in the database rather than existing only in application logs.

---

# 34. Error Handling

External provider failures should not crash the entire system.

The application should handle:

* API timeouts
* rate limits
* malformed responses
* missing data
* stale data
* temporary provider outages

Failures should be logged.

The system should avoid making trades when required data is incomplete or stale.

Conservative failure behavior is preferred.

---

# 35. Testing Architecture

Testing should include:

## Unit Tests

For:

* probability calculations
* opportunity calculations
* position sizing
* P&L
* risk logic

## Integration Tests

For:

* provider adapters
* database interactions
* market normalization
* paper execution

## End-to-End Tests

Eventually:

```text
Market discovered
    ↓
Event matched
    ↓
Forecast generated
    ↓
Opportunity detected
    ↓
Paper trade executed
    ↓
Position resolved
    ↓
P&L calculated
```

Tests must never execute live trades.

---

# 36. Trading Safety Boundary

Real-money trading must remain isolated behind an explicit execution provider.

The architecture must make this impossible:

```text
LLM
 ↓
Exchange API
```

The required path is:

```text
LLM Analysis
 ↓
Validated Forecast
 ↓
Opportunity Engine
 ↓
Position Sizing
 ↓
Risk Engine
 ↓
Approved Trade
 ↓
Execution Engine
 ↓
Exchange API
```

Paper mode must remain the default.

---

# 37. Codex-Friendly Architecture

The repository should be organized so Codex can work on bounded areas without modifying unrelated systems.

Examples:

```text
Implement market ingestion.

Implement NBA event normalization.

Implement Elo forecasting.

Implement paper execution.

Implement risk rules.
```

Each feature should have:

* clear module boundaries
* typed interfaces
* tests
* relevant documentation

Codex should avoid large cross-cutting refactors unless they are explicitly justified.

---

# 38. Initial MVP Architecture

The first functional architecture should be significantly simpler than the long-term design.

Initial backend:

```text
FastAPI Application
        │
        ├── Prediction Market Provider
        │
        ├── NBA and MLB Data Providers
        │
        ├── Event Matcher
        │
        ├── Base Forecast Model
        │
        ├── Opportunity Engine
        │
        ├── Risk Engine
        │
        ├── Paper Execution Engine
        │
        └── PostgreSQL
```

Initial frontend:

```text
Next.js Dashboard
        │
        ├── Server-only API Adapter
        │       └── Partial Read States
        │
        ├── Markets
        ├── Forecasts
        ├── Opportunities
        ├── Positions
        ├── Paper Activity
        └── Performance + Calibration
```

AI evidence processing should be introduced after the deterministic pipeline works.

---

# 39. Recommended Implementation Order

The architecture should be implemented in approximately this order:

```text
1. Project bootstrap

2. Database

3. Prediction-market provider interface

4. First prediction-market adapter

5. Market normalization

6. NBA sports-data provider

7. NBA event normalization

8. Market-to-event matching

9. Base forecasting model

10. Opportunity engine

11. Portfolio model

12. Position sizing

13. Risk engine

14. Paper execution

15. Position management

16. Evaluation

17. Basic dashboard

18. Research pipeline

19. AI evidence analysis

20. Final probability adjustment

21. Real-time updates

22. Live trading
```

Live trading must remain last.

---

# 40. Architectural Principle

The most important architectural separation is:

```text
FORECASTING

What is likely to happen?

        ↓

OPPORTUNITY DETECTION

Is the market mispriced?

        ↓

POSITION SIZING

How much should we risk?

        ↓

RISK MANAGEMENT

Are we allowed to take this risk?

        ↓

EXECUTION

How do we place the trade?
```

These concerns should remain separate.

A change to one should not require rewriting the others.

This separation is essential for safely experimenting with forecasting and trading strategies.
