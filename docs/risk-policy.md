# Risk Policy Specification

## 1. Purpose

This document defines the risk-management policy for the prediction-market trading platform.

The risk system is responsible for answering:

> Given a proposed trade, is the system allowed to take this risk?

The risk engine should remain separate from:

* forecasting
* opportunity detection
* position sizing
* execution

The forecasting system estimates what is likely to happen.

The opportunity engine determines whether a market may be mispriced.

The position-sizing system proposes how much capital should be allocated.

The risk engine determines whether that proposed allocation is acceptable.

---

# 2. Core Risk Principle

No trade may execute without passing through the deterministic risk engine.

The required path is:

```text
Forecast

↓

Opportunity

↓

Position Size Proposal

↓

Risk Evaluation

↓

APPROVE
REJECT
or
REQUIRE HUMAN APPROVAL

↓

Execution
```

The system must not support:

```text
LLM

↓

Trade Execution
```

AI-generated outputs may influence forecasts and confidence, but an AI model must never bypass deterministic risk rules.

---

# 3. Initial Trading Mode

The default trading mode must always be:

```text
TRADING_MODE=paper
```

Paper trading is the default for:

* local development
* testing
* CI
* new strategy evaluation
* new model evaluation

Live trading must require explicit configuration.

The application must fail safely if trading mode is missing or invalid.

It must never silently default to live trading.

---

# 4. Risk Decision Types

Every proposed trade should receive exactly one risk decision.

Initial decisions:

```text
REJECT

AUTO_APPROVE

REQUIRE_HUMAN_APPROVAL
```

Future systems may add:

```text
DEFER

REDUCE_SIZE
```

but these are not required for the initial implementation.

---

# 5. Available Bankroll

Risk limits should primarily be calculated using the available bankroll for the relevant portfolio.

Conceptually:

```text
Available Bankroll

=

Cash Balance

-

Capital Reserved for Existing Orders

-

Other Committed Capital
```

Paper and live bankrolls must remain completely separate.

A live account must never use paper balances for risk calculations.

For the Phase 6 paper portfolio, the exact stored denominator is:

```text
current_bankroll = starting_bankroll + realized_pnl
cash_balance = current_bankroll - committed_capital
available_bankroll = cash_balance - reserved_capital
```

Position sizing reads one immutable snapshot of these values. Its advisory proposals do not reserve or commit any amount; the future risk and execution layers must revalidate the source snapshot before changing portfolio state.

---

# 6. Proposed Exposure

Each trade should calculate its proposed exposure as a percentage of the available bankroll.

Conceptually:

```text
Proposed Exposure %

=

Proposed Capital at Risk
/
Available Bankroll
```

Example:

```text
Available bankroll:
$100

Proposed position:
$8

Proposed exposure:
8%
```

This percentage should be stored with every proposed trade.

---

# 7. Initial Exposure Escalation Rules

The initial conceptual risk thresholds are:

## Below 10% Exposure

A trade may be automatically approved if all other risk checks pass.

Example:

```text
Exposure:
7%

Other risk checks:
PASS

Decision:
AUTO_APPROVE
```

---

## Between 10% and 40% Exposure

A trade may be automatically approved only when confidence is sufficiently high and all other risk checks pass.

Example:

```text
Exposure:
18%

Confidence:
HIGH

Liquidity:
SUFFICIENT

Other checks:
PASS

Decision:
AUTO_APPROVE
```

If confidence is not sufficiently high:

```text
Decision:
REQUIRE_HUMAN_APPROVAL
```

During early development, before confidence is properly calibrated, this range should be handled conservatively.

The initial implementation may require human approval for this range until the confidence system is validated.

---

## Above 40% Exposure

A trade must require explicit human approval.

Example:

```text
Exposure:
44%

Decision:
REQUIRE_HUMAN_APPROVAL
```

The system must never automatically approve a trade above this threshold under the initial policy.

---

# 8. Configurable Thresholds

Exposure thresholds must not be hard-coded throughout the application.

