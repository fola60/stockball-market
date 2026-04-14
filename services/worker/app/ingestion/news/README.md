# Worker Ingestion News Module

## Purpose

Future module for ingesting football news and transfer-rumor data.

## Responsibilities

- Fetch news articles or headlines from approved providers.
- Match stories to players, clubs, or fixtures.
- Store source, timestamp, URL/reference, and normalized text metadata where permitted.
- Feed later news-derived signal calculations.

## Boundaries

- Does not directly change prices.
- Does not execute trades.
- Does not decide sentiment or hype scores by itself; signal modules interpret ingested facts.
