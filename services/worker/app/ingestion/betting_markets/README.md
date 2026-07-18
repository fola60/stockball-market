# Worker Ingestion Betting Markets Module

## Purpose

Ingests licensed pre-match Bet365 1X2 (home/draw/away) odds observations through
an approved data feed or internal proxy. It never requests or scrapes `bet365.com`.

These reads answer: "What did external betting markets imply before the match?"

## Responsibilities

- Fetch pre-match odds from approved bookmaker, odds-provider, or exchange APIs.
- Store fixture IDs, market types, selections, odds, source, and observed timestamps.
- Preserve raw provider payloads for auditability.
- Normalize odds into decimal format.
- Derive implied probabilities where useful, while retaining the original quoted odds.
- Track provider rate limits, market availability, and stale snapshots.

## Current Scope

- Pre-match match-result (`1X2`) selections only: `HOME`, `DRAW`, and `AWAY`.
- Decimal odds, implied probability, provider event ID, observed timestamp, and raw feed payload.
- Optional linkage to an existing Stockball fixture via `stockball_fixture_provider_id`.

Lineups, player props, and match/player statistics are intentionally out of scope. They
need a separately licensed provider and should continue through fixture/stat ingestion.

## Configuration

```bash
STOCKBALL_BET365_ODDS_URL=https://licensed-odds-proxy.example/internal/bet365
STOCKBALL_BET365_API_TOKEN=replace-with-secret
STOCKBALL_BET365_REQUEST_INTERVAL_SECONDS=60
STOCKBALL_BET365_SCHEDULE_ENABLED=false
```

The endpoint must implement `GET /events` and return a JSON object shaped as:

```json
{"observed_at":"2026-07-12T12:00:00Z","events":[{"id":"provider-event-123","markets":[{"key":"1X2","selections":[{"key":"HOME","odds":2.10},{"key":"DRAW","odds":3.40},{"key":"AWAY","odds":3.60}]}]}]}
```

Run it manually with `scripts/local-ingestion.sh bet365 --league PL`, or enable the
opt-in 15-minute scheduler only after confirming licensing, credentials, and feed limits.

## Candidate Markets

- Match result: home/draw/away.
- Draw no bet.
- Asian handicap.
- Total goals.
- Both teams to score.
- Correct score.
- Future player props if licensing and coverage are clear.

## Usage

- Betting observations may feed future market-aware synthetic trader signals.
- Betting observations may support admin context around fixtures and player demand.
- Betting observations should be treated as external facts, not Stockball prices.

## Boundaries

- Does not execute trades.
- Does not directly mutate Stockball instrument prices.
- Does not decide synthetic trader orders directly.
- Does not replace executed Stockball trades as the source of price movement.
- Must not scrape or store odds from sources that prohibit automated use.
