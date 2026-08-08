# Codex Development Workflow

## 1. Purpose

This document defines how Codex should be used to build, maintain, test, and evolve the prediction-market trading platform.

The goal is not to maximize the amount of code Codex produces.

The goal is to maximize:

* engineering quality
* correctness
* development speed
* maintainability
* test coverage
* architectural consistency
* effective human oversight

Codex should function as an engineering collaborator operating within clearly defined constraints.

The project should avoid relying on a single massive prompt to generate the entire application.

Development should instead use:

```text
Specification

↓

Bounded Task

↓

Implementation Plan

↓

Implementation

↓

Testing

↓

Review

↓

Documentation

↓

Commit
```

---

# 2. Core Development Principle

Codex should be given:

```text
CLEAR CONTEXT

+

BOUNDED SCOPE

+

TESTABLE ACCEPTANCE CRITERIA
```

Avoid prompts such as:

```text
Build my prediction-market trading bot.
```

Prefer:

```text
Implement Phase 3 market-to-event matching.

Read the relevant project documentation first.

Do not modify forecasting, trading, or risk logic.

Implement:

- NBA team alias matching
- date-aware event matching
- confidence scoring
- ambiguous match handling

Add tests for:
- exact match
- team aliases
- date mismatch
- ambiguous match

Run all relevant tests and type checking.

Report remaining limitations.
```

---

# 3. Codex Surfaces

The project may use Codex through several interfaces.

Each interface should have a primary role.

## Codex Desktop / ChatGPT Desktop

Primary use:

* larger feature work
* parallel agent workflows
* repository-level tasks
* reviewing agent progress
* coordinating independent workstreams
* long-running development sessions

Codex supports delegated subagent workflows where independent tasks can run separately and return results to a main thread. The supported interfaces expose individual subagent threads so their work can be inspected.

---

## Codex CLI

Primary use:

* local repository work
* debugging
* quick implementation tasks
* scripted workflows
* repeatable automation
* CI-related tasks

The CLI can inspect and modify the local repository and run tools installed on the development machine. Non-interactive `codex exec` can also be incorporated into repeatable scripts and pipelines.

---

## IDE Integration

Primary use:

* manual code inspection
* surgical edits
* debugging
* reviewing diffs
* understanding specific files
* collaborating with Codex while actively coding

The developer should use the IDE when human attention is valuable.

Codex should not replace understanding of important system behavior.

---

## Mobile Remote Workflow

Primary use:

* checking active work
* sending follow-up instructions
* answering Codex questions
* reviewing results
* approving actions
* steering development away from the computer

Remote connections currently allow the ChatGPT mobile app to access Codex or ChatGPT work running on a connected Windows or Mac host. From mobile, the user can continue chats, send instructions, approve actions, and inspect outputs such as diffs, tests, terminal output, and screenshots. The host must remain available and connected.

The mobile workflow should be treated primarily as:

```text
STEER

REVIEW

APPROVE

REDIRECT
```

rather than the main environment for manually debugging complex code.

---

# 4. Recommended Development Setup

The recommended development setup is:

```text
GitHub Repository

+

Codex Desktop / ChatGPT Desktop

+

Codex CLI

+

VS Code

+

Docker

+

PostgreSQL
```

The same repository should remain the source of truth regardless of which Codex interface is used.

---

# 5. Repository Instructions

The root:

```text
AGENTS.md
```

defines persistent project-level instructions.

Codex reads applicable `AGENTS.md` instructions before beginning work and supports layered instructions, where guidance closer to the current working directory can override broader repository guidance.

The root `AGENTS.md` should define:

* project mission
* language requirements
* testing expectations
* trading safety boundaries
* documentation requirements
* architecture principles

Future specialized directories may introduce additional instructions.

Example:

```text
backend/
    AGENTS.md

frontend/
    AGENTS.md
```

A backend-specific file might specify:

```text
- Use explicit Python type hints.
- Business logic should remain independent of FastAPI routes.
- New database schema changes require Alembic migrations.
```

