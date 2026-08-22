# Decision 0010: Research-only MLB market classification and matching

## Context

The MLB ingestion foundation provides official teams, schedules, and results, but a market cannot be
matched safely from text or a ticker substring alone. Kalshi exposes many baseball products and
leagues, including spreads, props, futures, alternate competitions, and ordinary MLB game-winner
contracts. NBA aliases also cannot be reused safely because MLB has qualified city labels such as
Chicago C/W, Los Angeles A/D, and New York M/Y.

## Decision

- Select Kalshi's exact official `KXMLBGAME` series through the public event API.
- Classify only binary Sports events whose product metadata explicitly declares `Pro Baseball` and
  `Game`; persist league, contract type, method, policy version, and semantic fingerprint.
- Keep the legacy broad `is_nba` discovery flag separate from authoritative sports classification.
- Use a separately maintained MLB alias policy plus official first-pitch proximity. Ambiguous city
  names cannot independently identify an MLB team.
- Include league and exact market/event semantics in append-only matching fingerprints and rows.
- Permit a confident MLB result to be recorded as `matched` for research, but require
  `automatic_trading_eligible=false` in both the domain model and PostgreSQL constraint.
- Keep forecasting, opportunities, sizing, risk, execution, and settlement unavailable for MLB.

## Consequences

The platform can audit current MLB contract coverage without confusing a research link with trading
authorization. Missing schedule windows or weak identity evidence remain ambiguous/unmatched until
official data is refreshed. Adding another sport or baseball product requires a new explicit series
classification and alias policy rather than broadening the current rule implicitly.

The public adapters remain read-only and credential-free for these sources. MLB game results never
settle a Kalshi contract; only the exchange's validated official resolution record has financial
authority.