They should be configurable.

Conceptual settings:

```text
AUTO_APPROVE_EXPOSURE_MAX=0.10

HIGH_CONFIDENCE_AUTO_APPROVE_MAX=0.40
```

The exact configuration format may evolve.

Changing thresholds should create or reference a new risk-policy version.

---

# 9. Important Interpretation of the 40% Threshold

The 40% threshold is an escalation threshold.

It should not be interpreted as:

> The system believes risking 40% of bankroll on one prediction is normally appropriate.

Position sizing and risk escalation are different.

The position-sizing engine should generally propose substantially smaller positions.

The risk engine exists as an additional safeguard.

A 40% proposed position should be considered exceptional.

---

# 10. Initial Position-Size Expectations

The first position-sizing model should generally produce conservative allocations.

Conceptually:

```text
Weak or uncertain opportunity:
0%

Small qualifying opportunity:
1%-3%

Strong opportunity:
3%-8%

Very strong opportunity:
8%-15%
```

These ranges are conceptual and should remain configurable.

The system should not intentionally target 40% positions during normal operation.

The implemented Phase 6 `raw_edge_bands` V1 makes the conceptual policy exact and more conservative:

```text
Raw edge below 0.08
→ no proposal

Raw edge 0.08 to below 0.12
→ target 2% of available bankroll

Raw edge 0.12 to below 0.18
→ target 5% of available bankroll

Raw edge 0.18 or greater
→ target 8% of available bankroll
```

Capital is floored to cents and actual exposure is recomputed from the floored amount. The configured maximum is 8% and configuration validation requires it to remain strictly below the Phase 7 10% escalation boundary. Confidence is not inferred; it is recorded as unavailable. These allocations have no approval authority.

---

# 11. Minimum Edge Requirement

A trade should not be approved when the estimated edge is below the configured minimum threshold.

Conceptually:

```text
Adjusted Edge
<
Minimum Required Edge

↓

REJECT
```

The system should distinguish:

```text
Raw Edge
```

from:

```text
Adjusted Edge
```

Adjusted edge may account for:

* fees
* slippage
* uncertainty
* liquidity
* other trading costs

Risk decisions should eventually rely primarily on adjusted edge.

---

# 12. Confidence Requirement

Confidence should influence trade eligibility.

Conceptually:

```text
LOW confidence
→ usually reject

MEDIUM confidence
→ smaller positions

HIGH confidence
→ may permit larger positions
```

Confidence must not override hard exposure limits.

Example:

```text
Confidence:
99%

Exposure:
60%

Initial Policy Decision:
REQUIRE_HUMAN_APPROVAL
```

Not:

```text
YOLO
```

---

# 13. Confidence Calibration

Before confidence scores have sufficient historical calibration, the risk engine should treat them conservatively.

A model stating:

```text
Confidence:
0.95
```

does not automatically mean the model has historically been correct 95% of the time.

The risk engine should eventually consider:

* stated confidence
* historical calibration
* model version
* sample size

Poorly calibrated models should receive reduced risk allowances.

---

# 14. Forecast Uncertainty

Wide forecast uncertainty should reduce risk tolerance.

Example:

```text
Final Probability:
62%

Range:
59%-65%
```

may be more actionable than:

```text
Final Probability:
62%

Range:
43%-76%
```

even though the central estimate is identical.

The system may:

* reduce position size
* require approval
* reject the trade

when uncertainty is excessive.

---

# 15. Market-to-Event Match Risk

Trades require a sufficiently confident market-to-event match.

Example:

```text
Market:
Will New York beat Boston tonight?

Matched Event:
Knicks vs Celtics

Match Confidence:
0.99
```

This may be eligible.

Example:

```text
Match Confidence:
0.61
```

should not be automatically traded.

Ambiguous or unmatched markets should be:

```text
REJECT
```

or excluded before reaching position sizing.

---

# 16. Market Status Checks

Before approving a trade, the system should confirm:

* the market is open
* the market has not already resolved
* the underlying event has not already started when the strategy forbids late entry
* the market has valid pricing
* the market is not suspended

Invalid market state should result in:

```text
REJECT
```

---

# 17. Data Freshness

The risk engine should reject or block automatic execution when required data is stale.

Potential data includes:

* market price
* order book
* sports data
* forecast
* injury information

Each data type may eventually have its own staleness threshold.

Example:

```text
Forecast generated:
3 hours ago

Major injury update:
20 minutes ago

Forecast not updated

↓

REJECT
```

or:

```text
REQUIRE FORECAST REFRESH
```

before a trade may continue.

---

# 18. Liquidity Risk

A forecast can be correct while the trade is still bad because the market is too illiquid.

Liquidity checks may consider:

* order-book depth
* bid-ask spread
* recent volume
* estimated price impact
* expected fill percentage

Poor liquidity may result in:

* smaller position
* human approval
* rejection

The risk engine should not assume that the displayed market price is available for the entire proposed order.

---

# 19. Slippage Risk

Expected slippage should reduce estimated edge.

Example:

```text
Raw Edge:
10%

Expected Slippage:
3%

Fees:
1%

Adjusted Edge:
6%
```

If adjusted edge falls below the required threshold, the trade should be rejected.

---

# 20. Fee Risk

Platform fees should be included where applicable.

The system should not treat a trade as advantageous if fees eliminate expected value.

Fee calculations should be provider-specific but converted into a common internal representation.

---

# 21. Existing Position Risk

Before approving a new trade, the system should inspect existing exposure.

Example:

```text
Existing Knicks YES exposure:
8%

New proposed Knicks YES exposure:
7%
```

The risk engine should evaluate total resulting exposure:

```text
15%
```

not only the new:

```text
7%
```

Position limits should consider aggregate exposure to the same underlying outcome.

---

# 22. Duplicate Trade Prevention

The system should prevent accidental repeated execution of the same trade.

Examples include:

* retry after network timeout
* duplicate background task
* repeated opportunity processing

Trades should use idempotency or equivalent safeguards where appropriate.

The risk engine and execution engine should both support duplicate protection.

---

# 23. Correlated Exposure

The system should eventually identify correlated positions.

Example:

```text
Knicks win tonight

Knicks cover alternate market

Knicks advance in tournament
```

These may represent overlapping risk.

The system should not treat them as completely independent.

Other examples:

```text
Celtics win championship

Celtics win Eastern Conference
```

Correlation analysis does not need to be sophisticated in the MVP.

Initial implementations may group positions by:

* underlying game
* team
* tournament
* shared event

---

# 24. Same-Event Exposure

Positions tied to the same underlying sports event should be grouped.

The system should calculate:

```text
Total Event Exposure
```

A new trade may be rejected or reduced when total exposure to one event becomes excessive.

This rule should exist even when individual contracts appear different.

---

# 25. Team-Level Exposure

Future risk logic may track exposure to the same team across multiple markets.

Example:

```text
Knicks game outcome

Knicks playoff qualification

Knicks championship
```

These positions may share underlying risk factors.

Team-level exposure limits may be introduced after multi-market support exists.

---

# 26. Portfolio Exposure

The system should track:

* total capital committed
* total open exposure
* available capital
* event-level exposure
* market-level exposure

A trade may be rejected even when its individual position size is reasonable if overall portfolio exposure is already excessive.

---

# 27. Maximum Portfolio Utilization

The system should eventually define a maximum percentage of bankroll that may be simultaneously committed.

Conceptual example:

```text
MAX_TOTAL_EXPOSURE=0.60
```

This value is not yet finalized.

Until sufficient strategy data exists, conservative utilization is preferred.

The configuration should support changing this limit.

---

# 28. Daily Risk Limit

Live trading should eventually include a limit on newly deployed capital per day.

Initial conceptual live limit:

```text
$10 per day
```

This should be configurable.

The daily limit may later be expressed as:

