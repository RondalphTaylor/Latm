# Paper Trading Specification

## 1. Purpose

This document defines the paper-trading system for the prediction-market platform.

The paper-trading system should simulate trading without using real money.

Its purpose is to answer:

> If the platform had executed these trades under realistic market conditions, how would the strategy have performed?

Paper trading should support evaluation of:

* forecasting quality
* opportunity detection
* position sizing
* risk management
* entry timing
* exit timing
* execution assumptions
* strategy profitability

The paper-trading system should use the same core trade, position, portfolio, and risk abstractions that future live trading will use where practical.

---

# 2. Core Principle

Paper trading should be:

```text
SAFE
+
AUDITABLE
+
REALISTIC ENOUGH TO BE USEFUL
```

It should not attempt to perfectly recreate a live exchange from the beginning.

However, it must avoid assumptions that create obviously unrealistic performance.

The simulator should become more realistic incrementally.

---

# 3. Default Trading Mode

The default application mode must be:

```text
TRADING_MODE=paper
```

When running in paper mode:

* no real-money order should be submitted
* no live execution endpoint should be called
* all trades should affect only the simulated portfolio
* all simulated actions should be clearly labeled as paper trades

The user interface must clearly indicate paper mode.

---

# 4. Paper Portfolio

The paper-trading system should maintain a simulated portfolio.

The portfolio should track:

* starting bankroll
* current cash balance
* reserved capital
* available bankroll
* open positions
* realized P&L
* unrealized P&L
* total portfolio value
* historical peak value
* drawdown

Phase 6 establishes the first, deliberately narrower accounting slice. It creates active USD paper portfolios with immutable sequence-zero snapshots and the following canonical equations:

```text
current_bankroll = starting_bankroll + realized_pnl
cash_balance = current_bankroll - committed_capital
available_bankroll = cash_balance - reserved_capital
```

At creation, current bankroll, cash, and available bankroll equal the starting bankroll, while committed capital, reserved capital, and realized P&L are zero. Phase 6 sizing proposals do not reserve capital or append balance snapshots. Open positions, unrealized P&L, drawdown, settlement, and balance mutations remain later paper-execution work.

Example:

```text
Starting Bankroll:
$1,000

Cash:
$720

Capital in Open Positions:
$300

Unrealized P&L:
+$20

Portfolio Value:
$1,040
```

---

# 5. Starting Bankroll

The starting paper bankroll should be configurable.

Example:

```text
PAPER_STARTING_BANKROLL=1000
```

Changing the starting bankroll should not alter historical portfolios.

A new simulated portfolio or explicit reset should be required.

---

# 6. Paper and Live Separation

Paper and live portfolios must remain completely separate.

The system must never:

* combine balances
* combine P&L
* use paper capital for live risk calculations
* present paper results as live results

Every portfolio should include an execution mode.

Example:

```text
PAPER
```

or:

```text
LIVE
```

---

# 7. Paper Trade Lifecycle

The conceptual lifecycle is:

```text
Opportunity Detected

↓

Position Size Proposed

↓

Risk Engine Evaluates

↓

Trade Approved

↓

Paper Execution Engine

↓

Fill Simulated

↓

Trade Recorded

↓

Position Created or Updated

↓

Position Monitored

↓

Position Reduced, Closed, or Resolved

↓

P&L Calculated

↓

Performance Evaluated
```

Paper trading must still use the normal risk engine.

---

# 8. Trade Direction

For binary prediction markets, the system should support both outcome directions.

Conceptually:

```text
BUY YES
```

and:

```text
BUY NO
```

The internal representation should avoid assuming all opportunities are YES trades.

Equivalent provider-specific implementations may differ.

The normalized trade model should hide those differences from strategy logic.

---

# 9. Proposed Trade

Before simulated execution, the system should create a proposed trade.

A proposed trade should include:

* portfolio ID
* market ID
* outcome
* direction
* proposed quantity
* proposed capital
* proposed exposure percentage
* reference market price
* maximum acceptable price if applicable
* forecast probability
* raw edge
* adjusted edge
* strategy version
* position-sizing version
* timestamp

The proposed trade should then pass through the risk engine.

Phase 6 stops one boundary earlier and stores `position_size_proposals`, not proposed trades. These records contain provider-neutral proposed capital and actual exposure against one exact portfolio snapshot. They remain `awaiting_risk`, contain no contract quantity, and cannot reach execution.

Phase 7 revalidates those records and stores immutable `risk_decisions`. An automatic approval is a short-lived risk authorization, not a paper trade: it does not reserve capital, append a balance snapshot, or authorize a stale future execution. Human-escalated decisions also remain pending evidence because Phase 7 has no approval-action workflow. Phase 8 owns simulated order creation, final source revalidation, reservation, fills, positions, and portfolio effects.

