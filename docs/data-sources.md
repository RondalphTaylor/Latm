# Data Sources

## 1. Purpose

This document defines the initial external data sources used by the prediction-market trading platform.

The platform requires data from several distinct categories:

1. Prediction-market data
2. Sports event data
3. Historical sports data
4. Player availability and injury data
5. External research and news
6. Optional sportsbook and betting-market data

The initial implementation should prioritize:

* official or well-documented APIs
* low-cost access
* reliable structured data
* historical availability
* clear authentication
* reasonable rate limits
* provider abstraction
* ease of integration with Python

The initial provider choices should not permanently couple the platform to any one external service.

All external providers should be accessed through internal provider adapters.

---

# 2. Initial Provider Decisions

The recommended initial provider stack is:

```text
Prediction Market:
Kalshi

NBA Structured Data:
BALLDONTLIE

Secondary Prediction Market:
Polymarket US

Future Premium Sports Data:
Sportradar
```

The recommended implementation order is:

```text
Kalshi
+
BALLDONTLIE

↓

Working NBA Market Pipeline

↓

Base Forecasting

↓

Paper Trading

↓

Evaluation

↓

Polymarket US

↓

Multi-Exchange Comparison
```

---

# 3. V1 Prediction-Market Provider

The recommended first prediction-market integration is:

```text
Kalshi
```

Kalshi provides official REST and WebSocket APIs for market data and trading. It also provides separate production and demo environments with separate credentials. n and demo environments should serve different purposes in this project.

---

# 4. Kalshi Production Environment

The production API should initially be used in a read-only capacity.

Initial uses:

* market discovery
* event discovery
* current prices
* bid/ask information
* order-book depth
* volume
* liquidity
* open interest
* trade history
* historical prices
* market resolution information

The bot should not require production trading credentials during early development.

Where public endpoints are available, market ingestion should use those endpoints without unnecessary authentication.

For example, Kalshi documents public order-book retrieval without authentication. shi Demo Environment

Kalshi provides a separate demo environment using mock funds.

This environment should be used for:

* testing authentication
* testing order creation
* testing order cancellation
* testing execution adapters
* testing WebSocket authentication
* testing portfolio integration

It should not be treated as the primary source of paper-trading market behavior.

Kalshi explicitly notes that prices and market behavior in the demo environment may not reflect real markets. ``text
Kalshi Production Read-Only Data
│
▼
Our Paper Trading Simulator

````

should be the preferred approach for evaluating strategies.

The Kalshi demo environment should instead validate:

```text
Can our exchange adapter correctly behave
like a real trading client?
````

These are different problems.

---

# 6. Kalshi Market Discovery

Kalshi organizes markets using concepts including:

```text
Series

↓

Events

↓

Markets
```

An event represents a real-world occurrence and may contain one or more tradable markets.

Kalshi explicitly includes sports games as an example of an event type. pipeline should therefore begin approximately as:

```text
Fetch Events

↓

Filter Sports

↓

Identify NBA-Related Events

↓

Retrieve Markets

↓

Normalize
```

The exact NBA filtering logic should be determined after inspecting real API responses.

Possible signals may include:

* event category
* series
* event title
* participant metadata
* event occurrence time
* product metadata

The implementation should avoid relying exclusively on text matching where structured metadata is available.

---

# 7. Kalshi Normalized Market Data

Kalshi markets expose useful fields including:

* market ticker
* event ticker
* YES bid
* YES ask
* NO bid
* NO ask
* last price
* volume
* 24-hour volume
* open interest
* liquidity
* market open time
* close time
* occurrence time
* settlement information
* market rules

These fields should be normalized into internal provider-independent models. should preserve:

```text
Internal ID

+

Provider Name

+

Provider Market ID
```

so external data remains traceable.

Phase 9 normalizes settlement only from terminal standard-binary market payloads with a typed `result`, explicit `settlement_value_dollars`, and `settlement_ts`, following Kalshi's documented [market lifecycle](https://docs.kalshi.com/getting_started/market_lifecycle) and [Get Market response](https://docs.kalshi.com/api-reference/market/get-market). Each official assertion is append-only and fingerprinted. Unsupported, incomplete, or conflicting outcomes remain non-financial.

---

# 8. Kalshi Order Books

Kalshi's order-book representation requires special normalization.

The API may represent bids on both:

```text
YES
```

and:

```text
NO
```

rather than returning conventional asks directly.

Because binary contracts are complementary, an ask can be inferred from the opposing bid.

For example:

```text
YES Ask
=
1.00 - Best NO Bid
```

Kalshi documents this relationship in its order-book API guidance. adapter should handle this conversion.

Core business logic should receive a normalized representation such as:

```text
YES Best Bid

YES Best Ask

NO Best Bid

NO Best Ask

