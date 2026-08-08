# Product Specification

## 1. Product Overview

The product is an autonomous prediction-market research and trading platform designed to identify mispriced markets by combining quantitative forecasting, external information, AI-assisted analysis, and automated risk management.

The initial version will focus on NBA prediction markets.

The system will:

* monitor supported prediction markets
* identify relevant NBA markets
* collect structured sports data
* calculate a quantitative base probability
* retrieve relevant external information
* use AI to analyze how new evidence should affect the forecast
* calculate a final probability estimate
* compare the final estimate against current market pricing
* identify potentially advantageous trades
* dynamically size positions
* paper trade automatically
* track positions and exit opportunities
* evaluate forecasting and trading performance
* maintain a complete audit trail of all decisions

The long-term goal is to expand beyond NBA markets to additional sports, additional prediction-market platforms, and eventually domains such as technology.

The product has two primary success criteria:

1. Demonstrate measurable forecasting and trading performance.
2. Serve as a technically impressive, production-style software engineering project.

---

# 2. Initial User

The initial user is the developer and operator of the platform.

The system is not initially intended to be a public consumer trading product.

The user should be able to:

* monitor bot activity
* inspect forecasts
* inspect active and historical positions
* understand why a trade was made
* approve or reject high-risk trades
* receive conversational trade notifications
* review the evidence used in forecasts
* inspect model performance
* change configurable risk parameters
* switch between paper and live trading modes when live trading is eventually implemented

---

# 3. Initial Scope

The first supported domain is NBA prediction markets.

The first version should support one prediction-market platform.

The specific platform should be implemented behind a provider adapter so additional platforms can be added later without changing core forecasting or trading logic.

V1 should focus primarily on game-outcome markets where the underlying event can be clearly mapped to an NBA game.

Example:

> Will the New York Knicks defeat the Boston Celtics on November 15?

Later versions may support additional market types such as:

* championship outcomes
* playoff qualification
* season win totals
* player awards
* player-specific outcomes
* series outcomes
* tournament outcomes

These more complex markets are not required for the first working version.

---

# 4. Core Product Workflow

The core system workflow is:

1. Discover an available prediction market.
2. Determine whether the market is supported.
3. Match the prediction market to an underlying NBA event.
4. Retrieve current prediction-market pricing.
5. Retrieve relevant structured NBA data.
6. Generate a quantitative base probability.
7. Retrieve relevant external evidence.
8. Analyze and score the evidence.
9. Adjust the forecast based on relevant evidence.
10. Produce a final probability estimate and uncertainty range.
11. Compare the final probability against the current market price.
12. Estimate the potential trading edge.
13. Apply fees, expected slippage, uncertainty, liquidity, and risk considerations.
14. Determine whether the opportunity should be ignored, watched, or traded.
15. Determine position size.
16. Pass the proposed trade through the risk engine.
17. Execute or simulate the trade depending on the configured trading mode.
18. Monitor the open position.
19. Recalculate the forecast when meaningful new information arrives.
20. Determine whether to hold, increase, reduce, or exit the position.
21. Record all decisions and outcomes.
22. Evaluate forecasting and trading performance after resolution.

---

# 5. Market Probability

Prediction-market prices should be converted into an implied probability where appropriate.

For example:

YES price:

0.42

Approximate market-implied probability:

42%

This value represents the market estimate used for comparison with the platform's internal forecast.

The system should preserve the original price and order-book information rather than storing only the converted probability.

---

# 6. Base Probability

The system should generate a quantitative base probability before applying AI-assisted evidence adjustments.

For NBA game outcomes, the initial base model may use factors such as:

* team strength
* Elo-style ratings
* home-court advantage
* recent performance
* offensive performance
* defensive performance
* schedule strength
* rest days
* back-to-back games
* travel
* known player availability
* expected starting lineups

The first version should favor interpretable and testable models over unnecessary complexity.

Every base forecast must record:

* event
* generated probability
* model name
* model version
* input data
* timestamp

The model must be reproducible given the same version and input data.

The system should support replacing or adding forecasting models later.

---

# 7. External Information

The system should eventually be capable of consuming information from sources including:

* official league sources
* official team sources
* sports data providers
* injury reports
* team announcements
* reputable sports journalists
* news organizations
* social media
* Reddit
* betting-market information
* prediction-market information
* other relevant public sources

V1 does not need to support every source.