---

# 10. Approved Trade

Only approved trades may reach the paper execution engine.

An approved trade should preserve:

* proposal details
* risk decision
* risk-policy version
* approval method
* approval timestamp

Approval methods may include:

```text
AUTO_APPROVED
```

or:

```text
HUMAN_APPROVED
```

---

# 11. Execution Result

Paper execution should create an execution result.

Possible statuses:

```text
FILLED

PARTIALLY_FILLED

REJECTED

FAILED
```

The earliest MVP may support:

```text
FILLED
```

and:

```text
REJECTED
```

only.

Partial fills should be added when order-book simulation is introduced.

---

# 12. MVP Fill Model

The first paper-trading implementation may assume immediate execution.

However, the executed price should not automatically equal the ideal displayed midpoint.

The MVP should use a conservative configurable execution assumption.

Possible initial approach:

```text
Execution Price
=
Current Best Available Price
+
Configured Slippage
```

for purchases.

The exact behavior depends on available provider data.

---

# 13. Market Price Selection

The simulator should prefer executable market prices where available.

Priority may be:

```text
Best Ask for Buying

Best Bid for Selling
```

rather than:

```text
Displayed Midpoint
```

Using midpoint pricing for every trade may create unrealistic simulated performance.

If only a single market price is available, the simulator may use it with an explicit execution assumption.

---

# 14. Slippage

Paper execution should support configurable slippage.

Conceptually:

```text
PAPER_SLIPPAGE_BPS
```

or another clearly documented representation.

Example:

```text
Displayed Price:
0.42

Simulated Execution Price:
0.425
```

Slippage assumptions should be recorded with the trade.

---

# 15. Fees

Paper trading should account for known platform fees where applicable.

If provider fees are unknown or not yet implemented, the system should:

* document that limitation
* support configurable estimated fees

A trade should record:

* gross trade value
* estimated fees
* net cost

---

# 16. Order-Book Simulation

A later paper-trading milestone should use order-book data.

Example:

```text
ASKS

$0.42: 10 contracts
$0.43: 20 contracts
$0.44: 50 contracts
```

A simulated order for 40 contracts should not assume all 40 execute at:

```text
$0.42
```

Instead:

```text
10 @ $0.42

20 @ $0.43

10 @ $0.44
```

This produces a volume-weighted average execution price.

---

# 17. Partial Fills

When realistic order-book simulation is implemented, paper trading should support partial fills.

Example:

```text
Requested:
100 contracts

Available within maximum acceptable price:
65 contracts

Result:
PARTIALLY_FILLED
```

The portfolio should reflect only the executed quantity.

---

# 18. Maximum Acceptable Price

Trade proposals should eventually include a maximum acceptable price.

Example:

```text
Bot Probability:
0.62

Maximum Acceptable YES Price:
0.49
```

If available liquidity pushes the average execution price above the limit, the simulator should:

* partially fill within the limit
* or reject the trade

depending on strategy configuration.

---

# 19. Stale Price Protection

A paper trade should not execute using arbitrarily old price data.

Before simulated execution, the system should check the timestamp of the market price or order book.

If data is too stale:

```text
EXECUTION_BLOCKED
```

The opportunity should be reevaluated using fresh data.

---

# 20. Price Revalidation

Before execution, the opportunity should be revalidated.

Example:

```text
Opportunity detected:

Market price:
0.42

Bot probability:
0.58
```

Later:

```text
Execution price:
0.54
```

The original edge may no longer exist.

The simulator should not blindly execute the original trade.

The system should recalculate the adjusted edge before execution where practical.

---

# 21. Position Creation

A filled trade should create or update a position.

A position should include:

* portfolio ID
* market ID
* outcome
* total quantity
* average entry price
* total cost basis
* current market price
* current estimated value
* unrealized P&L
* realized P&L
* opened timestamp
* position status

Possible statuses:

```text
OPEN

CLOSED

RESOLVED
```

---

# 22. Multiple Entries

The system should support entering the same position multiple times.

Example:

```text
First Entry:
10 contracts @ $0.40

Second Entry:
10 contracts @ $0.50
```

Average entry price:

```text
$0.45
```

The system should correctly maintain:

* quantity
* cost basis
* average price

---

# 23. Opposing Positions

The system should define how opposing trades are handled.

Example:

```text
Existing:
20 YES contracts

New trade:
10 NO contracts
```

Possible implementations include:

* treat as independent positions
* reduce equivalent exposure
* close part of the existing position

