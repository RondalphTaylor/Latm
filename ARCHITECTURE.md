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

# 10. NBA Event Normalization

NBA events should be represented independently of the sports data provider.

A normalized NBA game should contain:

* internal event ID
* external provider IDs
* home team
* away team
* scheduled start time
* venue
* game status
* final score when available

Forecasting code should operate against normalized events.

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

The initial deterministic matcher uses exact, boundary-aware NBA aliases and event-time proximity. A `MATCHED` result requires the configured minimum confidence and sufficient separation from the runner-up; otherwise plausible results remain `AMBIGUOUS`. Matching scores are inspectible heuristics, not calibrated forecast probabilities.

Match attempts are append-oriented and keyed by a matcher version plus semantic input fingerprint. Unchanged reruns are idempotent, while changed market text, schedules, candidate events, policies, or matcher versions preserve a new audit record. The broad market-ingestion `is_nba` flag is discovery input only and never establishes match or trading eligibility by itself.

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

An `AUTO_APPROVE` result is risk authorization evidence only. It does not reserve capital or mutate portfolio accounting, and there is no human-approval action or execution route in Phase 7. The Phase 8 execution boundary must revalidate the risk record, latest price, forecast, match, opportunity, proposal, portfolio snapshot, duplicate intent, and available bankroll atomically before simulated execution. Adjusted edge and calibrated confidence are unavailable; liquidity and existing executed-position exposure are explicitly not evaluated yet.

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

The execution engine receives only approved trades.

Execution modes:

```text
paper
live
```

Default:

```text
paper
```

The execution interface should be common across modes.

Conceptually:

```python
from typing import Protocol


class ExecutionProvider(Protocol):
    async def execute(
        self,
        trade: "ApprovedTrade",
    ) -> "ExecutionResult":
        ...
```

Implementations may include:

```text
PaperExecutionProvider

LivePredictionMarketExecutionProvider
```

The live implementation is future work.

---

# 22. Paper Trading Architecture

Paper trading should simulate real execution as accurately as practical.

The paper execution engine may consider:

* current market price
* order-book depth
* liquidity
* slippage
* fees
* partial fills

The initial implementation may begin simpler and increase realism incrementally.

Paper trades should produce the same internal trade and position objects used by future live execution.

This ensures the rest of the application does not need separate paper and live logic.

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

The position manager should support future actions:

* hold
* increase
* reduce
* close

Position decisions should pass through the same opportunity and risk logic as initial entries.

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

The system should record exit reasons.

Example:

```text
EDGE_DISAPPEARED

FORECAST_REVERSED

RISK_REDUCTION

MARKET_RESOLVED
```

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

The initial snapshot sets current bankroll, cash, and available bankroll equal to the configured starting bankroll, with reserved capital, committed capital, and realized P&L at zero. Position sizing reads this snapshot but never appends another snapshot or changes any balance. Phase 7 risk evaluation also leaves balances untouched; Phase 8 paper execution owns reservation and balance transitions.

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

evaluation_results
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

GET /trades

GET /portfolio

GET /evaluation
```

Future mutation routes may include:

```text
POST /approvals/{id}/approve

POST /approvals/{id}/reject
```

The current local mutations are `POST /opportunities/run`, idempotent paper-only `POST /portfolios`, and bounded `POST /position-sizing/run`. They write audit records but cannot approve risk, reserve capital, create a trade, or execute.

API design should use typed request and response schemas.

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
        ├── NBA Data Provider
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
        ├── Markets
        ├── Forecasts
        ├── Opportunities
        ├── Positions
        └── Performance
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