A frontend-specific file might specify:

```text
- Use TypeScript.
- Avoid duplicating backend domain types manually where generated types are available.
- Mobile responsiveness is required for approval workflows.
```

Nested instructions should only be added when they provide meaningful value.

---

# 6. Documentation as Persistent Context

Codex should not depend entirely on conversation history.

Important context should live in the repository.

Primary documentation:

```text
AGENTS.md

README.md

ARCHITECTURE.md

ROADMAP.md

docs/product-spec.md

docs/prediction-system.md

docs/risk-policy.md

docs/paper-trading.md

docs/codex-workflow.md
```

Future additions may include:

```text
docs/data-sources.md

docs/decisions/

docs/experiments/

docs/progress.md
```

This creates durable context across new Codex sessions.

---

# 7. Architectural Decision Records

Meaningful architecture decisions should be preserved.

Directory:

```text
docs/decisions/
```

Example:

```text
docs/decisions/
    001-use-postgresql.md
    002-provider-adapter-pattern.md
    003-paper-trading-default.md
```

A decision record should include:

```text
Decision

Context

Alternatives Considered

Reason

Consequences
```

Codex should create a decision record only for meaningful architectural decisions.

Do not create one for trivial implementation details.

---

# 8. Development Progress Log

Maintain:

```text
docs/progress.md
```

This file should summarize completed roadmap phases and major outstanding work.

Example:

```text
# Current Phase

Phase 3: Market-to-Event Matching

# Completed

- Phase 0 project bootstrap
- Phase 1 Kalshi market ingestion
- Phase 2 NBA event ingestion

# Current Work

- Team alias matching
- Match confidence scoring

# Known Issues

- Some abbreviated market titles fail matching

# Next

- Complete Phase 3 acceptance tests
```

Codex should update this file after completing major roadmap milestones.

It should not update it after every tiny change.

---

# 9. Standard Feature Workflow

For significant implementation tasks, Codex should follow:

```text
1. Read instructions.

2. Read relevant documentation.

3. Inspect existing code.

4. Identify affected components.

5. Produce an implementation plan.

6. Implement the smallest complete solution.

7. Add tests.

8. Run tests.

9. Run linting.

10. Run type checking.

11. Review its own diff.

12. Fix discovered issues.

13. Update documentation if necessary.

14. Summarize results.
```

The implementation should remain inside the requested scope.

---

# 10. Standard Feature Prompt

A default Codex feature prompt may use:

```text
Implement [TASK].

Before changing code:

1. Read AGENTS.md.
2. Read ARCHITECTURE.md.
3. Read ROADMAP.md.
4. Read the relevant docs under docs/.
5. Inspect the existing implementation.

Then produce a concise implementation plan.

Implement only the requested scope.

Requirements:

- Follow existing architecture.
- Use explicit types.
- Do not bypass existing abstractions.
- Add or update tests.
- Do not weaken trading safeguards.
- Do not implement future roadmap phases unless required by the current task.

Before finishing:

1. Run relevant tests.
2. Run linting.
3. Run type checking.
4. Review your diff for unnecessary changes.
5. Fix any issues you identify.

At completion report:

- What was implemented
- Files meaningfully changed
- Tests and validation run
- Assumptions made
- Known limitations
- Recommended next task
```

---

# 11. Phase Implementation Prompt

For roadmap phases:

```text
Implement Phase [X] from ROADMAP.md.

Read:

- AGENTS.md
- ARCHITECTURE.md
- ROADMAP.md
- docs/product-spec.md
- all documentation relevant to Phase [X]

First inspect the repository and determine what portions of the phase already exist.

Produce an implementation plan mapped to the acceptance criteria in ROADMAP.md.

Implement the smallest complete version that satisfies those acceptance criteria.

Do not begin later roadmap phases.

Add tests for new business logic.

Run all relevant:

- unit tests
- integration tests
- linting
- type checking

Review the final diff.

At completion provide an acceptance-criteria checklist showing PASS, FAIL, or PARTIAL for every requirement in Phase [X].

Explain any remaining failures or limitations.

Update docs/progress.md if the phase is completed.
```

