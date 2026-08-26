# Prediction System Specification

## 1. Purpose

This document defines how the platform should generate, update, evaluate, and store probability forecasts.

The prediction system is responsible for answering:

> What probability does the system assign to each possible market outcome?

The prediction system should remain separate from:

* opportunity detection
* position sizing
* risk management
* trade execution

A good forecast does not automatically imply a trade.

The prediction system estimates what is likely to happen.

Other components determine whether the market price creates an attractive opportunity and whether the system should risk capital.

---

# 2. Initial Domain

The initial prediction domain is NBA game outcomes.

The first supported forecast type should be:

```text
P(Home Team Wins)
```

and therefore:

```text
P(Away Team Wins)
=
1 - P(Home Team Wins)
```

The initial system should focus on regulation-and-overtime game winners where market resolution rules clearly correspond to the final official game result.

Markets with unusual resolution conditions should not automatically reuse the standard game-win forecast.

---

# 3. Forecasting Pipeline

The prediction pipeline should conceptually follow:

```text
Structured NBA Data
        │
        ▼
Base Forecast Model
        │
        ▼
Base Probability
        │
        ▼
External Evidence
        │
        ▼
Evidence Analysis
        │
        ▼
Evidence Adjustments
        │
        ▼
Final Probability
        │
        ▼
Confidence + Uncertainty
        │
        ▼
Stored Forecast
```

The deterministic base forecasting pipeline should work before AI evidence adjustment is introduced.

---

# 4. Forecast Types

The system should distinguish between at least two forecast types.

## Base Forecast

A probability generated using structured quantitative data.

Example:

```text
Knicks win probability:
54%
```

Generated from:

* team ratings
* home-court advantage
* recent results
* rest
* other structured features

## Final Forecast

A probability generated after considering relevant external evidence.

Example:

```text
Base probability:
54%

Important new evidence:
Starting point guard ruled out

Final probability:
47%
```

The system should always preserve the original base forecast.

The final forecast must never overwrite the historical base forecast.

---

# 5. Forecasting Principles

The forecasting system should follow these principles.

## Probabilities Must Be Explicit

Forecasts should use probabilities between:

```text
0.0
and
1.0
```

Example:

```text
0.63
```

represents:

```text
63%
```

## Forecasts Must Be Versioned

Every forecast must identify the model and strategy that produced it.

## Forecasts Must Be Reproducible

Given:

* the same model version
* the same input data
* the same configuration

the deterministic base model should produce the same result.

AI-assisted forecasts may have limited nondeterminism depending on the model used.

Relevant AI settings and outputs should still be stored.

## Forecasts Must Be Auditable

It should be possible to determine:

* what data was used
* what model was used
* what evidence was used
* how the forecast changed
* when the forecast was generated

---

# 6. Base Model V1

The first base model should prioritize simplicity, interpretability, and measurability.

Recommended initial approach:

```text
Elo-style team strength model
+
Home-court advantage
```

This establishes the forecasting pipeline with minimal complexity.

More features should be added only after the baseline model works and can be evaluated.

---

# 7. Elo-Style Rating Model

Each NBA team should maintain a numerical strength rating.

Conceptually:

```text
Higher Rating
=
Stronger Team
```

After each completed game:

```text
Winner gains rating

Loser loses rating
```

The size of the adjustment should depend on:

* expected result
* actual result

Unexpected outcomes should cause larger rating changes.

Expected outcomes should cause smaller rating changes.

The exact formula should be documented and versioned.

---

# 8. Initial Elo Probability

For a matchup:

```text
Home Team Rating
vs
Away Team Rating
```

the system should calculate an expected home-team win probability.

Conceptually:

```text
rating_difference
=
home_rating
-
away_rating
+
home_court_adjustment
```

Then convert the rating difference into a probability.

The implementation may use a standard Elo logistic probability function.

The exact mathematical formula should live with the model implementation and be documented.

## Implemented NBA Elo V1 policy

The initial production policy is fixed and versioned as `nba_elo` code version `1.0.0`, with the effective configuration fingerprint embedded in the persisted version string.