The normalized portfolio model should eventually account for economic equivalence.

For the MVP, the simplest provider-compatible representation may be used, but behavior must be explicit.

---

# 24. Position Valuation

Open positions should be marked using current market prices.

For a YES contract:

```text
Current Position Value
=
Quantity
×
Current Executable or Reference Price
```

The system should distinguish:

```text
Mark Price
```

from:

```text
Expected Exit Price
```

in more advanced simulation.

---

# 25. Unrealized P&L

Conceptually:

```text
Unrealized P&L

=

Current Position Value

-

Remaining Cost Basis
```

Fees and expected exit costs may eventually be incorporated.

The exact formula should be tested carefully.

---

# 26. Realized P&L

When a position is reduced or closed:

```text
Realized P&L

=

Exit Proceeds

-

Allocated Cost Basis

-

Fees
```

The system must handle partial exits correctly.

---

# 27. Position Monitoring

Open paper positions should be periodically reevaluated.

Inputs may include:

* current market price
* current forecast
* adjusted edge
* new evidence
* market status
* time until resolution
* portfolio risk

The position manager may recommend:

```text
HOLD

REDUCE

CLOSE
```

Future versions may also support:

```text
INCREASE
```

---

# 28. Hold Decision

The system may hold a position when:

* expected edge remains positive
* risk remains acceptable
* no superior exit condition exists

Holding should be an explicit evaluated outcome rather than simply the absence of an action where practical.

---

# 29. Early Exit

The system should support closing positions before resolution.

Potential exit reasons include:

```text
EDGE_DISAPPEARED

FORECAST_REVERSED

TAKE_PROFIT

RISK_REDUCTION

NEW_EVIDENCE

MARKET_CONDITIONS_CHANGED
```

The exact strategy should evolve through experimentation.

---

# 30. Edge-Disappearance Exit

Example:

```text
Entry:

Market:
0.42

Bot:
0.58
```

Later:

```text
Market:
0.56

Bot:
0.58
```

Most of the expected edge has disappeared.

The system may determine that capital is better deployed elsewhere.

This can justify an early exit.

---

# 31. Forecast-Reversal Exit

Example:

```text
Initial Forecast:
0.62

New Forecast:
0.45
```

The position thesis has reversed.

The system should reevaluate immediately.

Depending on market pricing and execution costs, the position may be closed.

---

# 32. Profit Taking

The system may eventually support explicit profit-taking rules.

However, profit alone should not automatically determine exits.

Example:

```text
Position up 30%
```

does not necessarily mean:

```text
SELL
```

if substantial edge remains.

Exit logic should primarily consider current expected value and risk.

---

# 33. Stop-Loss Rules

Prediction markets differ from traditional assets because a falling price may reflect genuinely new information.

Simple price-based stop losses may therefore be inappropriate.

The system should generally prefer forecast-based reevaluation.

Future strategies may still test stop-loss rules.

They should be evaluated empirically rather than assumed beneficial.

---

# 34. Market Resolution

When a market resolves, the paper-trading system should settle the position.

For a binary contract:

Correct outcome:

```text
Settlement Value:
$1 per winning contract
```

Incorrect outcome:

```text
Settlement Value:
$0
```

Provider-specific rules should be normalized.

---

# 35. Resolution Validation

The system should not settle a paper position solely based on its own sports data when the actual prediction-market contract may have distinct resolution rules.

Where practical, resolution should be based on:

```text
Official Market Resolution
```

rather than independently inferred game results.

This better reflects live trading behavior.

---

# 36. Market Cancellation

The simulator should support markets that are:

```text
CANCELED

VOIDED
```

The appropriate simulated outcome should follow provider rules.

For example:

* capital returned
* position canceled

Exact behavior should depend on the provider.

---

# 37. Position Settlement

When a market resolves:

```text
OPEN POSITION

↓

SETTLEMENT

↓

RESOLVED POSITION

↓

REALIZED P&L
```

The portfolio balance should update automatically.

Resolution details should be stored.

---

# 38. Trade History

Every paper trade should record:

* trade ID
* portfolio
* market
* direction
* requested quantity
* executed quantity
* requested price
* execution price
* fees
* slippage
* execution status
* timestamp
* associated forecast
* associated opportunity
* associated risk decision
* strategy versions

This should allow complete reconstruction of a simulated trade.

---

# 39. Position History

The system should preserve all position changes.

Possible events:

```text
POSITION_OPENED

POSITION_INCREASED

POSITION_REDUCED

POSITION_CLOSED

POSITION_RESOLVED
```

Position history should be append-oriented where practical.

---

# 40. Portfolio Snapshots

