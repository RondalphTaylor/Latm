# Project Roadmap

## 1. Purpose

This roadmap breaks the prediction-market platform into incremental development phases.

The goal is to keep each phase:

* independently testable
* useful on its own
* small enough for Codex to implement and verify
* safe from premature real-money trading
* measurable through clear acceptance criteria

Each phase should be completed and validated before major work begins on later phases.

The roadmap prioritizes building the deterministic trading pipeline first.

AI-assisted forecasting should be added only after the underlying market, forecasting, paper-trading, and evaluation infrastructure works correctly.

---

# Phase 0: Project Foundation

## Goal

Create a reliable development environment and repository structure that Codex can work within safely.

## Scope

Implement:

* Python backend project
* FastAPI application
* TypeScript frontend project
* PostgreSQL
* Docker Compose
* environment configuration
* testing setup
* linting
* formatting
* type checking
* CI

## Backend

Recommended tooling may include:

* Python
* FastAPI
* Pydantic
* SQLAlchemy
* Alembic
* pytest

Exact dependencies should be chosen conservatively.

## Frontend

Recommended tooling:

* Next.js
* TypeScript

The frontend may initially contain only a basic health/status page.

## Infrastructure

Docker Compose should support local startup of:

* backend
* frontend
* PostgreSQL

## Required Configuration

Create:

```text
.env.example
```

At minimum, prepare configuration for:

```text
DATABASE_URL
TRADING_MODE=paper
```

## Safety Requirement

The application must default to:

```text
TRADING_MODE=paper
```

No live trading functionality should exist.

## Acceptance Criteria

Phase 0 is complete when:

* the backend starts successfully
* the frontend starts successfully
* PostgreSQL is accessible
* database migrations can run
* backend tests run successfully
* backend type checking passes
* frontend type checking passes
* linting passes
* Docker Compose starts the development stack
* CI runs validation on pull requests
* no secrets are committed

---

# Phase 1: Prediction-Market Ingestion

## Goal

Connect to the first prediction-market platform and ingest NBA-related markets.

## Scope

Implement:

* provider interface
* first provider adapter
* market retrieval
* normalized market models
* market persistence
* basic market API endpoints

The first platform should be chosen based on:

* API availability
* legal accessibility
* documentation quality
* sports market availability
* ease of paper-trading integration

## Core Models

Implement normalized representations for:

* PredictionMarket
* MarketOutcome
* MarketPrice
* OrderBook if available

## Database

Create initial tables for:

* providers
* markets
* market outcomes
* market prices

Provider-specific IDs should be preserved.

## Backend API

Initial routes may include:

```text
GET /markets

GET /markets/{id}
```

## Market Filtering

The system should be able to identify likely NBA-related markets.

Initial filtering may use:

* category
* league metadata
* keywords
* event metadata

## Acceptance Criteria

Phase 1 is complete when:

* the application can retrieve markets from one supported provider
* provider data is converted into normalized internal models
* markets can be stored in PostgreSQL
* markets can be retrieved through the backend API
* NBA-related markets can be filtered
* provider failures are handled gracefully
* tests exist for normalization logic
* no trading functionality exists

---

# Phase 2: NBA Data Ingestion

## Goal

Build a provider-independent NBA data layer.

## Scope

Implement ingestion for:

* teams
* scheduled games
* completed games
* scores
* game status

Optional early additions:

* standings
* team statistics

Player-level and injury data may be introduced later if the chosen provider makes them easy to access.

## Core Models

Implement:

* Team
* SportsEvent

A SportsEvent should include:

* home team
* away team
* scheduled start time
* game status
* score when available
* provider IDs

## Database

Create tables for:

* teams
* sports events

## Backend API

Potential routes:

```text
GET /events

GET /events/{id}
```

## Acceptance Criteria

Phase 2 is complete when:

* NBA teams can be retrieved
* upcoming games can be retrieved
* completed game results can be retrieved
* data is normalized
* events are stored in PostgreSQL
* duplicate events are not repeatedly created
* provider failures do not crash the application
* automated tests cover normalization

---

# Phase 3: Market-to-Event Matching

## Goal

Connect prediction-market contracts to the NBA games they represent.

## Scope

Implement an event-matching service.

Potential inputs include:

* team names
* team aliases
* market title
* market description
* event dates
* event start times
* provider metadata

## Output

Each match should include:

* market ID
* sports event ID
* match confidence
* match method
* timestamp

## Match Statuses

Possible statuses:

```text
MATCHED

AMBIGUOUS

UNMATCHED
```