```text
initial_rating = 1500
k_factor = 20
logistic_scale = 400
home_court_advantage = 100 Elo points

adjusted_difference = home_rating + home_court_advantage - away_rating
p_home = 1 / (1 + 10 ^ (-adjusted_difference / logistic_scale))
p_away = 1 - p_home

delta = k_factor * (actual_home_win - p_home)
new_home_rating = home_rating + delta
new_away_rating = away_rating - delta
```

Probabilities are calculated with deterministic decimal arithmetic and persisted as exact complements to six decimal places. Ratings are persisted to four decimal places, and each update is zero-sum. V1 deliberately excludes margin of victory, season resets, recency weighting, rest, injuries, advanced statistics, market prices, and AI evidence. Any change to these semantics requires a new effective configuration fingerprint and model identity.

Replay is ordered by scheduled tip and stable event ID. Only final, non-postponed local records strictly before a target cutoff may affect ratings. Incomplete or equal-score final records are fingerprinted and counted but do not update ratings. A target result and any simultaneous or later game are excluded. Unseen teams retain the recorded equal-rating initialization and are exposed as cold starts through their zero prior-game counts.

`operational` forecasts use a single generation-time cutoff for future scheduled events that have a latest eligible Phase 3 match. `historical_replay` forecasts use each completed target's scheduled tip as the cutoff and do not require a market. Historical replay is a simulated chronological evaluation and does not claim that every result was available to the platform at that historical time; the current normalized schema does not preserve first-observed result timestamps.

---

# 9. Initial Team Ratings

The system needs a strategy for initializing team ratings.

Possible options include:

* all teams start equal
* ratings are seeded using previous-season performance
* ratings are generated from historical games

For V1, using historical NBA game results to generate ratings is preferred where practical.

If sufficient historical data is unavailable during early implementation, equal initialization is acceptable.

The initialization method must be recorded as part of the model version.

---

# 10. Home-Court Advantage

Home-court advantage should initially be implemented as a configurable Elo-style rating adjustment.

Example conceptually:

```text
Adjusted Home Rating
=
Home Team Elo
+
Home Court Adjustment
```

The exact value should be configurable.

It should later be estimated using historical data rather than treated as permanently fixed.

---

# 11. Base Model V1 Features

The minimum required features for the first working model are:

* home-team rating
* away-team rating
* home-court adjustment

The first model should intentionally remain simple.

This baseline allows future improvements to be measured.

---

# 12. Base Model V2 Candidates

After V1 is evaluated, additional structured features may include:

* recent team performance
* offensive rating
* defensive rating
* net rating
* strength of schedule
* rest days
* back-to-back status
* travel
* player availability
* starting lineup availability
* estimated minutes lost
* schedule density

These features should not all be added simultaneously without evaluation.

Each meaningful model change should create a new model version.

---

# 13. Player Availability

Player availability is likely to become one of the most important inputs.

Possible statuses include:

```text
AVAILABLE

PROBABLE

QUESTIONABLE

DOUBTFUL

OUT
```

The system should distinguish between:

* known structured injury data
* uncertain external reports
* AI-interpreted evidence

Confirmed structured player availability may eventually be incorporated directly into the base model.

Breaking or ambiguous information may remain part of evidence adjustment.

---

# 14. Probability Snapshot Timing

NBA forecasts may change substantially as game time approaches.

The system should support multiple forecast snapshots.

Potential snapshots include:

```text
24 hours before game

6 hours before game

1 hour before game

30 minutes before game

At lineup confirmation
```

The exact schedule should evolve.

Each snapshot should be stored separately.

The system must not overwrite earlier forecasts.

Historical forecast movement is valuable evaluation data.

---

# 15. External Evidence

External evidence is information that may affect the probability beyond the current structured base-model inputs.

Examples:

* player ruled out
* minutes restriction announced
* unexpected starting lineup
* coach announcement
* travel disruption
* team illness
* suspension
* late injury
* trusted reporter update

Evidence should not modify probabilities before being evaluated.

---

# 16. Evidence Item Structure

Each evidence item should conceptually contain:

```text
id

event_id

claim

source

source_type

source_timestamp

retrieved_timestamp

relevance

reliability

freshness

independence_group

direction

estimated_impact

analysis_version
```

The exact database model may differ.

---

# 17. Evidence Relevance

Relevance measures how directly an evidence item affects the target event.

Conceptual range:

```text
0.0
to
1.0
```