Initial development should prioritize reliable, accessible, and low-cost or free data sources.

The architecture should allow additional information providers to be added later.

---

# 8. Evidence Processing

External information should not automatically change a probability.

Retrieved information should first be converted into structured evidence.

Each evidence item should contain information such as:

* source
* source type
* claim
* event relevance
* reliability
* freshness
* independence
* direction of impact
* estimated magnitude of impact
* timestamp

Example:

A reliable reporter announces that a star player will not play.

The evidence system may determine:

* relevance: very high
* reliability: high
* freshness: very high
* direction: negative for the player's team
* expected probability impact: meaningful

The system should attempt to avoid double-counting information.

For example, ten articles repeating the same original injury report should not be treated as ten independent pieces of evidence.

---

# 9. AI-Assisted Forecasting

AI should primarily be used to interpret information and estimate how evidence should affect an existing quantitative forecast.

The AI should not simply produce an unsupported probability based on intuition.

The preferred forecasting structure is:

Base probability

*

Evidence analysis

=

Final probability

An AI forecasting response should use a validated structured format.

A conceptual output may include:

* base probability
* final probability
* confidence
* probability range
* evidence considered
* supporting evidence
* opposing evidence
* evidence reliability
* unresolved uncertainty
* reasoning summary
* model version

The system may use multiple AI roles.

Potential roles include:

### Research Agent

Finds relevant information.

### Evidence Agent

Evaluates individual evidence items.

### Forecast Agent

Estimates how evidence affects the base probability.

### Critic Agent

Attempts to identify missing evidence, duplicated information, unsupported assumptions, contradictions, or overconfidence.

The exact agent architecture may change through experimentation.

AI agents must not directly execute prediction-market trades.

---

# 10. Final Probability

The system should produce a final probability after combining the base forecast and relevant evidence.

Example:

Base probability:

52%

New evidence:

Star player ruled out:

-6 percentage points

Opponent fatigue:

+2 percentage points

Final probability:

48%

Future versions may use more sophisticated methods than additive probability changes.

Every final forecast should include:

* base probability
* final probability
* confidence
* uncertainty range
* evidence used
* timestamp
* model versions

---

# 11. Opportunity Detection

The system should compare its final probability against the current market-implied probability.

Example:

Market probability:

42%

Final model probability:

58%

Raw estimated edge:

16 percentage points

A large raw difference does not automatically justify a trade.

The system should eventually consider:

* probability difference
* forecast uncertainty
* model confidence
* market liquidity
* expected slippage
* platform fees
* market resolution rules
* available bankroll
* current portfolio exposure
* correlated positions
* historical model calibration

The opportunity engine should produce one of several possible outcomes.

Examples:

* IGNORE
* WATCH
* TRADE

The exact thresholds should remain configurable and should be refined using paper-trading results.

---

# 12. Advantageous Trade Definition

An advantageous trade is one where the system estimates that the expected value of entering the position remains positive after accounting for relevant costs, uncertainty, and risk.

A conceptual model is:

Adjusted Edge

=

Model Probability

*

Market Probability

*

Transaction Costs

*

Expected Slippage

*

Uncertainty Penalty

*

Other Risk Adjustments

The exact formula is experimental and should evolve.

The system should record both raw and adjusted edge values.

---

# 13. Dynamic Position Sizing

Position size should not be fixed.

The system should dynamically determine position size using factors such as:

* estimated edge
* model confidence
* liquidity
* uncertainty
* historical calibration
* current bankroll
* current portfolio exposure
* correlated exposure
* recent performance
* drawdown

A larger estimated edge and higher confidence may justify a larger position.

A lower-confidence or poorly calibrated forecast should receive a smaller position or no position.

The initial implementation may use a simple rules-based sizing model.

More advanced position-sizing approaches, including Kelly-style strategies, may be evaluated later.

---

# 14. Risk Escalation

Initial risk escalation should be based primarily on the proposed percentage of available bankroll exposed to the trade.

Conceptual default rules:

### Below 10% of available bankroll

May be automatically executed if all normal risk checks pass.

### Between 10% and 40%

May be automatically executed only when confidence is high and other risk checks pass.

### Above 40%

Requires explicit human approval.

These percentages must be configurable.

These values are experimental and should not be treated as proven optimal risk limits.

The system should be able to introduce additional safeguards as the project develops.

---

# 15. Human Interaction