* fixed dollars
* percentage of bankroll
* both

The stricter applicable limit should win.

---

# 29. Daily Loss Limit

The system should eventually support a maximum acceptable realized loss per day.

Example conceptually:

```text
DAILY_LOSS_LIMIT
```

When reached:

```text
New Automatic Trading
→ DISABLED
```

Existing positions may still be managed or reduced.

The system should not attempt to "win it back" by increasing risk after losses.

---

# 30. Drawdown Protection

The portfolio should track drawdown from its historical peak.

Conceptually:

```text
Peak Bankroll:
$1,000

Current Bankroll:
$850

Drawdown:
15%
```

Risk limits may become stricter as drawdown increases.

Example future policy:

```text
Small drawdown
→ normal sizing

Moderate drawdown
→ reduced sizing

Large drawdown
→ automatic trading paused
```

Exact thresholds should be determined through experimentation.

---

# 31. Losing Streak Behavior

The system should not automatically increase position sizes after consecutive losses.

A Martingale-style strategy is explicitly not part of the default risk policy.

Position size should be driven by:

* opportunity quality
* bankroll
* calibration
* portfolio risk

not an attempt to recover prior losses.

---

# 32. Winning Streak Behavior

The system should not dramatically increase risk simply because recent trades were profitable.

A short winning streak does not prove that the strategy has improved.

Capital scaling should depend on:

* sample size
* long-term performance
* drawdown
* calibration
* execution quality

not recent vibes.

---

# 33. Model Performance Risk

The system should eventually reduce risk when model performance deteriorates.

Potential indicators include:

* worsening Brier score
* worsening calibration
* unexpected drawdown
* significant underperformance relative to baseline
* AI-adjusted model underperforming base model

Possible responses:

```text
Reduce position sizing

Disable affected strategy

Switch to shadow mode

Require human approval
```

---

# 34. Model-Version Risk

New forecasting models should not immediately receive full trading authority.

New model versions may begin in:

```text
SHADOW
```

mode.

After evaluation, they may be promoted to:

```text
PAPER_ACTIVE
```

and eventually:

```text
LIVE_ELIGIBLE
```

The same principle may apply to:

* forecasting models
* AI agents
* opportunity strategies
* position-sizing strategies

---

# 35. Strategy-Version Risk

Trading decisions should record the strategy version used.

Example:

```text
opportunity_strategy:
edge_v2

position_sizing:
rules_v3

risk_policy:
risk_v1
```

If a strategy performs poorly, its historical trades must remain distinguishable from later versions.

---

# 36. Human Approval

Human approval should be required when deterministic risk rules escalate a trade.

Approval should answer:

> Are you willing to accept this proposed risk?

The approval interface should include:

* market
* platform
* direction
* current price
* model probability
* raw edge
* adjusted edge
* confidence
* uncertainty
* proposed position
* bankroll percentage
* existing related exposure
* major evidence
* major risks

---

# 37. Approval Actions

Initial actions:

```text
APPROVE

REJECT
```

Potential future action:

```text
APPROVE REDUCED SIZE
```

is useful but not required initially.

Approval decisions must be logged.

---

# 38. Approval Expiration

Human approvals should expire.

A previously approved trade should not execute indefinitely later if conditions change.

Approval should become invalid when:

* market price moves materially
* forecast changes materially
* proposed position changes materially
* market closes
* configured time limit expires

The exact expiration policy should be configurable.

---

# 39. Human Approval Does Not Bypass Hard Safety Rules

A human approval should not automatically override every system safeguard.

Example:

```text
Market already closed
```

should remain:

```text
REJECT
```

even if the user had previously approved the trade.

Hard technical and validity checks should remain enforced.

---

# 40. Human Knowledge Requests

The system may eventually request information from the user separately from risk approval.

This is a distinct workflow.

Risk question:

> Do you approve risking 45% of the bankroll?

Knowledge question:

> Do you have reliable information about this event that the system has not found?

These should not be conflated.

---