## Trading Safety

Markets with ambiguous or missing event matches must not be eligible for automatic trading.

## Database

Create:

```text
market_event_matches
```

## Acceptance Criteria

Phase 3 is complete when:

* common NBA game markets can be matched to NBA events
* match confidence is calculated
* ambiguous matches are identifiable
* unmatched markets are preserved without causing errors
* aliases such as abbreviated team names are supported
* automatic trading eligibility requires a sufficiently confident match
* matching tests cover common and ambiguous cases

---

# Phase 4: Base Forecasting Model

**Implementation status:** Complete on 2026-08-01. The shipped `nba_elo` V1 uses a fixed, fingerprinted configuration, append-only forecast snapshots, matched-event operational runs, and explicitly labeled historical replay.

## Goal

Generate an independent probability estimate for NBA game outcomes.

## Initial Model

Start with an interpretable model.

Recommended first approach:

```text
Elo-style team ratings
+
Home-court adjustment
```

Possible early extensions:

* recent performance
* rest days
* back-to-back games
* offensive rating
* defensive rating

The initial goal is not to build the most accurate NBA model possible.

The goal is to establish a measurable forecasting pipeline.

## Forecast Output

Each base forecast should contain:

* event ID
* home-team win probability
* away-team win probability
* model name
* model version
* input features
* timestamp

## Database

Create:

```text
base_forecasts

model_versions
```

## Reproducibility

The same model version and same inputs should produce the same output.

## Acceptance Criteria

Phase 4 is complete when:

* the system can generate a base probability for matched NBA games
* probabilities are valid
* model versions are recorded
* relevant input features are stored
* forecasts can be reproduced
* forecasts are persisted
* tests validate probability calculations
* historical completed games can be used to evaluate predictions

---

# Phase 5: Opportunity Detection

**Implementation status:** Complete on 2026-08-11. The shipped raw-edge V1 records separate YES and NO comparisons using fresh direct asks, independent current-version Elo forecasts, configurable thresholds, conservative input gating, and append-only audit history.

## Goal

Compare internal probabilities against prediction-market prices.

## Scope

Implement:

```text
Market Probability

vs

Base Model Probability
```

The initial opportunity engine does not need AI.

## Initial Calculations

Calculate:

```text
raw_edge =
model_probability - market_probability
```

The system should support both YES and NO opportunities.

## Opportunity Status

Initial configurable states:

```text
IGNORE

WATCH

TRADE_CANDIDATE
```

Example conceptual rules:

```text
Very small edge
→ IGNORE

Moderate edge
→ WATCH

Large edge
→ TRADE_CANDIDATE
```

Exact thresholds should be configurable.

## Database

Create:

```text
opportunities
```

Store:

* market probability
* model probability
* raw edge
* direction
* status
* model version
* timestamp

## Acceptance Criteria

Phase 5 is complete when:

* forecasts can be compared to live market prices
* potential YES and NO edges can be identified
* opportunity thresholds are configurable
* opportunities are persisted
* historical opportunities can be inspected
* automated tests cover edge calculation

---

# Phase 6: Portfolio and Position Sizing

**Implementation status:** Complete on 2026-08-11. The shipped paper portfolio and raw-edge sizing V1 use immutable accounting snapshots, configurable 2%/5%/8% allocation bands, exact current-candidate revalidation, and append-only advisory proposals that cannot reserve capital or execute.

## Goal

Create a simulated portfolio and determine how much capital should be allocated to each opportunity.

## Scope

Implement:

* paper bankroll
* available balance
* committed capital
* position-sizing interface

## Initial Position Sizing

Start with a simple rules-based strategy.

Inputs may include:

* edge
* confidence placeholder
* available bankroll

Example:

```text
No meaningful edge
→ 0%

Small qualifying edge
→ small position

Larger edge
→ larger position
```

Do not implement complex Kelly Criterion sizing yet.

## Database

Potential tables:

```text
portfolios

portfolio_snapshots

proposed_trades
```

## Acceptance Criteria

Phase 6 is complete when:

* a paper portfolio can be created
* bankroll is tracked
* the system can propose a position size
* proposed exposure is represented as a percentage of bankroll
* position sizing is versioned
* sizing rules are configurable
* tests cover balance and sizing calculations

---

# Phase 7: Risk Engine

**Status:** Complete (2026-08-15)

## Goal

Deterministically approve, reject, or escalate proposed trades.

## Scope

Implement the initial risk policy.

Conceptual rules:

### Exposure below 10%

May be automatically approved if all checks pass.

### Exposure between 10% and 40%

May be automatically approved only when confidence is sufficiently high.

Until a proper confidence system exists, this range may conservatively require approval or use a placeholder deterministic rule.

### Exposure above 40%

Requires human approval.

## Additional Checks

Initial risk checks should include:

* sufficient available bankroll
* valid market-event match
* market still open
* position size limits
* trading mode
* duplicate trade prevention

## Output

Risk decisions:

```text
REJECT

AUTO_APPROVE

REQUIRE_HUMAN_APPROVAL
```

## Database

Create:

```text
risk_decisions
```

## Acceptance Criteria

Phase 7 is complete when:

* every proposed trade passes through the risk engine
* risk decisions are deterministic
* risk rules are configurable
* > 40% exposure requires human approval
* invalid or ambiguous markets are rejected
* insufficient bankroll is rejected
* risk decisions are logged
* tests cover every major rule

---

# Phase 8: Paper Trading Engine

**Implementation status:** Complete on 2026-08-17. The shipped `paper_immediate_fill` V1 consumes each still-valid automatic risk authorization at most once, reproduces the complete active risk evaluation under a portfolio lock, and atomically records a provider-free paper entry, open position, and immutable accounting snapshot.

## Goal

Execute approved trades using simulated capital.

## Scope

Implement:

* paper order execution
* trade creation
* position creation
* bankroll adjustment
* basic fees
* basic slippage

Initial execution may assume immediate fills.

More realistic order-book simulation can be added later.

The first implementation uses the exact direct directional ask plus configurable absolute binary-price-point slippage, whole-contract quantities bounded by all-in authorized capital, and a configurable flat estimated fee rounded conservatively to cents. It marks the opening position at the directional bid when available, otherwise at an explicitly labeled ask fallback. Only one open position per portfolio and market is permitted until Phase 9 defines increases, opposing entries, exits, and settlement.

## Required Flow

```text
Opportunity

↓

Position Size

↓

Proposed Trade

↓

Risk Decision

↓

Paper Execution

↓

Position
```

## Database

Create:

```text
trades

positions
```

## Acceptance Criteria

Phase 8 is complete when:

* approved trades can execute in paper mode
* rejected trades cannot execute
* trades modify the paper portfolio correctly
* positions are created correctly
* fees and basic slippage can be configured
* trades cannot accidentally invoke live APIs
* tests cover P&L and balance accounting

Phase 8 remains paper-only and provider-free. Human approval actions, live APIs, order-book depth, liquidity modeling, partial fills, exits, settlement, and recurring position monitoring are excluded.

---

# Phase 9: Position Monitoring and Exits

## Goal

Manage positions after entry.

## Scope

Periodically reevaluate:

* current market price
* current forecast
* current edge
* position P&L

Initial exit rules may include:

```text
Edge disappears

Forecast reverses

Market resolves
```

The system should support:

* HOLD
* REDUCE
* CLOSE

Increasing positions may be added later.

## Acceptance Criteria

Phase 9 is complete when:

* open positions are periodically reevaluated
* positions can be closed before resolution
* exit reasons are recorded
* realized P&L is calculated
* resolved markets settle positions
* position history remains auditable

---

# Phase 10: Evaluation Engine

## Goal

Determine whether the forecasting and trading system actually works.

## Forecast Metrics

Implement:

* Brier score
* calibration
* prediction accuracy where useful

Log loss may be added if appropriate.

## Trading Metrics

Implement:

* total P&L
* return on bankroll
* win rate
* maximum drawdown
* average entry edge
* average trade return

## Segmentation

Performance should eventually be filterable by:

* model version
* strategy version
* date
* confidence
* market type

## Acceptance Criteria

Phase 10 is complete when:

* completed predictions can be evaluated
* paper trades can be evaluated
* calibration can be inspected
* model versions can be compared
* strategy versions can be compared
* drawdown is tracked
* the system clearly shows whether it is profitable

---

# Phase 11: Basic Dashboard

## Goal

Provide a usable interface for monitoring the system.

## Pages

Initial dashboard should include:

### Markets

Display:

* market
* platform
* prices
* volume or liquidity where available

### Forecasts

Display:

* event
* market probability
* model probability
* edge

### Opportunities

Display:

* direction
* edge
* status

### Positions

Display:

* entry
* current price
* exposure
* unrealized P&L

### Performance

Display:

* bankroll
* total P&L
* return
* win rate
* basic calibration

## Mobile

