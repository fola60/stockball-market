# Worker Ingestion Stats Module

## Purpose

Future module for ingesting football performance and availability data.

## Responsibilities

- Fetch player stats from approved football data providers.
- Store appearances, minutes, goals, assists, cards, injuries, suspensions, and other relevant observations.
- Match provider player IDs to canonical Stockball players.
- Feed later `signals/stats` calculations.

## Boundaries

- Does not decide bot trades directly.
- Does not directly change prices.
- Stat interpretation belongs to `services/worker/app/signals/stats`.