The system should distinguish between two different reasons for contacting the user.

## Risk Approval

The system has already formed a recommendation but requires approval due to risk.

Example:

> 🚨 Large position detected.
>
> Market has the Knicks at 41%.
> I estimate 59%.
>
> Proposed exposure: 43% of available bankroll.
>
> Main reason: confirmed opponent injury combined with model disagreement.
>
> Recommended action: Buy YES.
>
> Approve or reject?

The user is not being asked to forecast the event.

The user is being asked to approve the risk.

## Human Information Request

The system may occasionally determine that asking the user a question could materially improve the forecast.

The bot should only ask a domain-specific question when it has a reasonable basis to believe the user may possess useful knowledge.

The system should not ask the user random expert questions about unfamiliar domains.

For example, the system should not ask the user to evaluate obscure pigeon-hunting information simply because a market exists.

When the user's expected domain knowledge is unknown or low, the system should rely on external research and only request risk approval when necessary.

Future versions may maintain a configurable user expertise profile.

---

# 16. Autonomous Trading

The system is intended to eventually support mostly autonomous trading.

The system should be capable of:

* identifying trades
* determining position sizes
* opening positions
* monitoring positions
* reducing positions
* increasing positions when allowed
* closing positions early
* allowing contracts to resolve

All autonomous actions must pass through the risk engine.

Real-money execution should never be controlled directly by an LLM.

A deterministic execution layer should be responsible for validating and submitting orders.

---

# 17. Exit Strategy

The system should not assume every position must be held until market resolution.

Open positions should be continuously or periodically reevaluated.

Reasons to exit or reduce a position may include:

* the market price moves toward the system's estimated probability
* the estimated edge disappears
* new evidence changes the forecast
* the model reverses its position
* liquidity conditions deteriorate
* portfolio risk becomes excessive
* a stop or risk rule is triggered
* expected value becomes negative

The system should record the reason for every exit decision.

---

# 18. Paper Trading

Paper trading is the default execution mode.

The initial system must not require real money.

Paper trading should attempt to simulate realistic execution.

The simulation should eventually account for:

* market price
* order-book depth
* liquidity
* partial fills
* fees
* slippage
* position sizing
* early exits

The paper-trading system should maintain a simulated bankroll.

Every simulated trade should be recorded exactly as a real trade would be recorded.

The goal is to evaluate whether the strategy appears profitable before exposing real capital.

---

# 19. Live Trading

Live trading is out of scope for the initial MVP.

The architecture should allow live execution later.

The initial conceptual live deployment will use very small amounts of capital.

A starting constraint may limit newly deployed capital to approximately $10 per day.

The exact rule should be configurable.

Live capital should increase only after evaluating:

* sample size
* profitability
* model calibration
* maximum drawdown
* execution quality
* strategy stability

A short winning streak must not automatically justify increasing risk.

---

# 20. Trade Logging and Auditability

Every meaningful decision must be stored.

For each forecast, the system should eventually record:

* market
* event
* platform
* market price
* order-book state
* base probability
* final probability
* confidence
* uncertainty
* raw edge
* adjusted edge
* evidence
* data sources
* model versions
* timestamps

For each trade, the system should eventually record:

* proposed trade
* position size
* approval status
* execution mode
* entry price
* executed quantity
* expected edge
* actual fill
* fees
* slippage
* exit price
* exit reason
* profit or loss
* final market resolution

The system should make it possible to reconstruct why any trade was made.

---

# 21. Evaluation

The system must evaluate both forecasting quality and financial performance.

Forecasting metrics may include:

* Brier score
* log loss
* calibration
* accuracy by confidence level

Trading metrics may include:

* total profit and loss
* return on capital
* maximum drawdown
* win rate
* average edge at entry
* average realized return
* performance by market type
* performance by model version
* performance by confidence
* performance by position size
* execution slippage

The system should compare:

* quantitative base model performance
* AI-adjusted forecast performance

This comparison is important.

AI adjustments should not be assumed to improve forecasts.

If the base model consistently outperforms the AI-adjusted model, that result should be visible.

---

# 22. Dashboard

The web dashboard should eventually provide visibility into:

## Portfolio

* current bankroll
* paper or live mode
* daily P&L
* total P&L
* current exposure

## Active Positions

* market
* direction
* entry price
* current price
* bot probability
* estimated edge
* unrealized P&L

## Opportunities

