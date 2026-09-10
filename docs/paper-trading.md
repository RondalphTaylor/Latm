# Paper Trading Specification

Release 0.11.26 extends the implemented settlement path to explicit official scalar
results with complementary fractional payouts. Remaining quantity times held-side
payout rounds down to cents; no sports-derived payout, synthetic provider result,
live execution or NFL entry authorization is added. Exchange fees/netting are not
fully simulated. The versioned [NFL promotion policy](decisions/0023-nfl-promotion-and-fractional-paper-settlement.md)
separates immediate engineering tests from model and pilot review requirements.

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

Phase 6 establishes active USD paper portfolios with immutable sequence-zero snapshots. Phase 8 extends those snapshots with open-position value, unrealized P&L, total portfolio value, and a previous-snapshot chain. The canonical equations are:

```text
current_bankroll = starting_bankroll + realized_pnl
cash_balance = current_bankroll - committed_capital
available_bankroll = cash_balance - reserved_capital
open_position_value = committed_capital + unrealized_pnl
total_portfolio_value = cash_balance + open_position_value
```

At creation, current bankroll, cash, available bankroll, and total portfolio value equal the starting bankroll, while committed capital, reserved capital, open-position value, realized P&L, and unrealized P&L are zero. Phase 6 sizing proposals and Phase 7 risk decisions do not reserve capital or append balance snapshots.

For a Phase 8 immediate entry with all-in cost `C` and initial marked value `V`, one locked transaction increases committed capital by `C`, reduces cash and available bankroll by `C`, increases open-position value by `V`, and increases unrealized P&L by `V - C`. Starting bankroll, current bankroll, reserved capital, and realized P&L remain unchanged. The transaction appends exactly one `paper_entry_filled` snapshot linked to the previous snapshot.

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

The implemented Phase 8 lifecycle ends at the initial `OPEN` position. It consumes a still-valid automatic risk authorization once, revalidates it atomically, and records either a filled entry with its position and balance snapshot or a rejected terminal attempt with no financial effects. Monitoring, increases, exits, settlement, and realized-P&L transitions begin in Phase 9.

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

Phase 7 revalidates those records and stores immutable `risk_decisions`. An automatic approval is a short-lived risk authorization, not a paper trade: it does not reserve capital, append a balance snapshot, or authorize a stale future execution. Human-escalated decisions remain pending evidence because no approval-action workflow exists.

Phase 8 accepts one explicit risk-decision ID and consumes only the latest, unexpired `AUTO_APPROVE` whose complete input fingerprint reproduces under the current risk and sizing policies. Each risk decision has at most one terminal execution record, so a retry returns the same result rather than spending twice. The service locks the portfolio, market and event source parents, and risk decision in a fixed order, captures wall-clock time after any waits, and revalidates the latest portfolio snapshot, opportunity semantics, direct directional price, match, forecast, market, event, available balance, prior execution, and existing open position before making any financial change.

---

# 10. Approved Trade

Only approved trades may reach the paper execution engine.

An approved trade should preserve:

* proposal details
* risk decision
* risk-policy version
* approval method
* approval timestamp

Approval methods may eventually include:

```text
AUTO_APPROVED
```

or:

```text
HUMAN_APPROVED
```

Phase 8 implements `AUTO_APPROVED` entries only. `REJECT` and `REQUIRE_HUMAN_APPROVAL` risk decisions cannot enter execution, and no human-approval action is available.

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

Phase 8 supports:

```text
FILLED
```

and:

```text
REJECTED
```

only.

Partial fills should be added when order-book simulation is introduced.

Both results are immutable terminal trade records. A `FILLED` result atomically creates a position and next portfolio snapshot. A `REJECTED` result preserves the failed execution checks but has no fill economics, position, reservation, or balance transition.

---

# 12. MVP Fill Model

The first paper-trading implementation assumes immediate full execution.

However, the executed price should not automatically equal the ideal displayed midpoint.

The MVP should use a conservative configurable execution assumption.

The implemented formula is:

```text
execution_price =
ceil_0.000001(direct_directional_ask + PAPER_SLIPPAGE_BPS / 10000)
```

`PAPER_SLIPPAGE_BPS` is an absolute binary-price-point adjustment, not a relative percentage. For example, 25 bps adds `0.0025` to the direct ask. Execution is rejected if the result reaches or exceeds `1.000000`.

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

Paper execution uses configurable, versioned slippage.

Conceptually:

```text
PAPER_SLIPPAGE_BPS
```

or another clearly documented representation.

Example with 50 absolute bps:

```text
Displayed Price:
0.42

Simulated Execution Price:
0.425
```

The configured value, absolute-price interpretation, six-decimal upward rounding, per-contract adjustment, and resulting cent-rounded slippage cost are recorded with the trade and execution-policy fingerprint.

---

# 15. Fees

Paper trading should account for known platform fees where applicable.

If provider fees are unknown or not yet implemented, the system should:

* document that limitation
* support configurable estimated fees

A Phase 8 trade records:

* gross trade value
* estimated fees
* net cost

The provider-specific fee schedule is not modeled. `PAPER_FEE_BPS` is a flat estimated rate over simulated gross cost. Nonzero fees round up to cents:

```text
gross_cost(q) = ceil_cent(execution_price * q)
fee(q) = ceil_cent(gross_cost(q) * PAPER_FEE_BPS / 10000)
total_cost(q) = gross_cost(q) + fee(q)
```

The proposal's capital is an all-in cap, including fees. The engine selects the largest integer contract quantity whose `total_cost` fits that cap, decreasing its estimate when cent rounding would otherwise overspend. If even one contract is unaffordable, execution is rejected.

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

Phase 8 performs a stronger exact check: the selected automatic authorization must be the latest risk result, use the active policy versions, remain strictly unexpired, and reproduce when the risk engine is rerun from authoritative state after acquiring the portfolio lock. Any newer or changed price, forecast, match, opportunity, event, market, proposal, or portfolio snapshot produces a rejected execution record and requires a fresh sizing and risk cycle.

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

Phase 8 recalculates adjusted edge after slippage, fee, and cent rounding:

```text
effective_unit_cost = ceil_0.000001(total_cost / whole_contract_quantity)
adjusted_edge = model_probability - effective_unit_cost
```

The fill is rejected unless this adjusted edge still meets both the active opportunity and risk minimum. A favorable newer price still invalidates the old authorization rather than silently changing its inputs.

---

# 21. Position Creation

A filled Phase 8 trade creates one position.

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

Phase 8 supports `OPEN` only. It stores whole-contract quantity, execution price, gross cost basis, entry fees, total cost basis, initial mark basis, market value, unrealized P&L, zero realized P&L, source price, opening trade, fingerprints, and timestamps.

---

# 22. Multiple Entries

The mature system should support entering the same position multiple times.

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

Phase 8 deliberately rejects a second entry whenever the portfolio already has an open position for that market. Phase 9 preserves that gate, implements exposure reduction, and permits a separately approved new entry only after the prior position is terminal. Increases and weighted-average entry updates remain unsupported.

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

The system prevents opposing positions by allowing only one open position per portfolio and market, regardless of direction. Phase 9 adds reduction semantics but not independent opposing positions or economic netting.

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

At entry, Phase 8 uses the exact source snapshot's direct directional bid when it exists and is not above the ask. If no bid exists, it stores the direct ask with the explicit basis `directional_ask_fallback`; this fallback is a reference mark, not a claim about executable exit liquidity. Market value is rounded down to cents.

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

Phase 8 includes entry fees in total cost basis:

```text
total_cost_basis = gross_cost_basis + entry_fees
unrealized_pnl = floor_cent(quantity * mark_price) - total_cost_basis
```

Phase 9 models a distinct configurable exit fee. The position and portfolio snapshot store the same initial market value and unrealized P&L.

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

Phase 9 handles partial exits with cumulative original-basis allocation. Gross entry basis and entry fees are allocated independently, rounded down to cents, and the last disposal consumes all residual basis. This prevents the realized result from changing merely because the same total quantity was reduced in different batch sizes.

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

The deterministic V1 manager records and immediately applies paper-only:

```text
HOLD

REDUCE

CLOSE

SETTLE
```

Every semantic source set and policy identity creates at most one immutable position event. A repeated monitoring call returns that event rather than applying its action again. Future versions may also support:

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

The V1 policy requires the latest direct held-side bid, a fresh latest operational forecast from the opening model lineage, a current event match, an open market, and a pregame event. It closes when remaining model edge at the executable bid is nonpositive, reduces by the configured fraction when positive edge is below the hold threshold, and otherwise holds. A reversed forecast is an explicit close reason only when the remaining edge is also below the threshold. The exact strategy should evolve through experimentation.

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

Phase 9 settles only from an append-only normalized official provider resolution. The record must contain a terminal standard-binary result, explicit consistent YES and NO payout, provider settlement time, retrieval time, source evidence, and fingerprint. Market status, an NBA final score, or an unvalidated raw payload is not settlement authority. Closed markets without that record remain open with an explicit `market_closed_unresolved` HOLD.

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