The system should periodically store portfolio snapshots.

A snapshot may include:

* timestamp
* cash
* reserved capital
* open-position value
* realized P&L
* unrealized P&L
* total portfolio value
* drawdown

Snapshots support performance charts and historical analysis.

---

# 41. Paper P&L Evaluation

Paper results should include:

```text
Gross P&L

Fees

Slippage Cost

Net P&L
```

Net P&L should be the primary profitability metric.

---

# 42. Return Metrics

Potential metrics include:

```text
Return on Starting Bankroll

Return on Average Capital Deployed

Return per Trade
```

The exact metric definitions should remain documented.

---

# 43. Maximum Drawdown

The simulator should track maximum drawdown.

Conceptually:

```text
Historical Peak Portfolio Value:
$1,200

Later Portfolio Value:
$900

Drawdown:
25%
```

Drawdown should be evaluated alongside returns.

---

# 44. Strategy Versioning

Every paper trade should reference the strategy versions responsible for the decision.

Examples:

```text
forecast_model:
nba_elo_v1

opportunity_strategy:
edge_v1

position_sizing:
rules_v1

risk_policy:
risk_v1

exit_strategy:
edge_exit_v1
```

This allows meaningful historical comparisons.

---

# 45. Historical Backtesting vs Paper Trading

The system should distinguish between:

```text
BACKTESTING
```

and:

```text
PAPER TRADING
```

Backtesting uses historical data to simulate past decisions.

Paper trading observes markets in real or near-real time and records hypothetical decisions going forward.

Both are useful.

They should not be mixed into one performance dataset without clear labels.

---

# 46. Lookahead Bias

Historical simulation must avoid using information that was not available at the simulated decision time.

Example:

A model predicting a game at 2 PM must not use:

```text
Starting lineup announced at 6 PM
```

unless the simulation explicitly represents a later forecast snapshot.

Preventing lookahead bias is essential.

---

# 47. Market Price Lookahead

Backtests should use market prices that were actually available at the simulated trade time.

Using final closing prices for earlier hypothetical trades would invalidate results.

---

# 48. Evidence Lookahead

Future AI-enhanced backtests must only expose evidence that existed before the simulated forecast timestamp.

News and injury reports should include publication times where available.

---

# 49. Simulation Modes

The paper system may eventually support different realism levels.

Example:

```text
SIMPLE

STANDARD

ORDER_BOOK
```

Conceptually:

### SIMPLE

* immediate fills
* basic configurable slippage
* estimated fees

### STANDARD

* bid/ask execution
* liquidity checks
* basic price impact

### ORDER_BOOK

* depth simulation
* partial fills
* maximum acceptable prices

The mode used should be recorded with results.

---

# 50. Conservative Assumptions

When exact execution behavior is unknown, the simulator should prefer conservative assumptions.

Examples:

* slightly worse execution price
* include estimated fees
* reject stale prices
* limit fills in illiquid markets

The simulator should not systematically favor the strategy.

---

# 51. Missing Order-Book Data

If order-book data is unavailable, the system may use:

* best available market price
* configurable slippage
* maximum simulated position size

The limitation should be recorded.

---

# 52. Liquidity Constraints

Paper trades should eventually be limited based on available liquidity.

Example:

```text
Displayed Edge:
20%

Available liquidity:
$3
```

The system should not simulate:

```text
$500 trade
```

at the displayed price.

Position sizing and execution should account for actual market capacity.

---

# 53. Opportunity-to-Execution Delay

The simulator may eventually model execution delay.

Example:

```text
Opportunity detected:
12:00:00

Execution attempted:
12:00:05
```

Fast-moving news markets may change significantly during this interval.

Latency simulation is not required for the MVP but may become important for news-reaction strategies.

---

# 54. News-Reaction Simulation

Future paper trading may record:

* information publication time
* information detection time
* forecast update time
* order decision time
* simulated execution time

This allows measurement of whether a news-reaction edge would realistically survive execution latency.

---

# 55. Failed Trades

Not every approved trade should necessarily execute.

Potential failure reasons:

```text
PRICE_MOVED

MARKET_CLOSED

INSUFFICIENT_LIQUIDITY

STALE_DATA

EXECUTION_ERROR
```

Failed trades should remain in history.

This helps measure execution quality.

---

# 56. Paper Approval Workflow

Paper trading should still simulate human approval requirements.

Example:

```text
Exposure:
45%

Risk Decision:
REQUIRE_HUMAN_APPROVAL
```

The paper trade should remain pending until:

```text
APPROVED
```

or:

```text
REJECTED
```

This allows testing the actual operational workflow before live trading.

