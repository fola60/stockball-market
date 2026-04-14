# Worker Ingestion Module

## Purpose

Owns all external data intake.

Ingestion answers: "What did the outside world say?"

## Responsibilities

- Fetch or scrape external data.
- Normalize provider-specific data into internal records.
- Store raw or normalized provider observations.
- Handle provider IDs, rate limits, retries, and failures.
- Keep provider-specific code away from trading and bot strategy modules.

## Submodules

- `players`: Premier League player identity and squad data.
- `market_values`: external player market-value data.
- `fixtures`: fixture, lineup, and match-status data.
- Future `stats`: player performance data from external providers.
- Future `social`: social mention and post data from external providers.
- Future `news`: football news and transfer-rumor data.
- Future `providers`: shared provider clients, auth, rate limiting, and response normalization.

## Boundaries

- Does not execute trades.
- Does not directly change asset prices.
- Does not decide bot trades.
- Writes facts and observations that other modules can interpret.