This should become one of the project's reusable prompt templates.

---

# 12. Task Sizing

Tasks should generally fit one of these categories.

## Small Task

Examples:

```text
Fix incorrect P&L calculation.

Add validation to Forecast schema.

Add team aliases.
```

Use one Codex agent.

---

## Medium Task

Examples:

```text
Implement NBA event ingestion.

Implement risk-engine MVP.

Implement portfolio snapshots.
```

Use one primary Codex agent.

Optional subagents may inspect:

* architecture
* tests
* edge cases

---

## Large Task

Examples:

```text
Implement complete paper-trading engine.

Add AI evidence-analysis pipeline.

Add second prediction-market provider.
```

Consider dividing into multiple bounded tasks.

Use subagents where work can be independently investigated or validated.

---

# 13. Subagent Strategy

Subagents should be used when parallel work improves speed or quality.

Good uses include:

* repository exploration
* documentation research
* test-gap analysis
* security review
* architecture review
* API investigation
* independent bug investigation
* code-review passes

Current Codex guidance recommends parallel agents especially for read-heavy independent tasks and advises more caution when multiple agents perform overlapping write-heavy work because coordination and merge conflicts can increase.

---

# 14. Good Multi-Agent Example

Task:

```text
Prepare implementation of the paper-trading engine.
```

Possible delegation:

```text
MAIN AGENT
Own overall implementation and integration.

SUBAGENT 1
Inspect existing portfolio and trade models.
Return architecture constraints.

SUBAGENT 2
Review docs/paper-trading.md.
Produce required acceptance cases.

SUBAGENT 3
Inspect current tests.
Identify missing execution and P&L test cases.

MAIN AGENT
Combine results.
Produce implementation plan.
Implement.
Run validation.
```

This minimizes conflicting writes.

---

# 15. Parallel Review Workflow

Multi-agent review is particularly useful.

Example prompt:

```text
Review the paper-trading implementation using parallel subagents.

Delegate:

Agent 1:
Review accounting and P&L correctness.

Agent 2:
Review execution realism and edge cases.

Agent 3:
Review risk-engine integration and trading safeguards.

Agent 4:
Review test coverage.

Wait for all agents.

Combine findings into:

- Critical
- High
- Medium
- Low

Fix Critical and High issues that are clearly within scope.

Run the complete relevant test suite afterward.
```

Codex supports explicitly requesting delegated work such as spawning multiple agents for different review categories and then having the main agent combine their findings.

---

# 16. Avoid Parallel Editing of Shared Core Files

Avoid situations where:

```text
Agent 1 edits portfolio.py

Agent 2 edits portfolio.py

Agent 3 edits portfolio.py
```

simultaneously.

Prefer:

```text
Agent 1 researches.

Agent 2 reviews.

Agent 3 identifies tests.

Main Agent implements.
```

Parallel implementation is most appropriate when modules are genuinely independent.

---

# 17. Main Agent Responsibility

The main Codex agent remains responsible for:

* understanding the user request
* respecting architecture
* assigning subagent work
* synthesizing results
* resolving contradictions
* integrating changes
* running final validation
* presenting the final result

Subagents should not independently redefine product requirements.

---

# 18. Subagent Output

Subagents should generally return summaries rather than dumping massive logs into the main context.

Useful output:

```text
Findings

Relevant files

Recommended changes

Risks

Tests needed
```

Not:

```text
17,000 lines of terminal output
```

Keeping noisy intermediate work out of the main thread is one of the documented advantages of delegated workflows.

---

# 19. Codex Skills

Repeated development workflows may eventually become Codex Skills.

A Codex Skill is defined by a `SKILL.md` file and may optionally include scripts, references, and other supporting resources. Codex can invoke skills explicitly or select them when the task matches their description.

Potential project skills:

```text
implement-roadmap-phase

add-prediction-market-provider

add-sports-data-provider

review-trading-risk

review-paper-execution

evaluate-model-change

prepare-pull-request
```

---

# 20. Recommended First Project Skill

After several phases have been completed manually, create:

```text
implement-roadmap-phase
```

The skill should teach Codex to:

```text
Read roadmap.

Read relevant specs.

Inspect existing implementation.

Map acceptance criteria.

Plan implementation.

Implement.

Test.

Review.

Update progress.

Report completion status.
```

Do not build this skill before the workflow has been used enough to understand what should be standardized.

---

# 21. Provider Integration Skill

Eventually create:

```text
add-provider
```

Possible behavior:

```text
1. Read provider abstraction.

2. Inspect existing adapters.

3. Implement provider-specific client.

4. Normalize provider responses.

5. Preserve provider IDs.

6. Add error handling.

7. Add rate-limit handling.

8. Add tests using fixtures or mocks.

9. Do not modify core business logic unless required.

10. Document provider limitations.
```

This becomes valuable when adding:

* Kalshi
* Polymarket
* sports providers
* news providers

---

# 22. Risk Review Skill

Eventually create:

```text
review-trading-risk
```

The skill should inspect changes for:

* bypassed risk engine
* live-trading exposure
* missing trading-mode checks
* incorrect bankroll math
* duplicate execution risk
* stale-data execution
* missing approval requirements
* unsafe default configuration

Any change touching execution should receive additional scrutiny.

---

# 23. MCP Usage

MCP can give Codex access to external tools and contextual systems. Current Codex clients can connect to MCP servers, and Codex desktop, CLI, and IDE environments can share MCP configuration for the same host.

Potential future uses for this project include:

```text
Documentation access

Database inspection

Monitoring systems

Analytics tools

Internal trading-system diagnostics
```

MCP should be introduced only when it solves a concrete development problem.

---

# 24. Future Prediction Bot MCP

A future read-only MCP interface could expose development diagnostics such as:

```text
get_recent_paper_trades

get_model_performance

get_calibration_metrics

get_failed_forecasts

get_execution_errors
```

Then Codex could be asked:

```text
Analyze the last 500 resolved paper trades.

Compare:

- base forecast performance
- AI-adjusted forecast performance

Identify:

- calibration problems
- market categories with poor performance
- common execution losses
- potential data-quality problems

Do not modify production strategy.

Write findings to:

docs/experiments/paper-trading-analysis-001.md
```

---

# 25. MCP Safety

Development MCP access to trading systems should initially be:

```text
READ ONLY
```

Codex should not receive MCP tools capable of:

```text
placing live trades

changing live risk limits

withdrawing funds

rotating production credentials
```

without a compelling future reason and additional safeguards.

Analysis and execution authority should remain separated.

---

# 26. Mobile Development Workflow

A typical mobile workflow may be:

```text
Desktop Host Running

↓

Open ChatGPT Mobile

↓

Connect through Remote

↓

Open Prediction Market Project

↓

Check Active Codex Task

↓

Review Progress

↓

Send Follow-Up

↓

Approve Required Action

↓

Review Tests / Diff

↓

Leave Final Code Review for Desktop
```

Remote currently supports steering active work, approving actions, and reviewing diffs and test results from the mobile app when connected to an available desktop host.

---

# 27. Example Mobile Prompt

While away from the computer:

```text
Continue the Phase 4 base forecasting implementation.

Before making additional changes, check the current branch status and summarize what remains against the Phase 4 acceptance criteria.

Focus only on remaining missing requirements.

Run the forecasting tests when complete.

Do not begin Phase 5.
```

---

# 28. Mobile Review Prompt

Example:

```text
Review the work completed so far.

Tell me:

1. Which Phase 4 acceptance criteria now pass?
2. Which remain incomplete?
3. Did any tests fail?
4. Did you make architectural changes not described in the plan?

Do not make additional code changes yet.
```

This allows the user to pause implementation and inspect progress.