Example:

```text
Starting player ruled out for tonight

relevance:
0.98
```

Example:

```text
Article discussing the team's season generally

relevance:
0.30
```

Low-relevance evidence should have little or no effect on the forecast.

---

# 18. Evidence Reliability

Reliability measures confidence that the information is accurate.

Possible factors include:

* official source
* reputable reporter
* direct quote
* secondary reporting
* anonymous social account
* unsupported rumor

Conceptual examples:

```text
Official NBA injury report:
0.99

Reliable beat reporter:
0.90

Major sports publication:
0.85

Unverified social post:
0.25
```

These numbers are conceptual and should eventually be calibrated.

---

# 19. Evidence Freshness

Freshness measures whether information remains current.

Recent information may be more useful than older information.

Example:

```text
Player ruled out 20 minutes ago
```

should have high freshness.

Example:

```text
Player reported questionable three days ago
```

may have lower freshness if newer information exists.

Freshness alone does not determine importance.

---

# 20. Evidence Independence

The system should avoid treating repeated reports of the same original fact as independent evidence.

Example:

```text
Reporter A posts injury update

Website B reports Reporter A's update

Website C summarizes Website B
```

These should likely belong to the same:

```text
independence_group
```

rather than being treated as three independent signals.

---

# 21. Evidence Direction

Evidence should indicate which side of the forecast it supports.

Possible conceptual values:

```text
HOME_POSITIVE

HOME_NEGATIVE

AWAY_POSITIVE

AWAY_NEGATIVE

NEUTRAL
```

These may be simplified internally.

Because NBA game outcomes are binary:

```text
HOME_NEGATIVE
```

is generally equivalent to:

```text
AWAY_POSITIVE
```

The data model should avoid unnecessary duplication.

---

# 22. Evidence Impact

Evidence impact represents the estimated effect on probability.

Conceptual example:

```text
Base home win probability:
0.57

Star player ruled out

Estimated adjustment:
-0.08

Adjusted probability:
0.49
```

Impact estimates should include uncertainty.

For example:

```text
estimated_delta:
-0.08

plausible_delta_range:
-0.04 to -0.12
```

The system should avoid pretending probability adjustments are more precise than the evidence supports.

---

# 23. AI Evidence Agent

The Evidence Agent should analyze a specific evidence item.

The Evidence Agent should not see itself as a trader.

Its responsibility is to answer:

> What does this information mean for the forecast?

Conceptual structured output:

```json
{
  "claim": "Starting point guard ruled out",
  "relevance": 0.98,
  "reliability": 0.97,
  "freshness": 0.99,
  "direction": "HOME_NEGATIVE",
  "estimated_probability_delta": -0.07,
  "delta_lower_bound": -0.03,
  "delta_upper_bound": -0.11,
  "reasoning_summary": "..."
}
```

The exact schema should use validated typed models.

---

# 24. AI Forecast Agent

The Forecast Agent should receive:

* base forecast
* evaluated evidence
* relevant event context

Its job is to estimate a final probability.

It should explicitly distinguish between:

* quantitative baseline
* evidence-based changes
* remaining uncertainty

Conceptual output:

```json
{
  "base_probability": 0.57,
  "final_probability": 0.49,
  "confidence": 0.78,
  "lower_bound": 0.42,
  "upper_bound": 0.56,
  "major_supporting_factors": [],
  "major_opposing_factors": [],
  "unresolved_uncertainties": []
}
```

---

# 25. AI Critic Agent

The Critic Agent should challenge the forecast.

Its purpose is not to generate an independent random probability.

It should inspect the forecast for weaknesses.

Questions may include:

* Was evidence counted twice?
* Is a source unreliable?
* Is important information missing?
* Is the probability adjustment too large?
* Is uncertainty understated?
* Does the market have unusual resolution rules?
* Is the evidence stale?
* Does the argument rely on unsupported assumptions?

The critic should output structured issues and severity.

---

# 26. Forecast Revision

After criticism, the system may allow the Forecast Agent to produce a revised forecast.

Conceptually:

```text
Initial Forecast

↓

Critic Review

↓

Forecast Revision

↓

Final Stored Forecast
```

The original pre-critique forecast should remain stored or recoverable for evaluation.

This allows analysis of whether critic review improves forecasting.