* available markets
* market probability
* bot probability
* estimated edge
* confidence
* recommended action

## Forecast Details

* base probability
* final probability
* probability history
* evidence
* sources
* confidence
* uncertainty
* model versions

## Trade History

* entries
* exits
* position sizes
* reasons
* P&L

## Evaluation

* calibration
* Brier score
* strategy returns
* drawdown
* performance by model

---

# 23. Mobile Experience

The first version does not require a native mobile application.

The initial dashboard should be responsive and usable from a mobile browser.

Mobile interactions should prioritize:

* trade alerts
* approval requests
* major risk alerts
* position updates
* important evidence changes

Notifications should be conversational rather than excessively mechanical.

Example:

> 🚨 Found something interesting.
>
> The market has New York at 42%, but I'm estimating 61%.
>
> A confirmed injury update is responsible for most of the difference.
>
> Proposed position: 7% of bankroll.
>
> Confidence: High.
>
> Executing automatically unless risk conditions change.

High-risk example:

> 👀 This one's big.
>
> Market: Knicks YES
>
> Market probability: 39%
> My estimate: 64%
>
> Proposed exposure: 44%.
>
> This exceeds your automatic trading limit.
>
> Approve or reject?

---

# 24. Platform Expansion

The system should eventually support multiple prediction-market platforms.

Each platform should implement a common adapter interface.

Core trading logic should not depend directly on a specific platform.

Future functionality may include:

* comparing equivalent markets across platforms
* identifying cross-platform pricing discrepancies
* selecting the best execution venue
* cross-market arbitrage

These features are not required for V1.

---

# 25. Domain Expansion

After the NBA system is working and evaluated, the system may expand to:

* NFL
* MLB
* NHL
* soccer
* additional sports

Later domains may include:

* technology
* business
* economics
* politics
* other prediction-market categories

Each domain may require its own base forecasting models and evidence-processing rules.

The shared market, trading, risk, evaluation, and execution architecture should remain reusable.

---

# 26. MVP Requirements

The first meaningful MVP should be able to:

1. Connect to one prediction-market data source.
2. Retrieve supported NBA markets.
3. Normalize market data.
4. Retrieve NBA game data.
5. Match supported markets to NBA events.
6. Generate a base probability.
7. Store forecasts.
8. Compare forecasts against market pricing.
9. Identify potential opportunities.
10. Simulate trades.
11. Track open paper positions.
12. Exit or resolve paper positions.
13. Calculate paper P&L.
14. Record decisions and results.
15. Display basic results in a dashboard.

AI evidence adjustment may be introduced after the base forecasting and paper-trading pipelines work correctly.

---

# 27. Explicit Non-Goals for Early Development

The initial version does not need:

* real-money trading
* native mobile applications
* multiple prediction-market exchanges
* every professional sport
* arbitrary prediction-market categories
* high-frequency trading
* advanced machine-learning forecasting
* complex microservice infrastructure
* Kubernetes
* automatic self-modification of production strategy
* unrestricted LLM control of trading accounts

These may be considered later where useful.

---

# 28. Product Principles

The project should prioritize:

### Measurability

The system must prove whether its forecasts and strategies work.

### Auditability

Every important prediction and trading decision should be explainable after the fact.

### Modularity

Markets, data providers, models, agents, and execution systems should be replaceable.

### Safety

Paper trading is the default.

Real trades must pass deterministic risk controls.

### Iteration

The first model does not need to be brilliant.

The system should make experimentation and comparison easy.

### Evidence Over Hype

AI components must demonstrate measurable improvement.

They should not be included merely because using AI sounds impressive.

### Simplicity Before Scale

The architecture should support future growth without prematurely building infrastructure the project does not yet need.

---

# 29. Definition of Product Success

Success is not defined by completing the project within a specific amount of time.

The primary indicators of success are:

1. The system demonstrates measurable prediction quality.
2. The system demonstrates positive risk-adjusted paper-trading performance over a meaningful sample.
3. The architecture is technically defensible and well documented.
4. The system can explain and reconstruct its decisions.
5. The project demonstrates strong engineering depth for resumes and technical interviews.
6. The system can eventually operate with limited autonomous real-money execution while respecting configurable risk controls.

The ultimate long-term goal is to determine whether combining quantitative forecasting, real-time information processing, AI-assisted evidence analysis, and automated execution can consistently identify and capitalize on mispriced prediction markets.