Order Book Depth
```

without needing to understand Kalshi-specific mechanics.

---

# 9. Kalshi Real-Time Data

Kalshi provides WebSocket streaming for real-time data including:

* ticker updates
* order-book changes
* trade executions
* market lifecycle updates
* user fills
* position information

WebSocket sessions require authentication during the connection handshake, including when consuming public-market channels through that session. eaming should not be required for the earliest MVP.

Recommended progression:

```text
Phase 1:
REST polling

↓

Later:
WebSocket market updates

↓

Later:
Event-driven forecasting and trading
```

REST is simpler for proving the full pipeline.

WebSockets become more valuable when the project begins testing:

* breaking-news reactions
* short-lived edges
* rapid price changes
* execution timing

---

# 10. Kalshi Historical Data

Kalshi provides historical APIs for older exchange data.

Available historical information includes:

* historical markets
* historical trades
* historical candlesticks

Candlestick intervals include:

```text
1 minute

1 hour

1 day
```

Kalshi separates older archived data from its live dataset using moving historical cutoffs. ble for:

* historical market analysis
* price-movement analysis
* strategy research
* backtesting
* evaluating how quickly markets react to information

The ingestion architecture should hide the distinction between:

```text
Live Kalshi API
```

and:

```text
Historical Kalshi API
```

from downstream analytics where practical.

---

# 11. Kalshi Rate Limits

Kalshi uses tier-based API rate limits with separate read and write budgets.

The entry-level tier is available after normal account signup, with higher tiers available through upgrades or trading activity. ot is unlikely to require high request volume.

Recommended behavior:

* cache relatively static market metadata
* avoid unnecessary repeated requests
* use WebSockets when continuous updates become necessary
* implement exponential backoff for rate-limit responses

Provider rate limiting should be handled inside the Kalshi adapter.

---

# 12. Kalshi Fees

Trading profitability calculations must account for provider fees.

Kalshi charges transaction fees based on its fee model, and some markets may use different fee structures or maker fees. must therefore avoid assuming:

```text
One universal fixed fee
```

for all markets.

The Kalshi provider adapter should eventually expose a normalized estimated transaction-cost model to the opportunity and execution systems.

For the first paper-trading version, configurable conservative estimated fees are acceptable until exact fee calculations are implemented.

---

# 13. Secondary Prediction-Market Provider

The recommended second provider is:

```text
Polymarket US
```

It is important to distinguish:

```text
International Polymarket
```

from:

```text
Polymarket US
```

The international Polymarket API currently lists the United States as a jurisdiction where users may close existing positions but may not open new positions. nitial user is based in the United States, future live integration should use Polymarket US rather than attempting to trade through the international platform.

---

# 14. Polymarket US API

Polymarket US provides separate capabilities for:

* public market data
* authenticated trading
* portfolio access
* account access

Public APIs can be used without authentication to browse:

* markets
* events
* series
* sports
* teams
* schedules
* order books
* best bid and offer
* settlement data

Authenticated APIs support trading and account functionality. lymarket US a strong candidate for the project's second prediction-market adapter.

---

# 15. Polymarket US SDKs

Polymarket US provides official:

```text
Python SDK

TypeScript SDK
```

The Python SDK supports synchronous and asynchronous usage, and the official SDKs provide typed access to API resources including markets, orders, portfolios, and WebSockets. project architecture well because:

```text
Python
→ Backend / Trading

TypeScript
→ Dashboard
```

The Python integration should be preferred for the backend.

---

# 16. Polymarket US Authentication

Public market-data access does not require authentication.

Trading and private WebSocket access require API credentials.

Polymarket US currently requires users to create an account and complete identity verification before generating trading API keys through its developer portal. et US integration should therefore remain a later milestone.

The first Polymarket US adapter may be:

```text
READ ONLY
```

before trading functionality is implemented.

---

# 17. Polymarket US Real-Time Data

Polymarket US provides WebSocket access for real-time:

* order books
* market updates
* trades
* private order updates
* position updates
* account updates

The market WebSocket can provide full order-book or lightweight price subscriptions. I currently documents a global authenticated limit of 20 REST requests per second per API key and recommends WebSockets instead of repeated polling for continuously changing market information. ture aligns with the long-term design of the bot.

---

# 18. Why Kalshi Comes Before Polymarket US

Both APIs are viable.

Kalshi is recommended first because:

1. It has a clearly documented mock-funds demo environment.
2. It exposes detailed current exchange data.
3. It exposes historical trades and candlestick data.
4. It provides REST and WebSocket interfaces.
5. It fits the initial provider-adapter architecture.
6. It allows the project to develop against a US-accessible prediction market.

Polymarket US should be added after the first provider pipeline is stable.

The goal should be:

```text
Build Provider Abstraction Correctly Once

↓

Kalshi Adapter

↓

