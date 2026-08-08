# Decision 0002: BALLDONTLIE NBA Data Ingestion

**Status:** Accepted
**Date:** 2026-08-01

## Context

Phase 2 requires provider-independent NBA team and game ingestion for upcoming schedules and completed results. The project data-source plan selects BALLDONTLIE first. Its API exposes team and game resources, uses API-key authorization, paginates list responses with cursors, and currently limits the free tier to five requests per minute.

## Decision

- Put BALLDONTLIE parsing, authentication, paging, pacing, and retry behavior behind a read-only `SportsDataProvider` protocol.
- Normalize teams and games into provider-independent immutable domain models while retaining raw source payloads for auditability.
- Represent scheduled, in-progress, final, postponed, canceled, and unknown states explicitly; scores are retained only when their state makes them meaningful.
- Store stable team and event identities derived from provider names and provider IDs, with database uniqueness constraints and idempotent upserts.
- Persist a game's referenced teams before the event within one transaction.
- Bound a game-ingestion request to 31 inclusive days and provider pagination to configured limits.
- Pace requests at 12.1 seconds by default so a single process stays within the documented free-tier request rate.
- Require `BALLDONTLIE_API_KEY` only for ingestion. Keep health checks and reads of previously persisted data available without it.
- Keep standings, team statistics, players, injuries, market-to-event matching, and forecasting out of Phase 2.

## Consequences

Downstream matching and forecasting code can consume normalized local NBA records without depending on BALLDONTLIE field names. Ingestion is deliberately batch-oriented at the free-tier rate; higher-frequency updates or multiple workers will require coordinated rate limiting or a provider-plan review. The API key is a sports-data credential only and grants no trading capability.

## References

- [BALLDONTLIE API documentation](https://docs.balldontlie.io/)
- [BALLDONTLIE teams endpoint](https://docs.balldontlie.io/#nba-teams)
- [BALLDONTLIE games endpoint](https://docs.balldontlie.io/#nba-games)