The dashboard should be responsive enough for basic use on a phone.

## Acceptance Criteria

Phase 11 is complete when:

* core system state is visible in the browser
* the dashboard reads data from the backend
* paper/live mode is clearly displayed
* active positions are visible
* historical trades are visible
* basic performance is visible

---

# Phase 12: Research and Evidence Pipeline

## Goal

Retrieve information that may affect NBA forecasts.

## Initial Sources

Prioritize high-quality sources.

Examples:

* official NBA information
* team announcements
* injury reports
* reliable sports news

Social platforms should not be the first dependency.

## Scope

Implement:

```text
Research Query

↓

Source Retrieval

↓

Document Normalization

↓

Evidence Extraction
```

## Evidence Model

Each evidence item should include:

* claim
* source
* source type
* timestamp
* relevance
* reliability
* freshness
* independence group

## Deduplication

Repeated reporting of the same original fact should not count as independent evidence.

## Acceptance Criteria

Phase 12 is complete when:

* relevant external information can be retrieved
* information is converted into structured evidence
* duplicate reporting can be grouped
* evidence is persisted
* evidence is linked to an event

---

# Phase 13: AI Evidence Analysis

## Goal

Use AI to interpret external evidence without giving it direct control of trading.

## Initial Agent Roles

Potential roles:

```text
Evidence Agent

Forecast Agent

Critic Agent
```

A separate Research Agent may be introduced later.

## Required Structured Output

AI responses should include fields such as:

* evidence relevance
* reliability assessment
* direction
* estimated probability impact
* uncertainty
* reasoning summary

Outputs must be schema validated.

## Critic

The critic should evaluate:

* duplicated evidence
* unsupported assumptions
* contradictory evidence
* missing context
* excessive confidence

## Safety

AI output must not directly create an exchange order.

## Acceptance Criteria

Phase 13 is complete when:

* evidence can be passed through the AI analysis pipeline
* AI responses are structured and validated
* malformed outputs fail safely
* every AI analysis is logged
* AI analyses can be reproduced where model settings permit
* the critic can flag questionable forecasts

---

# Phase 14: Final Probability Engine

## Goal

Combine quantitative forecasts with evidence-based adjustments.

## Flow

```text
Base Probability

+

Evidence Adjustments

+

Uncertainty

↓

Final Probability
```

## Required Output

Store:

* base probability
* final probability
* lower bound
* upper bound
* confidence
* evidence used
* model versions

## Evaluation Requirement

The system must separately evaluate:

```text
Base Forecast Performance

vs

AI-Adjusted Forecast Performance
```

AI should not be assumed to improve results.

## Acceptance Criteria

Phase 14 is complete when:

* final probabilities are generated
* AI-adjusted forecasts can be compared with base forecasts
* evidence used in each forecast is auditable
* confidence and uncertainty are stored
* evaluation can determine whether AI improves forecasting

---

# Phase 15: Dynamic Position Sizing

## Goal

Use accumulated performance data to improve capital allocation.

## Inputs

Potential inputs:

* adjusted edge
* confidence
* uncertainty
* liquidity
* historical calibration
* bankroll
* existing exposure
* drawdown

## Possible Future Methods

Evaluate:

* rules-based sizing
* fractional Kelly Criterion
* capped Kelly strategies

Advanced methods should only be introduced after sufficient historical data exists.

## Acceptance Criteria

Phase 15 is complete when:

* sizing responds dynamically to opportunity quality
* calibration affects sizing
* poorly calibrated forecasts receive less capital
* sizing remains capped by risk policy
* strategy versions are comparable

---

# Phase 16: Human Approval Workflow

## Goal

Allow high-risk trades to be reviewed from the dashboard or mobile browser.

## Scope

Implement approval requests.

Actions:

```text
APPROVE

REJECT
```

Approval requests should include:

* market
* proposed direction
* proposed exposure
* market probability
* model probability
* confidence
* major evidence
* major risks

## Human Knowledge Requests

A separate workflow may later support asking the user for information.

The system should distinguish:

```text
RISK_APPROVAL

DOMAIN_INFORMATION_REQUEST
```

## Acceptance Criteria

Phase 16 is complete when:

* high-risk trades can generate approval requests
* approved trades continue through execution
* rejected trades are not executed
* approval history is stored
* requests are usable on mobile

---

# Phase 17: Real-Time Updates and Notifications

## Goal

Make the system responsive to changing information.

## Scope

Potential additions:

* WebSockets
* Server-Sent Events
* push-style dashboard notifications