---

# 57. Approval Timeout

Paper approval requests should support expiration.

Example:

```text
Approval requested:
7:00 PM

Market moves materially by:
7:05 PM
```

The previous proposal should be invalidated or reevaluated.

---

# 58. Human Rejection

When the user rejects a paper trade, the system should store the decision.

Later analysis may compare:

```text
Trades bot wanted

vs

Trades user approved

vs

Trades user rejected
```

This could reveal whether human intervention improves or worsens performance.

---

# 59. Automatic vs Human Performance

The system should eventually evaluate:

```text
Fully automatic trades

Human-approved trades

Human-rejected hypothetical trades
```

This helps determine whether requiring human judgment adds value.

---

# 60. Shadow Strategies

Alternative strategies may run in shadow paper mode.

Example:

```text
Primary Strategy:
rules_v2

Shadow Strategy:
kelly_v1
```

Both may generate hypothetical trades.

Only the primary strategy affects the main paper portfolio.

Shadow results should be stored separately.

---

# 61. Multiple Paper Portfolios

The architecture should eventually support multiple paper portfolios.

Examples:

```text
Base Model Only

AI-Adjusted Model

Conservative Sizing

Aggressive Sizing
```

This allows true side-by-side strategy comparison.

Each portfolio must remain logically isolated.

---

# 62. Experiment Isolation

Experimental strategies should not overwrite historical results from existing strategies.

A new strategy version should either:

* use a separate paper portfolio
* or be clearly version-tagged

The system should preserve historical comparability.

---

# 63. Paper Trading Dashboard

The dashboard should eventually show:

## Portfolio

* starting bankroll
* current value
* cash
* open exposure
* realized P&L
* unrealized P&L

## Active Positions

* market
* direction
* quantity
* entry price
* current price
* bot probability
* current edge
* unrealized P&L

## Trade History

* entry
* exit
* execution price
* fees
* slippage
* realized P&L

## Performance

* return
* drawdown
* win rate
* calibration
* model comparison

---

# 64. Paper Trade Detail

A trade detail page should eventually show:

```text
Why did the bot trade?

What did the market believe?

What did the model believe?

What data was used?

What was the estimated edge?

What risk decision occurred?

What execution assumptions were used?

Why was the position exited?

How much money did it make or lose?
```

This is important for both debugging and portfolio demonstration.

---

# 65. Database Models

Potential tables include:

```text
portfolios

portfolio_snapshots

proposed_trades

risk_decisions

trade_approvals

trades

positions

position_events

market_resolutions
```

The exact schema should be defined during implementation.

---

# 66. MVP Paper Trading Scope

The first paper-trading implementation should support:

```text
1. Configurable starting bankroll

2. One paper portfolio

3. Approved trade execution

4. Immediate simulated fills

5. Configurable fees

6. Configurable basic slippage

7. Position creation

8. Position tracking

9. Manual or automated closing

10. Market settlement

11. Realized P&L

12. Unrealized P&L

13. Portfolio value

14. Trade history
```

---

# 67. MVP Execution Assumption

The first MVP may use:

```text
Best available price
+
Configured conservative slippage
```

If only one price is available:

```text
Provider Price
+
Configured conservative slippage
```

This limitation should be documented.

---

# 68. Second Paper Trading Milestone

After the basic simulator works, add:

* bid/ask-aware execution
* price revalidation
* maximum acceptable price
* liquidity checks
* improved fee modeling

---

# 69. Third Paper Trading Milestone

Later add:

* order-book depth
* partial fills
* realistic market impact
* execution latency
* approval expiration

---

# 70. Fourth Paper Trading Milestone

Support side-by-side experimental portfolios.

Example:

```text
Portfolio A:
Base Forecast Only

Portfolio B:
AI-Adjusted Forecast

Portfolio C:
Alternative Position Sizing
```

This will make strategy comparisons substantially more reliable.

---

# 71. Promotion to Live Trading

Paper performance alone should not automatically enable live trading.

Before live deployment, review:

* trade sample size
* return
* maximum drawdown
* forecast calibration
* execution assumptions
* simulated vs expected real liquidity
* provider fees
* strategy stability

The biggest question should be:

> Are the assumptions that made the paper strategy profitable likely to survive contact with real execution?

---

# 72. Core Paper Trading Principle

The simulator should attempt to answer:

```text
WOULD THIS STRATEGY
HAVE ACTUALLY BEEN TRADEABLE?
```

not merely:

```text
DID THE MODEL EVENTUALLY
PREDICT THE RIGHT WINNER?
```

A useful paper-trading system must evaluate both prediction quality and execution reality.
