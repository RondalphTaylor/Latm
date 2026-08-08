# Project Mission

Build an auditable, autonomous prediction-market research and trading platform.

The initial focus is NBA prediction markets and paper trading.

The long-term system should:

- ingest prediction-market data
- ingest sports data and relevant external information
- calculate base probabilities using quantitative models
- use AI to evaluate new evidence and adjust forecasts
- identify potentially mispriced prediction-market contracts
- dynamically size positions based on edge, confidence, liquidity, and risk
- paper trade before any real-money trading
- eventually support multiple prediction-market platforms
- maintain a complete audit trail of every prediction and trading decision

# Current Development Priority

The project is currently in the MVP stage.

Initial scope:

1. NBA markets
2. One prediction-market platform
3. Market data ingestion
4. NBA data ingestion
5. Base probability estimation
6. AI evidence analysis
7. Paper trading
8. Evaluation and calibration

Real-money trading is explicitly out of scope until the paper-trading system has been evaluated.

# Engineering Principles

- Python is the primary language for backend, forecasting, data, and trading systems.
- TypeScript is the primary language for user interfaces.
- Python functions must use explicit type hints.
- TypeScript must use explicit types where reasonable.
- Prefer simple modular architecture over premature microservices.
- All external platforms must be accessed through adapters.
- Business logic must not depend directly on a specific prediction-market provider.
- LLM outputs must use validated structured schemas.
- LLMs must never directly call real-money trading APIs.
- The trading engine must always pass decisions through the risk engine.
- Paper trading must be the default execution mode.
- Every forecast must be reproducible.
- Every trade decision must be logged.
- Every model and strategy must be versioned.

# AI and Forecasting Principles

The AI should not generate probabilities from intuition alone.

Forecasts should follow this general structure:

1. Generate a quantitative base probability.
2. Retrieve relevant external evidence.
3. Evaluate evidence for:
   - relevance
   - reliability
   - freshness
   - independence
4. Estimate how evidence affects the base probability.
5. Generate a final probability and uncertainty range.
6. Compare the final probability against market pricing.

AI-generated evidence adjustments must be auditable.

# Risk Principles

The system should dynamically size positions.

Initial conceptual escalation rules:

- Proposed exposure below 10% of available bankroll:
  - may be automatically executed if risk requirements pass

- Proposed exposure between 10% and 40%:
  - may be automatically executed only with high confidence and sufficient liquidity

- Proposed exposure above 40%:
  - requires human approval

These thresholds are configurable and experimental.

The system should distinguish between:

1. Human risk approval
2. Human domain-knowledge requests

The system should not ask the user domain-specific questions unless it has reason to believe the user can provide useful information.

# Trading Safety

The default trading mode must always be:

TRADING_MODE=paper

Real-money execution must require an explicit configuration change.

Do not weaken or bypass this safeguard without explicit user instruction.

# Required Development Workflow

Before implementing a major feature:

1. Read this AGENTS.md file.
2. Read ARCHITECTURE.md.
3. Read ROADMAP.md.
4. Read relevant files in docs/.
5. Inspect the existing implementation.
6. Produce an implementation plan.
7. Implement the smallest reasonable scope.
8. Add or update tests.
9. Run relevant tests.
10. Run linting and type checking.
11. Update documentation when architecture or behavior changes.

# Testing

New business logic should include tests.

Important areas requiring strong test coverage include:

- probability calculations
- market normalization
- event matching
- position sizing
- paper trade execution
- P&L calculations
- risk limits
- trading-mode safeguards

Tests must not make real-money trades.

# Agent Behavior

When requirements are ambiguous:

- prefer conservative behavior
- do not invent major product requirements
- document meaningful assumptions
- avoid unnecessary infrastructure
- do not introduce new external dependencies without justification

For large tasks, break work into independently verifiable components.

Use subagents when tasks can reasonably be performed in parallel without creating conflicting changes.

# Documentation

Major architectural decisions should be documented.

Important experimental results should also be preserved, including:

- forecasting performance
- strategy performance
- failed approaches
- calibration results
- major changes to risk policy