---

# 27. Evidence Aggregation

Multiple evidence items must be combined carefully.

The system should not blindly sum all probability adjustments.

Example:

```text
Evidence A:
Player ruled out
-8%

Evidence B:
Article reporting same player ruled out
-7%

Evidence C:
Another article repeating same report
-6%
```

The system should not produce:

```text
-21%
```

because these items may all represent the same underlying information.

Aggregation should consider:

* independence
* relevance
* reliability
* overlap
* conflicting evidence

The exact method should be versioned.

---

# 28. Final Probability Constraints

Final probabilities must remain within:

```text
0.0
to
1.0
```

The system should avoid extreme probabilities without exceptional evidence.

Exact caps may eventually be introduced, such as avoiding outputs extremely close to:

```text
0%
or
100%
```

unless the event is nearly resolved.

Any probability transformation should be documented.

---

# 29. Confidence

Confidence should not simply mean:

> The AI feels confident.

Confidence should represent the system's estimate of forecast reliability.

Potential inputs include:

* model historical calibration
* data completeness
* evidence quality
* evidence consistency
* source reliability
* forecast uncertainty
* event-match confidence

Confidence should eventually be calibrated against historical results.

---

# 30. Initial Confidence System

Before sufficient historical data exists, confidence may use a rules-based score.

Conceptual factors:

```text
Base Model Reliability

+

Data Completeness

+

Evidence Reliability

+

Evidence Agreement

-

Missing Information

-

Conflicting Evidence
```

Output:

```text
0.0
to
1.0
```

Example labels:

```text
LOW

MEDIUM

HIGH
```

The numeric score should remain the underlying representation.

---

# 31. Confidence and Risk

Confidence is an input to trading decisions.

However:

```text
High confidence
```

does not mean:

```text
Guaranteed outcome
```

The risk engine should treat confidence as one factor.

Confidence must never bypass exposure caps or other deterministic safeguards.

---

# 32. Uncertainty Range

Final forecasts should include an uncertainty interval.

Example:

```text
Final Probability:
0.61

Plausible Range:
0.53 to 0.68
```

The initial uncertainty system may be heuristic.

Later versions should attempt to derive better-calibrated uncertainty estimates.

Wide ranges should reduce trading aggressiveness.

---

# 33. Forecast Comparison

The system should evaluate multiple forecast stages separately.

At minimum:

```text
Market Probability

Base Model Probability

Final AI-Adjusted Probability
```

Example:

```text
Market:
42%

Base:
51%

Final:
58%
```

This makes it possible to determine where predictive value is coming from.

---

# 34. Forecast History

Every material forecast change should create a new snapshot.

Example:

```text
10:00 AM
Base: 54%
Final: 54%

4:00 PM
New injury evidence
Final: 49%

6:45 PM
Player confirmed active
Final: 55%
```

This history should support:

* backtesting
* calibration
* trade analysis
* model debugging

---

# 35. Forecast Validity

Forecasts should have freshness requirements.

A forecast may become stale when:

* important sports data changes
* new evidence appears
* market conditions change significantly
* expected lineups change

The opportunity engine should not trade using forecasts that exceed configured staleness limits.

---

# 36. Market Information Leakage

Prediction-market prices should not automatically be used as primary inputs to the base forecast.

Otherwise the system risks simply reproducing the market probability it is trying to evaluate.

The base forecast should primarily rely on independent structured data.

Market prices may be used for:

* comparison
* opportunity detection
* secondary research
* model evaluation

Any model that directly incorporates market pricing should be explicitly identified as a separate model version.

---

# 37. Sportsbook Information

Traditional sportsbook odds may eventually be used as an additional forecasting signal.

However, sportsbook odds are themselves market forecasts.

They should not be treated as independent factual evidence.

Potential future models may compare:

```text
Internal Quantitative Model

Sportsbook-Implied Probability

Prediction-Market Probability
```

This can be useful, but should remain transparent.

---

# 38. Probability Calibration

Calibration is a core requirement.

If the system makes many predictions around:

```text
70%
```

approximately 70% of those events should occur over a sufficiently large sample.

Calibration buckets may include:

```text
50%-60%

60%-70%

70%-80%

80%-90%

90%-100%
```

