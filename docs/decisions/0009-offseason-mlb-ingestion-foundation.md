# Decision 0009: Offseason MLB ingestion foundation

## Context

The NBA is out of season in August, which leaves too few current games for useful ingestion and
evaluation exercises. MLB has a dense regular-season schedule, official team and result data, and
active binary game-winner markets. The platform needs current events for testing without weakening
the NBA-specific forecasting and trading safeguards.

## Decision

- Add a second read-only sports adapter named `mlb` over the official
  `statsapi.mlb.com/api/v1` source.
- Retrieve active Major League Baseball teams from `/teams` with `sportId=1` and retrieve bounded
  schedules or one `gamePk` from `/schedule`.
- Validate the provider payload before normalization, retain the validated raw snapshot, and map
  teams and games into the existing provider-neutral `Team` and `SportsEvent` domain models with
  `league=mlb`.
- Preserve stable provider-derived database identities and reuse the existing transactional team
  and event upserts. NBA and MLB records coexist in the same normalized tables.
- Allow each ingestion request to select `provider=mlb` without changing the configured default.
  Add an explicit `league` filter to team and event reads.
- Keep the existing NBA matcher, Elo forecasts, evaluation, opportunity, sizing, risk, execution,
  and position-management paths restricted to `league=nba`. This slice cannot generate an MLB
  forecast or trade.

## Source contract

The adapter currently consumes only:

- active team identity, league, and division metadata;
- official game identity and scheduled time;
- lifecycle status and inning state;
- home/away teams and scores;
- venue, season, game type, and series description.

The provider is public and no credential is transmitted. Calls use bounded timeouts, conservative
pacing, retry only temporary failures, and fail closed on malformed or incomplete payloads.

Official MLB starting lineups, probable pitchers, Statcast, weather, injuries, prediction-market
matching, and an MLB forecast model remain separate future slices. They must receive their own
typed source contracts before affecting a probability.

## Consequences

The local platform can now ingest live MLB games and results for current-data exercises while the
NBA is idle. The normalized schema did not require a migration because it was already
provider-neutral and stored league as a bounded string.

The MLB Stats API response is treated as an external contract that may evolve. Strict validation,
raw snapshots, provider health handling, and regression fixtures protect downstream code from
silent schema drift. A provider result is sports outcome data only and is never sufficient to
settle a prediction-market position; market settlement still requires the official exchange
resolution record.
