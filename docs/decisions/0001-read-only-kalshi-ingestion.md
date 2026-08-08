# Decision 0001: Read-Only Kalshi Market Ingestion

**Status:** Accepted
**Date:** 2026-08-01

## Context

Phase 1 requires one prediction-market provider without coupling business logic to a venue or introducing trading. The project data-source plan selects Kalshi first. Current Kalshi documentation exposes public REST event and market-data endpoints and uses cursor pagination. Its current market schema uses dollar-denominated fields such as `yes_bid_dollars`; legacy cent-denominated fields are being removed.

## Decision

- Use Kalshi's production public REST API without credentials.
- Discover events with nested markets so category, series, and event metadata are available to NBA filtering.
- Put Kalshi parsing and retry behavior behind a read-only `PredictionMarketProvider` protocol.
- Normalize only binary market identity, outcomes, current prices, volume/open interest/liquidity when present, lifecycle times, rules, and raw source metadata.
- Store stable market and outcome identities, while appending one price snapshot per market retrieval timestamp.
- Retry only transient network, rate-limit, and server failures within a configured bound. Treat invalid payloads and non-retryable HTTP failures as safe provider errors.
- Keep order books, WebSockets, authentication, account access, and order placement out of Phase 1.

## Consequences

Downstream code can query normalized local records without knowing Kalshi field names. Live public prices can support realistic future paper trading, while the adapter cannot transact. Event discovery is larger than a provider-specific NBA-series request, but avoids hard-coding an unstable series ticker and makes structured filtering possible.

## References

- [Kalshi Get Events](https://docs.kalshi.com/api-reference/events/get-events)
- [Kalshi Get Markets](https://docs.kalshi.com/api-reference/market/get-markets)
- [Kalshi API changelog](https://docs.kalshi.com/changelog)