# 41. Expected Value of Human Information

The system should only ask domain-specific questions when user input is expected to improve the decision.

Conceptually:

```text
Expected Forecast Improvement

×

Importance of Decision

>

Cost of Asking User
```

This does not need to be mathematically implemented in V1.

It is a product principle.

The bot should avoid annoying the user with questions about obscure subjects where the user is unlikely to have expertise.

---

# 42. User Expertise Profile

A future version may maintain a simple profile of domains where the user may have useful knowledge.

Example:

```text
NBA:
HIGH

Technology:
HIGH

NFL:
MEDIUM

Pigeon Hunting:
UNKNOWN
```

Unknown expertise should not automatically trigger questions.

The system should prefer external research.

---

# 43. Human Input as Evidence

When the user supplies factual information, it should be stored as evidence rather than silently altering the forecast.

Example:

```text
source_type:
human_input
```

The evidence should include:

* claim
* timestamp
* user-provided source if available
* reliability classification

This keeps forecasting auditable.

---

# 44. Paper Trading Risk

Paper trading should use the same risk pipeline as future live trading where practical.

This allows the system to evaluate:

* proposed sizing
* risk escalation
* portfolio exposure
* drawdowns

Paper trading should not become an unrestricted sandbox where impossible risks are taken unless explicitly running a separate experimental strategy.

---

# 45. Paper vs Live Configuration

Risk configuration may differ between:

```text
PAPER

LIVE
```

Live limits should generally be stricter.

Example:

```text
Paper bankroll:
$1,000 simulated

Live bankroll:
$100 actual
```

Exposure percentages should be calculated independently for each portfolio.

---

# 46. Live Trading Eligibility

Before live trading is enabled, the system should require documented review of:

* paper-trading performance
* sample size
* calibration
* drawdown
* execution simulation
* provider reliability
* credential security

Live trading should not be enabled solely because the software appears functional.

---

# 47. Initial Live Capital

The initial live system should use minimal capital.

Initial conceptual limit:

```text
Maximum new capital deployed per day:
$10
```

Individual trades should generally remain small.

The exact limits should be configured before live deployment.

---

# 48. Live Capital Scaling

Increasing live capital should be a manual decision.

The system may recommend scaling based on evidence.

It must not autonomously increase account risk limits.

Scaling considerations should include:

* meaningful number of trades
* sustained profitability
* acceptable drawdown
* good calibration
* paper/live performance consistency
* stable execution

---

# 49. Kill Switch

Live trading must eventually support a kill switch.

Activating the kill switch should prevent:

* new positions
* increases to existing positions

The system may still allow:

* position reduction
* position closure
* market settlement

The kill switch should be easy to activate.

---

# 50. Automatic Trading Pause

The system should eventually be able to automatically pause new trading when serious problems occur.

Potential triggers:

* provider malfunction
* repeated execution failures
* stale market data
* corrupted sports data
* database inconsistency
* excessive drawdown
* risk-policy violation
* model health failure

Fail-safe behavior should favor stopping new trades.

---

# 51. Provider Failure

If a prediction-market API fails during execution, the system must not assume the trade succeeded.

Execution status should be explicitly reconciled.

Possible states may include:

```text
PENDING

FILLED

PARTIALLY_FILLED

FAILED

UNKNOWN
```

Unknown execution state should trigger conservative handling.

The system must avoid blindly retrying an order that may already have executed.

---

# 52. Partial Fill Risk

Future live and realistic paper execution should account for partial fills.

Risk calculations should update based on actual executed quantity.

The system should not assume the entire proposed position was filled.

---

# 53. Order Price Movement

Before execution, the system should verify that the current price remains within an acceptable range.

Example:

```text
Opportunity detected at:
42%

Price before execution:
51%
```

The original trade thesis may no longer exist.

The execution should be canceled or reevaluated.

---

# 54. Maximum Acceptable Price

Proposed trades should eventually include a maximum acceptable execution price.

For a YES trade:

```text
Buy only if price <= configured limit
```