More sophisticated calibration analysis may be added later.

---

# 39. Brier Score

The system should calculate Brier score for resolved binary forecasts.

For prediction:

```text
p
```

and outcome:

```text
y
```

where:

```text
y = 1
```

for a win and:

```text
y = 0
```

for a loss:

```text
Brier Score
=
(p - y)^2
```

Lower Brier scores indicate better probabilistic predictions.

Brier score should be evaluated separately for:

* base forecasts
* final forecasts
* model versions

---

# 40. Log Loss

Log loss may also be tracked.

It heavily penalizes highly confident incorrect forecasts.

This can be useful for detecting dangerous overconfidence.

The implementation should handle numerical stability near:

```text
0
and
1
```

---

# 41. Forecast Evaluation Segmentation

Forecast performance should eventually be segmented by:

* model version
* confidence
* probability range
* home vs away prediction
* date range
* time before game
* evidence present vs absent
* AI-adjusted vs base-only

This helps identify where the system performs well or poorly.

---

# 42. Forecast Model Registry

Each forecasting component should have a version identifier.

Examples:

```text
nba_elo_v1

nba_elo_rest_v2

evidence_agent_v1

forecast_adjustment_v1

critic_v1

confidence_rules_v1
```

Forecast records should reference relevant versions.

---

# 43. Model Experimentation

New models should be treated as experiments before replacing existing production models.

Conceptual process:

```text
Existing Model

vs

Candidate Model

↓

Historical Evaluation

↓

Paper Trading Comparison

↓

Decision
```

The system should make side-by-side model evaluation possible.

---

# 44. Shadow Forecasting

Future model versions may run in shadow mode.

A shadow model:

* produces predictions
* stores results
* does not influence trading

This allows new approaches to be evaluated safely.

Example:

```text
Production Forecast:
nba_elo_v2

Shadow Forecast:
nba_ml_v1
```

After sufficient evaluation, the shadow model may be promoted.

---

# 45. Human Input

Human input should not directly overwrite forecasts without being recorded.

If the user provides relevant information, it should be converted into a traceable evidence item.

Example:

```text
Source Type:
human_input

Claim:
Player reportedly expected to have minutes restriction

Reliability:
unknown or manually configured
```

The system should preserve the fact that the evidence came from the user.

---

# 46. Forecast Failure Modes

The system should explicitly guard against:

* stale data
* missing games
* incorrect team matching
* duplicate evidence
* unreliable sources
* AI hallucinations
* extreme overconfidence
* unsupported probability jumps
* incorrect market resolution interpretation

When forecast integrity is questionable, the system should prefer:

```text
NO_FORECAST
```

or:

```text
LOW_CONFIDENCE
```

rather than inventing certainty.

---

# 47. Missing Data Behavior

When required structured data is missing:

```text
Do not silently substitute invented values.
```

The system may:

* use documented defaults
* fall back to a simpler model
* reduce confidence
* skip the forecast

The chosen behavior should be explicit.

---

# 48. Prediction API

The backend should eventually expose forecast data.

Potential routes:

```text
GET /forecasts

GET /forecasts/{id}

GET /events/{id}/forecasts
```

Responses may include:

* base probability
* final probability
* confidence
* uncertainty
* model versions
* evidence references
* timestamp

Detailed internal AI chain-of-thought should not be required or stored.

Concise reasoning summaries and structured evidence are sufficient.

---

# 49. Forecast Database Records

Potential records include:

```text
base_forecasts

final_forecasts

forecast_snapshots

model_versions

evidence_items

evidence_analyses

critic_reviews
```

The exact schema should be defined when implementing the corresponding phase.

---

# 50. MVP Prediction System

The first implementation should include only:

```text
NBA Historical Game Data

↓

Elo Ratings

↓

Home-Court Adjustment

↓

Base Win Probability

↓

Stored Forecast
```

Then:

```text
Base Probability

vs

Prediction-Market Probability
```

AI should not be required for the first forecasting milestone.

---

# 51. Second Prediction Milestone

After the base forecasting pipeline works:

```text
Base Forecast

+

Structured Player Availability

↓

Improved Base Forecast
```

The system should evaluate whether this improves predictive performance.

---

# 52. Third Prediction Milestone

After deterministic forecasting is measurable:

```text
External Research

↓

Evidence Extraction

↓

AI Evidence Analysis

↓

Final Probability
```

Then compare:

```text
Base Model

vs

AI-Adjusted Model
```

The AI system should earn its place through measurable results.

## Implemented MLB model-candidate contract

The MLB pilot now freezes eight matchup inputs before model fitting: sample-weighted lineup observed
wOBA, expected wOBA on contact, hard-hit rate, and barrel rate, plus the same allowed-contact
measures for the probable starters. Lineup features use home minus away; starter allowed features
use away minus home, so positive always favors the home team. Exact source coverage is retained and
missing values are not imputed.

The candidate is regularized logistic regression for the official final home-win target. Examples
must be ordered by scheduled first pitch and assigned to explicit chronological train, validation,
test, and untouched prospective-holdout intervals. Random shuffling is forbidden. This is a design
and dataset contract with a deterministic fitter. Once the approved 500/150/150 exploratory gates
pass, one immutable research artifact can freeze fitted coefficients, standardization, out-of-sample
metrics, and exact ordered example lineage. The current live dataset remains below that gate, and no
operational probability output or MLB trading eligibility exists.

Prospective research collection composes the official schedule, lineup, Statcast, and feature
services for no more than seven calendar days and 25 returned events per invocation. It advances
only scheduled games strictly before first pitch and stops at incomplete lineups. Canonical dataset
selection returns at most one labeled vector per event, always preferring operational pregame
evidence; retrospective fallback is explicit and research-only. These additions still fit no
live artifact below the readiness gate and cannot generate an operational probability.

Dataset-readiness V1 uses fixed June 1, July 1, and August 23, 2026 boundaries and minimum split
sizes of 500/150/150/200. Retrospective examples are permitted only for exploratory train,
validation, and test intervals; the prospective holdout is operational-pregame-only. Historical
backfill can use complete official postgame lineups, but every derived source and example retains
retrospective provenance and cannot satisfy the holdout or any trading gate.

Before fitting, the approved canonical selection can be frozen into an immutable dataset-quality
audit. V1 recomputes chronological and pregame leakage constraints, feature-policy and safety
identity, missingness, duplicates, and outcome timing, then reports class/team/date coverage,
feature distributions, zero variance, and minimum-side source support. A passing quality report is
descriptive and structural only; it cannot satisfy readiness thresholds, publish a probability, or
enable trading.

---

# 53. Recommended Development Principle

The prediction system should evolve in this order:

```text
Simple

↓

Measurable

↓

Calibrated

↓

More Sophisticated
```

Not:

```text
Complex

↓

Impressive Looking

↓

Impossible to Debug
```

The system should always retain a strong baseline model.

If a more advanced model cannot outperform the baseline, it should not automatically replace it.

---

## Implemented Phase 10 forecast evaluation

Phase 10 evaluates one designated home-win Bernoulli probability per completed NBA event. It does not score the complementary away probability as a second observation. The exact scalar score is `(home_probability - home_won)^2`; accuracy abstains at exactly `0.5` instead of choosing an arbitrary side.

The current canonical sample contains only the newest forecast snapshot for each event, model version, and purpose. Operational forecasts must have been generated strictly before tip. Historical replay uses tip as its chronological cutoff and is always labeled retrospective because the current sports schema does not preserve when earlier results first became available.

Every score freezes the final result semantics, model identity, forecast, policy, and fingerprints in `forecast_evaluations`. A score or event-date correction appends a new row. Current summaries match those frozen values back to the current event row, so a correction reversion selects the original semantic fact without deleting either history record.

Calibration returns every fixed-width bin, including empty bins, plus mean Brier, expected calibration error, and maximum calibration error. Model comparisons use only paired events with the same outcome fingerprint; unpaired sample coverage is reported separately. The engine does not make significance or independence claims from these descriptive metrics.

# 54. Core Prediction Principle

The core forecasting philosophy is:

```text
START WITH A DATA-DRIVEN PRIOR

↓

UPDATE WITH NEW INFORMATION

↓

REPRESENT UNCERTAINTY

↓

MEASURE CALIBRATION

↓

COMPARE AGAINST THE MARKET
```

The prediction system should not attempt to prove that it is smarter than the market.

It should continuously test whether it is.