Events may include:

* price changes
* new evidence
* new opportunities
* trades
* approval requests
* exits

## Acceptance Criteria

Phase 17 is complete when:

* important system changes appear without full-page refreshes
* users can receive time-sensitive trade alerts
* high-risk approval requests are surfaced quickly

---

# Phase 18: Improved Paper Execution

## Goal

Make simulation closer to actual market execution.

## Additions

Potential improvements:

* order-book depth
* partial fills
* dynamic slippage
* order expiration
* liquidity constraints

## Acceptance Criteria

Phase 18 is complete when:

* paper trading accounts for available liquidity
* unrealistic fills are reduced
* partial fills are supported where appropriate
* simulated results better approximate real execution

---

# Phase 19: Live Trading Preparation

## Goal

Prepare the system for very small real-money trading without enabling it by default.

## Requirements

Before live trading:

* legal and platform eligibility must be confirmed
* account authentication must be secure
* risk limits must be enforced
* paper performance must be reviewed
* kill switches must exist
* live and paper accounts must be isolated

## Initial Live Constraints

Potential configuration:

```text
TRADING_MODE=live

DAILY_NEW_CAPITAL_LIMIT=10
```

Exact rules should be finalized before implementation.

## Acceptance Criteria

Phase 19 is complete when:

* a live execution adapter exists
* live credentials are securely configured
* live mode requires explicit configuration
* paper mode remains default
* daily live risk is capped
* a kill switch exists
* no AI system can bypass deterministic risk controls

---

# Phase 20: Small-Scale Live Trading

## Goal

Validate whether paper-trading performance translates into real execution.

## Scope

Begin with minimal capital.

Monitor:

* real slippage
* fill quality
* fees
* latency
* strategy performance

Capital increases should not occur automatically.

## Acceptance Criteria

Phase 20 is complete when:

* real trades can be executed safely
* real and simulated execution can be compared
* discrepancies are measurable
* performance can be evaluated independently from paper results

---

# Phase 21: Additional Sports

## Goal

Expand the system beyond NBA markets.

Potential order:

```text
NFL

MLB

NHL

Soccer
```

Each sport may require:

* new data providers
* new event matching
* new forecasting models
* new evidence logic

Shared systems should remain reusable.

---

# Phase 22: Multiple Prediction Markets

## Goal

Support multiple trading venues.

Potential platforms include:

```text
Kalshi

Polymarket

Other supported venues
```

Each platform should implement the common market adapter.

## Future Features

Enable:

* cross-platform market matching
* best-price selection
* pricing discrepancy detection
* arbitrage research

---

# Phase 23: Cross-Market Strategies

## Goal

Identify opportunities created by differences across prediction markets.

Potential strategies:

* equivalent market price discrepancies
* best venue execution
* constrained arbitrage
* market disagreement signals

These strategies should be tested independently.

---

# Phase 24: Additional Domains

## Goal

Expand beyond sports.

Initial candidate:

```text
Technology
```

Potential future areas:

* economics
* business
* politics

Each domain should have its own forecasting logic.

The shared infrastructure should continue handling:

* market ingestion
* evidence
* opportunities
* risk
* execution
* evaluation

---

# Codex Task Strategy

Codex should generally be assigned one phase or one bounded portion of a phase at a time.

Avoid prompts such as:

```text
Build the entire prediction-market bot.
```

Prefer:

```text
Implement Phase 1 from ROADMAP.md.

Read:
- AGENTS.md
- ARCHITECTURE.md
- docs/product-spec.md
- ROADMAP.md

Before implementation:

1. Inspect the existing codebase.
2. Produce a concrete implementation plan.
3. Identify affected files.
4. Identify required dependencies.

Then implement the smallest complete version of Phase 1.

Do not implement future phases.

Add tests.

Run:
- tests
- linting
- type checking

At completion report:
- what was implemented
- tests run
- assumptions made
- remaining limitations
- recommended next task
```

---

# Current Immediate Target

The current project target is:

```text
Phase 9
```

Completed foundations:

```text
Phase 0

Phase 1

Phase 2

Phase 3

Phase 4

Phase 5

Phase 6

Phase 7

Phase 8
```

The project should not begin with AI agents or real trading.

The first major milestone is:

```text
REAL MARKET DATA
+
REAL NBA DATA
+
BASE FORECASTS
+
PAPER TRADES
+
MEASURABLE RESULTS
```

Once that deterministic foundation works, AI-assisted evidence analysis can be added and evaluated against the baseline.