Polymarket US Adapter
```

rather than:

```text
Build Two Exchange Integrations Simultaneously
```

---

# 19. V1 NBA Data Provider

The recommended initial NBA provider is:

```text
BALLDONTLIE
```

BALLDONTLIE provides an authenticated NBA API with historical data from 1946 through the present.

Its free tier currently includes:

* teams
* players
* games

The free tier is limited to 5 requests per minute. This is sufficient to bootstrap:

* team normalization
* historical game results
* game schedules
* Elo calculation
* basic event matching

---

# 20. BALLDONTLIE Free Tier

The initial base model requires:

```text
Teams

+

Historical Games

+

Upcoming Games
```

These are currently available on the free tier. The free tier is sufficient for:

```text
Phase 2:
NBA Data Ingestion

Phase 3:
Market-to-Event Matching

Phase 4:
Basic Elo Model
```

The 5-request-per-minute limitation should not create a serious problem during early development if data is cached and historical datasets are persisted locally.

---

# 21. BALLDONTLIE Paid Upgrade

The current ALL-STAR tier is listed at:

```text
$9.99 per month
```

and provides 60 requests per minute.

It adds access to data including:

* game player statistics
* active players
* player injuries

The GOAT tier is listed at:

```text
$39.99 per month
```

with 600 requests per minute and adds broader data including:

* season averages
* advanced statistics
* box scores
* lineups
* standings
* betting odds
* player props
* plays

These tiers can be tested through the provider's documented trial offering. hould begin on:

```text
FREE
```

and upgrade only when a specific feature requires it.

The most likely first paid requirement is:

```text
Player Injuries
```

---

# 22. Recommended NBA Data Progression

Start with:

```text
BALLDONTLIE Free

Teams

Games

Historical Results
```

Build:

```text
Elo V1
```

Then evaluate.

Next:

```text
BALLDONTLIE ALL-STAR

Player Injuries

Game Player Stats
```

Build:

```text
Player Availability Adjustments
```

Then evaluate again.

Only move to deeper data when there is evidence that the additional features may improve forecasting.

---

# 23. Premium NBA Data Candidate

A future premium provider candidate is:

```text
Sportradar
```

Sportradar describes its NBA API as a B2B REST API and states that its NBA data collection is supported by the NBA as an official source.

Its NBA API includes dozens of specialized feeds, with REST intended as the core data backbone and push feeds available for faster updates. so provides trial access through its developer marketplace. ortradar attractive later for:

* higher-quality data
* reliable player information
* live game feeds
* commercial-grade infrastructure
* faster information updates

It is probably excessive for V1.

The project should revisit Sportradar if:

```text
BALLDONTLIE Data Quality

or

Data Latency

or

Feature Availability
```

becomes a measurable bottleneck.

---

# 24. Provider Abstraction

Sports data must use an adapter.

Conceptually:

```python
class SportsDataProvider(Protocol):
    async def get_teams(self) -> list[Team]:
        ...

    async def get_games(
        self,
        start_date: date,
        end_date: date,
    ) -> list[SportsEvent]:
        ...

    async def get_game(
        self,
        game_id: str,
    ) -> SportsEvent:
        ...
```

Later capabilities may include:

```python
async def get_player_statuses(
    self,
    event_id: str,
) -> list[PlayerStatus]:
    ...
```

The core forecasting system should not know whether data came from:

```text
BALLDONTLIE

Sportradar

or

another provider
```

---

# 25. Local Data Persistence

External data that is useful for forecasting should generally be persisted locally.

Examples:

* NBA teams
* historical games
* upcoming games
* market metadata
* market prices
* trade data
* model inputs

This reduces:

* API usage
* rate-limit pressure
* provider dependency
* repeated historical downloads

It also improves reproducibility.

---

# 26. Historical NBA Dataset

The platform should create its own normalized historical NBA dataset.

Initial source:

```text
BALLDONTLIE
```

Pipeline:

```text
External Game Data

↓

Normalize

↓

PostgreSQL

↓

Forecast Training / Evaluation
```

Once historical games have been ingested, Elo calculations and backtests should operate against the local dataset rather than repeatedly querying the external provider.

---

# 27. Source Timestamps

Every external record should preserve relevant timestamps.

Examples:

```text
Source Published Time

Provider Updated Time

Retrieved Time
```

This becomes especially important for:

* injuries
* breaking news
* lineup changes
* market price snapshots

Without timestamps, realistic backtesting becomes difficult because the platform cannot determine what information was available at a specific moment.

---

# 28. External Research Sources

AI-assisted research should be added only after deterministic forecasting works.

Potential future categories include:

```text
Official NBA Sources

Official Team Sources

Reliable Sports News

Beat Reporters

Social Media

Reddit
```

Initial AI research should prioritize:

```text
Official

↓