Phase 8 `trades` are append-only terminal execution attempts linked to the exact proposal, automatic risk decision, opportunity, match, price, forecast, before/after portfolio snapshots, and sizing/risk/execution policy versions. They preserve every execution gate, direct reference ask, configured slippage and fee, whole-contract calculation, cost and mark values, fingerprints, assumptions, and failure reasons. A unique risk-decision link enforces single-use execution.

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

Phase 8 appends a snapshot only for a filled entry. It links to the prior sequence and records cash, reserved and committed capital, available bankroll, open-position value, realized and unrealized P&L, and total portfolio value. Rejected attempts append no snapshot. An immediate atomic fill creates no intermediate reservation snapshot; `reserved_capital` remains unchanged.

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

Phase 8 uses terminal `filled` and `rejected` states only. Expected gate failures—expired or superseded authorization, changed risk fingerprint, stale source, snapshot change, open-position conflict, invalid directional book, unaffordable contract, execution price at one, or inadequate adjusted edge—are persisted as rejected attempts with no financial effects. Unexpected database failures roll back rather than recording a result that might imply a completed fill.

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

Phase 8 does not implement this workflow. A `REQUIRE_HUMAN_APPROVAL` decision remains non-executable evidence; only `AUTO_APPROVE` can produce a paper execution attempt. Approval actions, pending approval state, and human-decision history remain future work.

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

The implemented entry path uses:

```text
portfolios

portfolio_snapshots

position_size_proposals

risk_decisions

trades

positions

```

Phase 9 adds the latter two records; approval history remains a later milestone:

```text
position_events

market_resolutions
```

Phase 8 `trades` still preserve filled and rejected entry attempts. Phase 9 keeps those rows immutable, turns `positions` into the current projection, and reconstructs all later HOLD, REDUCE, CLOSE, and SETTLE history from ordered immutable events and snapshots.

---

# 66. MVP Paper Trading Scope

The staged MVP ultimately should support:

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

Phases 8 and 9 complete items 1-14 for the initial immediate-fill simulator: entry, tracking, deterministic automated reduction/closing, official standard-binary settlement, realized and unrealized P&L, portfolio value, and immutable history. Human approval, live execution, increases, scalar/void settlement, and realistic order-book fills remain future work.

---

# 67. MVP Execution Assumption

Phase 8 uses:

```text
Best available price
+
Configured conservative slippage
```

For entry, the best available price is the direct directional ask. If no directional bid exists for the initial mark, the same ask is retained as an explicitly labeled fallback reference:

```text
Provider Price
+
Configured conservative slippage
```

This limitation is recorded in every affected trade and position. The simulation does not infer a complement price, midpoint, or provider fill.

---

# 68. Second Paper Trading Milestone

After the basic simulator works, add:

* maximum acceptable price
* liquidity checks
* improved fee modeling

Direct directional ask execution, bid-first initial marking, complete source revalidation, and post-cost edge checks are already present in Phase 8.

---

# 69. Third Paper Trading Milestone

Later add:

* order-book depth
* partial fills
* realistic market impact
* execution latency
* approval expiration

Risk authorization expiration is already enforced in Phase 8; a future milestone may add a separate pending human-approval timeout once that workflow exists.

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

## Implemented Phase 10 trading evaluation

Phase 10 derives performance under the same portfolio lock used by execution and monitoring. It validates the immutable snapshot chain, current position projections, filled opening lineage, entry-edge arithmetic, and monitoring-event continuity before producing results. Financial metrics are not copied into another mutable ledger.

The headline total P&L is marked equity minus starting bankroll, exactly equal to realized plus unrealized P&L. Return on starting bankroll is unannualized. Win rate counts completed positions once, includes breakevens in the denominator, and excludes open positions. Average terminal return is the arithmetic mean of terminal position P&L divided by original all-in basis; aggregate return on cost is exposed separately.

Maximum drawdown is calculated over sequence-ordered `total_portfolio_value` snapshots with exact peak and trough provenance. It is explicitly snapshot-sampled, not continuous intraperiod drawdown. Stored open marks exclude hypothetical future exit fees and slippage, and ask-fallback valuation can be non-executable; response warnings preserve those limitations.

Model and strategy comparison uses the immutable opening lineage rather than mutable current forecasts: model configuration, opportunity policy, sizing policy, risk policy, execution policy, and opening market type. Exit-policy attribution is not treated as a whole-position strategy because one position can be reduced under several monitoring versions.

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