---

# 29. Remote Host Considerations

When relying on Remote:

* the host machine must remain available
* the relevant project should be accessible on the host
* required development tools should be installed
* credentials needed for development should already be configured securely

On Windows, Remote requires the host desktop app to remain available, and certain computer-use tasks require the Windows session to remain unlocked.

A dedicated always-on development machine may eventually be useful but is not required.

---

# 30. Git Workflow

Every significant Codex task should begin from a clean Git state.

Recommended workflow:

```text
main

↓

feature branch

↓

Codex implementation

↓

tests

↓

human review

↓

pull request

↓

merge
```

Examples:

```text
feat/market-ingestion

feat/nba-event-matching

feat/elo-forecast

feat/paper-trading

fix/position-pnl
```

---

# 31. Git Checkpoints

Before large agentic changes:

```text
Commit current known-good state.
```

After completing a bounded feature:

```text
Review diff.

Run tests.

Commit.
```

This makes reverting bad agent changes straightforward.

The Codex CLI documentation also recommends Git checkpoints around tasks so changes remain easy to revert.

---

# 32. Commit Strategy

Commits should represent meaningful units.

Good:

```text
feat: add normalized NBA event ingestion

feat: implement Elo base forecast

test: add market matching ambiguity cases

fix: correct partial position P&L
```

Avoid one giant commit containing:

```text
market ingestion

forecasting

AI agents

dashboard redesign

Docker rewrite

and 63 unrelated formatting changes
```

---

# 33. Pull Request Workflow

Before a PR is considered ready:

```text
Tests pass.

Lint passes.

Type checking passes.

Diff reviewed.

Documentation updated if necessary.

No secrets included.

Acceptance criteria checked.
```

Codex may prepare PR summaries.

Human review should remain required for:

* architecture changes
* risk logic
* trading execution
* authentication
* live-trading code
* financial calculations

---

# 34. Diff Review Prompt

Before accepting a large Codex task:

```text
Review your own diff against the original request.

Look specifically for:

- scope creep
- unnecessary dependencies
- duplicated logic
- missing type annotations
- missing tests
- architectural violations
- unsafe trading behavior
- dead code

Fix clear issues.

Do not perform unrelated refactors.

Then summarize the final diff.
```

---

# 35. Test-First Bug Fixing

For bugs, prefer:

```text
Reproduce

↓

Add failing test

↓

Fix

↓

Confirm test passes
```

Example prompt:

```text
Investigate the incorrect realized P&L behavior.

First reproduce the bug and add a focused failing test.

Then implement the smallest correct fix.

Run all portfolio and paper-trading tests.

Do not refactor unrelated accounting code.
```

---

# 36. Codex Debugging Workflow

When a problem is unclear:

```text
1. Reproduce.

2. Collect evidence.

3. Identify likely root cause.

4. Confirm root cause.

5. Implement smallest fix.

6. Add regression test.

7. Run broader relevant tests.
```

Codex should avoid changing several possible causes simultaneously.

Otherwise it becomes difficult to know what actually fixed the problem.

---

# 37. Research Before Implementation

When integrating an external API, Codex should first investigate:

* official documentation
* authentication
* rate limits
* response models
* pagination
* WebSocket availability
* testing environment
* known restrictions

Then create the provider adapter.

Do not let Codex guess API schemas from memory.

---

# 38. Dependency Policy

Codex should not introduce major dependencies without justification.

Before adding a dependency, consider:

```text
Can the standard library handle it?

Is an existing project dependency sufficient?

Is this library actively maintained?

Does it meaningfully simplify the implementation?
```

The completion summary should mention meaningful new production dependencies.

---

# 39. Database Migration Workflow

Database schema changes should:

```text
Update model

↓

Create migration

↓

Review migration

↓

Run migration

↓

Run tests
```

Codex should not modify production-style schemas without corresponding migration support once Alembic is established.

---

# 40. Secrets

Secrets must never be committed.

Examples:

```text
API keys

Database passwords

Exchange credentials

LLM credentials

Private signing keys
```

Use:

```text
.env
```

for local secrets.

Commit:

```text
.env.example
```

with placeholder values.

---

# 41. Trading Credentials

Future live prediction-market credentials require stricter handling.

Codex should never:

* print credentials into logs
* commit credentials
* include credentials in documentation
* copy live credentials into test fixtures

Paper trading should not require live private keys.

---

# 42. Live Trading Code Review

Any future change affecting live execution must receive an explicit dedicated review.

Recommended prompt:

```text
Review this change as a financial execution safety review.

Use parallel review agents where useful.

Inspect for:

- risk-engine bypass
- duplicate execution
- retry hazards
- incorrect order sizing
- stale pricing
- partial-fill handling
- idempotency problems
- incorrect paper/live routing
- credential leakage
- kill-switch bypass

Do not modify code yet.

Return findings ranked by severity.
```

---

# 43. AI-Generated Code Is Not Assumed Correct

Codex output should be treated as:

```text
A HIGH-QUALITY ENGINEERING PROPOSAL
```

not:

```text
MAGICALLY CORRECT CODE
```

Critical financial logic should be validated through:

* tests
* invariants
* review
* simulation

---

# 44. High-Risk Components

Changes to these areas deserve extra review:

```text
Position sizing

Risk engine

Portfolio accounting

P&L calculations

Order execution

Market resolution

Live trading

Authentication

Database migrations
```

A small bug in these components may materially distort results or capital exposure.

---

# 45. Low-Risk Parallel Work

Codex may operate more autonomously on:

```text
Documentation

Dashboard presentation

Test generation

Provider fixtures

Read-only analytics

Code exploration
```

This is an appropriate place to use more aggressive parallel delegation.

---

# 46. Model Experiment Workflow

Forecasting improvements should follow:

```text
Hypothesis

↓

Implementation

↓

Historical Evaluation

↓

Shadow Forecasting

↓

Paper Trading

↓

Comparison

↓

Promotion Decision
```

Codex should never automatically promote an experimental model because it appears promising.

---

# 47. Experiment Document

Store meaningful experiments under:

```text
docs/experiments/
```

Example:

```text
docs/experiments/
    elo-rest-adjustment-001.md
```

Template:

```text
# Hypothesis

# Model Version

# Dataset

# Evaluation Metrics

# Baseline

# Results

# Limitations

# Decision
```

---

# 48. Codex Experiment Prompt

Example:

```text
Evaluate whether adding rest-day information improves nba_elo_v1.

Do not replace the current model.

Implement the new model as:

nba_elo_rest_v1

Run both models over the same historical evaluation dataset.

Compare:

- Brier score
- log loss
- calibration

Write results to:

docs/experiments/elo-rest-adjustment-001.md

Do not promote the new model automatically.
```

---

# 49. Autonomous Improvement Boundary

Codex may:

```text
Analyze failures

Propose experiments

Implement approved experiments

Run evaluations

Produce recommendations
```

Codex should not autonomously:

```text
Change live strategy

Increase risk limits

Increase bankroll

Enable live trading

Replace production models
```

These decisions remain under human control.

---

# 50. Continuous Improvement Loop

Long term:

```text
Prediction Bot Runs

↓

Forecasts and Trades Stored

↓

Evaluation Engine Produces Metrics

↓

Codex Analyzes Performance

↓

Codex Identifies Weakness

↓

Codex Proposes Experiment

↓

Human Reviews

↓

Experiment Implemented

↓

Backtest / Shadow / Paper Evaluation

↓

Promotion Decision
```

This is the preferred interpretation of a self-improving system.

The bot generates evidence.

Codex helps improve the software.

The developer retains control of strategy promotion and financial risk.

---

# 51. Suggested Daily Workflow

When actively building:

```text
START OF SESSION

Check branch

Read docs/progress.md

Choose one roadmap target

Give Codex bounded task

↓

DURING WORK

Let Codex investigate and implement

Use subagents for independent analysis

Steer from desktop or mobile when necessary

↓

END OF TASK

Run validation

Review diff

Run dedicated review for risky components

Update progress

Commit

↓

NEXT TASK
```

---

# 52. Suggested Phone Workflow

When away from the desk:

```text
Open Remote

↓

Check current task

↓

Ask for acceptance-criteria status

↓

Review failures

↓

Give narrow follow-up

↓

Approve safe required actions

↓

Leave complex diff review for desktop
```

The phone should extend the development session.

It should not lower engineering standards.

---

# 53. Avoid Endless Agent Sessions

A Codex thread should not become the permanent brain of the project.

When a task is complete:

```text
Store important decisions in repository docs.

Commit code.

Start a fresh bounded task when appropriate.
```

Durable knowledge belongs in:

```text
Code

Tests

Documentation

Git history
```

not only conversation history.

---

# 54. When to Start a New Codex Thread

Start a new thread when:

* beginning a new roadmap phase
* changing domains significantly
* the existing context has become noisy
* debugging an unrelated problem
* performing an independent review

Continue an existing thread when:

* following up on the same implementation
* fixing test failures from the current task
* reviewing the current diff

---

# 55. Definition of a Completed Codex Task

A task is not complete because:

```text
The code was written.
```

A task is complete when:

```text
Requested behavior exists.

Tests exist.

Tests pass.

Types pass.

Lint passes.

Relevant documentation is current.

The diff has been reviewed.

Known limitations are documented.
```

---

# 56. Immediate Codex Workflow

During the current early stage, the project should use the simplest workflow possible.

For Phase 0:

```text
1. Create repository documentation.

2. Give Codex Phase 0 prompt.

3. Have Codex inspect all specifications.

4. Let Codex create the initial backend and frontend structure.

5. Run validation.

6. Review the resulting architecture manually.

7. Fix Phase 0 issues.

8. Commit.

9. Begin Phase 1.
```

Do not create custom Skills or MCP servers yet.

First establish the development patterns that are worth automating.

---

# 57. First Codex Implementation Prompt

When the documentation package is complete, the first major Codex prompt should be:

```text
Implement Phase 0 from ROADMAP.md.

Before changing any files:

1. Read AGENTS.md.
2. Read README.md.
3. Read ARCHITECTURE.md.
4. Read ROADMAP.md.
5. Read all current files under docs/.
6. Inspect the repository.

Produce a concise implementation plan mapped directly to the Phase 0 acceptance criteria.

Then implement Phase 0 only.

Do not implement:

- prediction-market integrations
- sports-data integrations
- forecasting
- AI agents
- paper trading logic
- live trading

Follow the architecture and engineering rules in the repository.

Use:

- Python and FastAPI for the backend
- TypeScript and Next.js for the frontend
- PostgreSQL for the database
- Docker Compose for local development

Set up appropriate:

- testing
- linting
- type checking
- database migrations
- environment configuration
- CI

TRADING_MODE must default safely to paper.

Before completion:

1. Start or validate the development stack.
2. Run backend tests.
3. Run backend linting and type checking.
4. Run frontend linting and type checking.
5. Verify database migrations.
6. Review the complete diff for unnecessary changes.

At completion provide a checklist for every Phase 0 acceptance criterion.

Mark each:

PASS
PARTIAL
or
FAIL

Explain any non-PASS result.

Update docs/progress.md if Phase 0 is complete.

Do not begin Phase 1.
```

---

# 58. Core Codex Principle

The development philosophy is:

```text
USE CODEX FOR LEVERAGE

NOT FOR CHAOS
```

Codex should allow one developer to operate with the leverage of a larger engineering team.

That leverage comes from:

* parallel investigation
* rapid implementation
* automated testing
* code review
* documentation
* repeated evaluation

It does not remove the need for:

* architecture
* measurable requirements
* testing
* human judgment

The project should gradually give Codex more responsibility only when the development workflow proves reliable.