High-Reliability Journalism

↓

Trusted Specialist Sources

↓

Social Signals
```

Social media should not automatically receive equal weight to official information.

Specific research providers and APIs should be selected during the AI evidence-pipeline phase.

---

# 29. Sportsbook Data

Traditional sportsbook prices may eventually become a useful comparison signal.

Possible future comparison:

```text
Internal Model Probability

vs

Sportsbook-Implied Probability

vs

Kalshi Probability

vs

Polymarket US Probability
```

Sportsbook prices should be treated as another market forecast.

They should not be treated as independent factual evidence.

Specific sportsbook-odds providers should be researched when this feature enters the roadmap.

---

# 30. Initial Data Architecture

The first functional pipeline should be:

```text
KALSHI
   │
   │ Market Data
   ▼
PredictionMarketProvider
   │
   ▼
Normalized Markets
   │
   ├───────────────────┐
   │                   │
   ▼                   ▼

PostgreSQL       Market-to-Event Matcher
                         ▲
                         │
                         │
BALLDONTLIE             │
   │                     │
   │ NBA Data            │
   ▼                     │
SportsDataProvider       │
   │                     │
   ▼                     │
Normalized NBA Events ───┘
```

Then:

```text
Normalized NBA Event

↓

Elo Forecast

↓

Model Probability

↓

Kalshi Market Probability

↓

Opportunity
```

This is the first complete data loop.

---

# 31. V1 Data Source Configuration

Conceptual environment variables:

```text
PREDICTION_MARKET_PROVIDER=kalshi

SPORTS_DATA_PROVIDER=balldontlie

KALSHI_ENVIRONMENT=production

BALLDONTLIE_API_KEY=

TRADING_MODE=paper
```

Production Kalshi market data may be consumed while:

```text
TRADING_MODE=paper
```

The trading mode determines execution behavior.

It should not prevent the system from observing real production market prices.

This allows realistic paper trading against live market conditions.

---

# 32. Demo Configuration

A separate configuration may eventually support:

```text
KALSHI_ENVIRONMENT=demo
```

This should be used when testing the Kalshi execution adapter itself.

Example:

```text
Testing Market Research:
Production Read-Only Data

Testing Trading Strategy:
Production Data + Internal Paper Execution

Testing Exchange Order Integration:
Kalshi Demo
```

These testing modes should remain conceptually separate.

---

# 33. Provider Failover

V1 does not require automatic provider failover.

If BALLDONTLIE is unavailable:

```text
NBA Data Status:
STALE
```

If Kalshi is unavailable:

```text
Market Data Status:
UNAVAILABLE
```

The system should stop generating new automatic trade actions that require unavailable or stale data.

It should not silently substitute invented or unrelated data.

---

# 34. Data Quality Monitoring

Each provider should eventually expose health information.

Examples:

```text
Last Successful Request

Last Successful Update

Request Error Rate

Data Freshness

Rate Limit Status
```

The dashboard may eventually show:

```text
Kalshi
HEALTHY

BALLDONTLIE
HEALTHY

Research Pipeline
DEGRADED
```

Data health should eventually be an input into the risk engine.

---

# 35. Current Provider Recommendation

The recommended V1 stack is:

```text
Prediction-Market Market Data:
Kalshi Production API

Exchange Integration Testing:
Kalshi Demo API

Paper Execution:
Internal Paper Trading Engine

NBA Historical and Schedule Data:
BALLDONTLIE Free Tier

NBA Injuries:
BALLDONTLIE ALL-STAR when needed

Future Premium NBA Data:
Sportradar

Second Prediction-Market Adapter:
Polymarket US
```

---

# 36. Why This Stack

This combination keeps the first implementation:

```text
CHEAP

+

REALISTIC

+

MODULAR
```

Kalshi provides the real prediction-market data.

BALLDONTLIE provides enough NBA data to build the first quantitative model.

The internal simulator evaluates the strategy against real market conditions.

Kalshi Demo validates future exchange execution.

Polymarket US later tests whether the provider abstraction actually works across multiple exchanges.

Sportradar remains available if higher-quality or faster sports data becomes necessary.

---

# 37. Immediate Implementation Target

Phase 1 should implement:

```text
KalshiPredictionMarketProvider
```

Initially supporting:

```text
List Markets

Get Market

Get Order Book

Normalize Market

Persist Market
```

Phase 2 should implement:

```text
BallDontLieSportsDataProvider
```

Initially supporting:

```text
Get Teams

Get Games

Get Historical Games

Normalize Events

Persist Events
```

The first end-to-end target is:

```text
Kalshi NBA Market

↓

Normalized Prediction Market

↓

Matched NBA Game

↓

Historical Team Ratings

↓

Base Win Probability

↓

Market vs Model Comparison
```

Once this works, the project has its first real forecasting loop.