This prevents market movement from silently destroying the expected edge.

---

# 55. Resolution Risk

Prediction-market resolution criteria must be considered before trading.

The system should verify that the forecast corresponds to the actual contract resolution.

Ambiguous or unusual resolution conditions should increase risk or prevent automatic trading.

A correct sports prediction can still lose money if the system misunderstands the contract.

---

# 56. Market Manipulation and Anomalies

Future risk systems should detect unusual market behavior.

Potential signals:

* extreme spread
* sudden price spikes
* low-liquidity price manipulation
* abnormal order-book behavior

The system should avoid interpreting every price movement as new information.

This is not required for the first MVP.

---

# 57. Risk Logging

Every risk decision should record:

* proposed trade ID
* risk-policy version
* decision
* exposure percentage
* bankroll
* confidence
* adjusted edge
* liquidity assessment
* existing exposure
* triggered rules
* timestamp

Human approvals should also record:

* approval decision
* timestamp
* user
* relevant trade snapshot

---

# 58. Risk Explainability

The system should be able to explain why a trade was rejected or escalated.

Examples:

```text
REJECTED

Reason:
Adjusted edge below required threshold
```

```text
REQUIRE HUMAN APPROVAL

Reason:
Proposed exposure is 43.2% of available bankroll
```

```text
REJECTED

Reasons:
- Event match confidence below minimum
- Forecast data is stale
```

Multiple reasons may apply.

---

# 59. Risk Policy Versioning

Every risk decision should reference a risk-policy version.

Example:

```text
risk_v1
```

Changes such as:

* new exposure thresholds
* new drawdown rules
* new liquidity checks

should create a new policy version where materially different.

---

# 60. MVP Risk Policy

The first implemented risk policy should remain simple.

Minimum checks:

```text
1. Trading mode is PAPER.

2. Market is valid and open.

3. Market-to-event match is sufficiently confident.

4. Forecast exists and is not stale.

5. Proposed trade has positive qualifying edge.

6. Portfolio has sufficient available bankroll.

7. Duplicate trade protections pass.

8. Exposure below 10%
   → AUTO_APPROVE

9. Exposure 10%-40%
   → REQUIRE_HUMAN_APPROVAL
   until confidence is properly implemented.

10. Exposure above 40%
    → REQUIRE_HUMAN_APPROVAL.
```

The initial MVP should err on the conservative side.

---

# 61. Second Risk Milestone

After confidence scoring is implemented and evaluated:

```text
Exposure below 10%
→ AUTO_APPROVE if checks pass

Exposure 10%-40%
→ AUTO_APPROVE only with sufficiently high confidence

Exposure above 40%
→ REQUIRE_HUMAN_APPROVAL
```

This matches the intended long-term escalation model.

---

# 62. Third Risk Milestone

After sufficient historical data exists, introduce:

* confidence calibration
* drawdown controls
* correlated exposure
* liquidity-aware limits
* model-health monitoring
* daily loss limits

These should be added incrementally and evaluated.

---

# 63. Risk Evaluation Order

The recommended evaluation order is:

```text
VALID MARKET?

↓

VALID EVENT MATCH?

↓

FRESH FORECAST?

↓

SUFFICIENT EDGE?

↓

SUFFICIENT LIQUIDITY?

↓

VALID POSITION SIZE?

↓

SUFFICIENT BANKROLL?

↓

PORTFOLIO LIMITS?

↓

EXPOSURE THRESHOLD?

↓

AUTO APPROVE
HUMAN APPROVAL
or
REJECT
```

Fast rejection checks should happen early where practical.

---

# 64. Core Risk Principle

The system should optimize for long-term survival.

The goal is not:

```text
Maximize profit on the next trade.
```

The goal is:

```text
Take repeated positive-expected-value opportunities

while avoiding individual mistakes
that can destroy the portfolio.
```

A forecasting model can be profitable while still being wrong frequently.

Risk management exists so that being wrong does not become catastrophic.
