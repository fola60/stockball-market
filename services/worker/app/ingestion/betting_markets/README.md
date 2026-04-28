# Worker Ingestion Betting Markets Module

## Purpose

Future module for ingesting pre-match football betting market observations.

These reads answer: "What did external betting markets imply before the match?"

## Responsibilities

- Fetch pre-match odds from approved bookmaker, odds-provider, or exchange APIs.
- Store fixture IDs, market types, selections, odds, source, and observed timestamps.
- Preserve raw provider payloads for auditability.
- Normalize odds into decimal format.
- Derive implied probabilities where useful, while retaining the original quoted odds.
- Track provider rate limits, market availability, and stale snapshots.

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
